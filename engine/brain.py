"""brain.py — the prediction engine.

A **variable-order interpolated Markov ensemble** with **discounted-Hedge
adaptive weighting**. Same family of model that backs context-mixing data
compressors, which by the Shannon source-coding equivalence is also the
optimal next-symbol predictor: every bit of compression it finds is a bit of
predictable structure in the game.

Three properties matter and all three are implemented explicitly:

1. **Never forgets** — ``fit()`` rebuilds every table from the full history,
   so a restart can never silently corrupt the model.
2. **Adapts** — counts use *lazy exponential recency decay* (exact, O(1) per
   update) and the ensemble weights are recomputed from a **discounted**
   cumulative log-loss, so stale evidence fades.
3. **Stays honest** — every reported number is measured *walk-forward*: at
   step i the model has only ever seen symbols 0..i-1. Info gain and the
   significance test are computed on those out-of-sample predictions, so a
   high confidence figure can never be an artefact of fitting the past.

At flat 3.0x odds on three symbols the book is perfectly fair, so **any**
probability above 1/3 is a real edge. The commit gate therefore tests
"better than chance", not "better than 50%".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import stats

LOG2 = math.log(2.0)
EPS = 1e-12


def _t_stat(mean: float, var: float, n: int) -> float:
    """t = mean / (s/sqrt(n)); zero variance is handled by _p_from."""
    if n < 2 or var <= 0:
        return 0.0
    return mean / math.sqrt(var / n)


def _p_from(mean: float, var: float, n: int) -> float:
    """One-sided p-value for "the mean return is greater than zero".

    The degenerate case matters: if every turn returned exactly the same
    amount the sample variance is zero, and a naive t-test falls through to
    p=0.5 — i.e. it reports "no evidence" for the most consistent possible
    record. Zero variance with a positive mean is the strongest evidence
    there is, so it gets p=0; zero variance with a flat or negative mean
    supports nothing.
    """
    if n < 2:
        return 1.0
    if var <= 0:
        return 0.0 if mean > 0 else 1.0
    return stats.norm_sf(_t_stat(mean, var, n))


def _p_greater_normal(k: int, n: int, p0: float) -> float:
    """One-sided binomial p-value, normal approximation w/ continuity correction."""
    if n <= 0:
        return 1.0
    sd = math.sqrt(n * p0 * (1.0 - p0))
    if sd <= 0:
        return 1.0
    return stats.norm_sf((k - 0.5 - n * p0) / sd)


# --------------------------------------------------------------------- decay
class DecayTable:
    """Conditional counts with *exact* lazy exponential recency decay.

    Each row remembers the time it was last touched; touching it later scales
    its counts by ``decay ** dt``. That yields exactly the same numbers as
    multiplying every count by ``decay`` on every single tick, at O(1) cost
    per update instead of O(#contexts).
    """

    __slots__ = ("decay", "rows")

    def __init__(self, decay: float):
        self.decay = float(decay)
        self.rows: Dict[Tuple[str, ...], List[Any]] = {}

    def _row(self, ctx: Tuple[str, ...], t: int) -> List[Any]:
        row = self.rows.get(ctx)
        if row is None:
            row = [{}, 0.0, t]
            self.rows[ctx] = row
            return row
        if row[2] < t:
            f = self.decay ** (t - row[2])
            if f < 1e-12:
                row = [{}, 0.0, t]
            else:
                w = {s: c * f for s, c in row[0].items() if c * f > 1e-9}
                row = [w, row[1] * f, t]
            self.rows[ctx] = row
        return row

    def add(self, ctx: Tuple[str, ...], sym: str, t: int) -> None:
        row = self._row(ctx, t)
        w = dict(row[0])
        w[sym] = w.get(sym, 0.0) + 1.0
        self.rows[ctx] = [w, row[1] + 1.0, t]

    def get(self, ctx: Tuple[str, ...], t: int) -> Tuple[Dict[str, float], float]:
        row = self._row(ctx, t)
        return row[0], row[1]

    def contexts(self) -> int:
        return len(self.rows)


# ----------------------------------------------------------------- container
@dataclass
class Prediction:
    """Everything the UI / bettor needs about one forecast."""
    probs: Dict[str, float]
    top: str
    confidence: float                     # top probability, percent
    committed: bool
    reasons: List[str]
    blockers: List[str]
    n_obs: int
    info_gain_bits: float                 # ensemble vs uniform 1/k, rolling
    info_gain_vs_base_bits: float         # ensemble vs adaptive base rate
    p_value: float                        # exact: OOS top-hit rate > 1/k
    p_value_bias: float                   # symbol frequency != uniform
    p_value_recent: float                 # same as p_value, recent window only
    base_rates: Dict[str, float]
    order_weights: Dict[int, float]
    order_losses: Dict[int, float]
    entropy_bits: float
    # --- money-side significance: is the favourite above its break-even rate?
    p_edge: float = 1.0
    p_edge_recent: float = 1.0
    break_even_pct: float = 33.33
    edge_top_pct: float = 0.0
    tier: str = "pass"            # "commit" | "provisional" | "pass"
    kelly_scale: float = 0.0      # how much of full Kelly the tier warrants
    # --- walk-forward paper trade (1 unit on the favourite, real odds)
    roi_pct: float = 0.0
    roi_p_value: float = 1.0
    roi_recent_pct: float = 0.0
    roi_n: float = 0.0

    def edges(self, payouts: Dict[str, float]) -> Dict[str, float]:
        """EV per coin staked on each colour: payout * p - 1."""
        return {s: payouts[s] * self.probs[s] - 1.0 for s in self.probs}

    def as_dict(self, payouts: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "probs": {k: round(v, 5) for k, v in self.probs.items()},
            "top": self.top,
            "confidence": round(self.confidence, 2),
            "committed": self.committed,
            "reasons": self.reasons,
            "blockers": self.blockers,
            "n_obs": self.n_obs,
            "info_gain_bits": round(self.info_gain_bits, 5),
            "info_gain_vs_base_bits": round(self.info_gain_vs_base_bits, 5),
            "p_value": round(self.p_value, 6),
            "p_value_bias": round(self.p_value_bias, 6),
            "p_value_recent": round(self.p_value_recent, 6),
            "base_rates": {k: round(v, 4) for k, v in self.base_rates.items()},
            "order_weights": {str(k): round(v, 4) for k, v in self.order_weights.items()},
            "order_losses": {str(k): round(v, 3) for k, v in self.order_losses.items()},
            "entropy_bits": round(self.entropy_bits, 4),
            "significance": stats.z_to_stars(min(self.p_value, self.p_value_bias,
                                                 self.p_edge)),
            "p_edge": round(self.p_edge, 6),
            "p_edge_recent": round(self.p_edge_recent, 6),
            "break_even_pct": round(self.break_even_pct, 2),
            "edge_top_pct": round(self.edge_top_pct, 2),
            "tier": self.tier,
            "kelly_scale": self.kelly_scale,
            "roi_pct": round(self.roi_pct, 2),
            "roi_p_value": round(self.roi_p_value, 6),
            "roi_recent_pct": round(self.roi_recent_pct, 2),
            "roi_n": int(self.roi_n),
            "gate": {"confidence": round(self.confidence, 2),
                     "break_even_pct": round(self.break_even_pct, 2),
                     "edge_top_pct": round(self.edge_top_pct, 2)},
        }
        if payouts:
            e = self.edges(payouts)
            d["edges"] = {s: round(v, 5) for s, v in e.items()}
            d["best_edge"] = round(max(e.values()), 5)
        return d


# -------------------------------------------------------------------- brain
class Brain:
    def __init__(self, settings):
        s = settings
        self.symbols: List[str] = s.symbols
        self.k = len(self.symbols)
        self.uniform = 1.0 / self.k
        self.max_order = int(s.g("brain", "max_context_order", default=5))
        self.alpha = float(s.g("brain", "interpolation_alpha", default=2.0))
        self.decay = float(s.g("brain", "recency_decay", default=0.997))
        self.eta = float(s.g("brain", "hedge_eta", default=0.6))
        self.wdecay = float(s.g("brain", "weight_decay", default=0.995))
        self.prior = 1.0                       # Dirichlet(1) on the unigram
        self.min_data = int(s.g("brain", "min_data_before_analysis", default=15))
        self.conf_thresh = float(s.g("honesty", "confidence_threshold_percent", default=38.0))
        self.min_ig = float(s.g("honesty", "min_info_gain_bits", default=0.01))
        self.max_p = float(s.g("honesty", "max_p_value", default=0.05))
        self.window = int(s.g("honesty", "recent_window", default=40))
        self.provisional_scale = float(s.g("honesty", "provisional_kelly_scale", default=0.3))
        self.provisional_tier = "provisional"
        # break-even win rate per colour: the frequency at which a bet on it is EV-neutral
        self.break_even = {sym: 1.0 / s.payout(sym) for sym in self.symbols}
        self.payouts = {sym: float(s.payout(sym)) for sym in self.symbols}
        self.reset()

    # ------------------------------------------------------------------ init
    def reset(self) -> None:
        self.tables = [DecayTable(self.decay) for _ in range(self.max_order + 1)]
        self.disc_loss = [0.0] * (self.max_order + 1)     # discounted cum log2 loss
        self.total_loss = [0.0] * (self.max_order + 1)    # undiscounted, for display
        self.weights = [1.0 / (self.max_order + 1)] * (self.max_order + 1)
        self.t = 0
        self.counts: Dict[str, float] = {s: 0.0 for s in self.symbols}
        self.hist: List[str] = []
        # walk-forward out-of-sample record. Index i holds the prediction made
        # BEFORE seeing symbol i, i.e. using only symbols 0..i-1.
        self.oos_probs: List[Dict[str, float]] = []
        self.oos_logp: List[float] = []
        self.oos_logp_base: List[float] = []
        self.oos_hit: List[bool] = []
        self.oos_committed: List[bool] = []
        self.oos_tier: List[str] = []
        self.oos_top: List[str] = []
        self.oos_actual: List[str] = []
        self.curve_accuracy: List[float] = []
        self.curve_ig: List[float] = []
        self.n_obs = 0
        self._hits_run = 0
        self._ring: List[bool] = []
        self._ring_hits = 0
        # running sums for the post-burn-in info gain, so it stays O(1)
        self._ig_sum = 0.0
        self._ig_n = 0
        # walk-forward paper-trading record: the return of a 1-unit bet on the
        # predicted colour at this game's odds, step by step. This is the
        # number the whole honesty gate is built on.
        self._roi_n = 0
        self._roi_sum = 0.0
        self._roi_sumsq = 0.0
        self._roi_ring: List[float] = []
        self._roi_ring_sum = 0.0
        self.roi_curve: List[float] = []
        self._roi_run = 0.0
        self._last_ig = 0.0
        self._last_ig_base = 0.0

    # ------------------------------------------------------------- internals
    def _normalised_weights(self) -> List[float]:
        lo = min(self.disc_loss)
        raw = [math.exp(-self.eta * (l - lo)) for l in self.disc_loss]
        tot = sum(raw) or 1.0
        return [r / tot for r in raw]

    def _order_probs(self, hist: Sequence[str]) -> List[Dict[str, float]]:
        """Interpolated chain P_0 -> P_1 -> ... -> P_K (Jelinek-Mercer backoff)."""
        t = self.t
        w0, tot0 = self.tables[0].get((), t)
        den = tot0 + self.prior * self.k
        p_prev = {s: (w0.get(s, 0.0) + self.prior) / den for s in self.symbols}
        out = [p_prev]
        for order in range(1, self.max_order + 1):
            if len(hist) < order:
                out.append(dict(p_prev))       # not enough context yet
                continue
            ctx = tuple(hist[-order:])
            w, tot = self.tables[order].get(ctx, t)
            den = tot + self.alpha
            pk = {s: (w.get(s, 0.0) + self.alpha * p_prev[s]) / den
                  for s in self.symbols}
            out.append(pk)
            p_prev = pk
        return out

    def _blend(self, order_probs: Sequence[Dict[str, float]],
               weights: Sequence[float]) -> Dict[str, float]:
        tot = sum(weights) or 1.0
        return {s: sum(w * op[s] for w, op in zip(weights, order_probs)) / tot
                for s in self.symbols}

    # ------------------------------------------------------------------- fit
    def fit(self, seq: Sequence[str]) -> "Brain":
        """Rebuild the whole model from scratch, walk-forward, on ``seq``."""
        self.reset()
        for sym in seq:
            if sym in self.counts:
                self.observe(sym)
        return self

    def observe(self, sym: str) -> Dict[str, float]:
        """Advance the model by one symbol. Returns the OOS prediction used.

        O(K) work — this is what makes live play and long auto-simulations
        fast; ``fit()`` is just ``reset()`` + a loop of these.

        Ordering matters for honesty: the commit decision and the info-gain
        figure recorded for step ``i`` are computed from state that reflects
        **only symbols 0..i-1** — exactly what was known before this result
        was revealed. The backtest and the auto-simulator both consume those
        flags, so neither can peek.
        """
        if sym not in self.counts:
            raise ValueError(f"unknown symbol {sym!r}")
        weights = self._normalised_weights()
        ops = self._order_probs(self.hist)
        ens = self._blend(ops, weights)
        base = ops[0]
        top = max(ens, key=lambda s: ens[s])
        i = self.n_obs

        # ---- honest, pre-outcome gate for this step (uses data 0..i-1 only)
        ig_pre, _ = self._ig_window(i)
        conf_pre = 100.0 * ens[top]
        ev = self._evidence(top, conf_pre, self.ig_all(), ig_pre, fast=True)
        tier, _scale, _b, _r = self._tier(ev, top)
        self.oos_tier.append(tier)
        self.oos_committed.append(tier == "commit")
        self.curve_ig.append(ig_pre)

        # ---- record out-of-sample evidence
        p_act = max(ens.get(sym, EPS), EPS)
        p_base = max(base.get(sym, EPS), EPS)
        self.oos_probs.append(ens)
        self.oos_logp.append(math.log(p_act) / LOG2)
        self.oos_logp_base.append(math.log(p_base) / LOG2)
        if i >= self.min_data:
            self._ig_sum += math.log(p_act) / LOG2
            self._ig_n += 1
        # paper trade: 1 unit on the colour the model liked, settled at these odds
        roi = (self.payouts.get(top, 1.0) if top == sym else 0.0) - 1.0
        self._roi_run += roi
        self.roi_curve.append(self._roi_run / (i + 1))
        if i >= self.min_data:
            self._roi_n += 1
            self._roi_sum += roi
            self._roi_sumsq += roi * roi
        self._roi_ring.append(roi)
        self._roi_ring_sum += roi
        if self.window > 0 and len(self._roi_ring) > self.window:
            self._roi_ring_sum -= self._roi_ring.pop(0)
        self.oos_top.append(top)
        self.oos_actual.append(sym)
        hit = top == sym
        self.oos_hit.append(hit)
        self._hits_run += 1 if hit else 0
        self.curve_accuracy.append(100.0 * self._hits_run / (i + 1))
        # rolling window of hits, maintained in O(window) so significance can
        # be recomputed cheaply on every step of a long auto-simulation
        self._ring.append(hit)
        if hit:
            self._ring_hits += 1
        if self.window > 0 and len(self._ring) > self.window:
            if self._ring.pop(0):
                self._ring_hits -= 1

        # ---- learn
        for kk, op in enumerate(ops):
            inc = -math.log(max(op.get(sym, EPS), EPS)) / LOG2
            self.disc_loss[kk] = self.disc_loss[kk] * self.wdecay + inc
            self.total_loss[kk] += inc
        self.weights = self._normalised_weights()
        self.tables[0].add((), sym, self.t)
        for order in range(1, self.max_order + 1):
            if len(self.hist) >= order:
                self.tables[order].add(tuple(self.hist[-order:]), sym, self.t)
        self.counts[sym] += 1.0
        self.t += 1
        self.n_obs += 1
        self.hist.append(sym)
        self._last_ig, self._last_ig_base = self._ig_window(self.n_obs)
        return ens

    # ------------------------------------------------------- edge measurement
    def _ig_window(self, n_end: int) -> Tuple[float, float]:
        """Out-of-sample info gain in bits/symbol over a recent window.

        ``ig`` is measured against a uniform 1/k predictor: that is the edge
        you can actually cash at flat odds. ``ig_base`` is measured against
        the model's own adaptive base rate, which isolates *sequential*
        structure over and above a simple frequency bias.

        The first ``min_data`` steps are excluded (burn-in): a model with no
        data is necessarily miscalibrated, and scoring it would just measure
        how long the warm-up was, not whether the game is predictable.
        """
        if n_end <= self.min_data or not self.oos_logp:
            return 0.0, 0.0
        lo = n_end - self.window if self.window > 0 else 0
        lo = max(self.min_data, lo, 0)
        seg = self.oos_logp[lo:n_end]
        segb = self.oos_logp_base[lo:n_end]
        if not seg:
            return 0.0, 0.0
        uniform_bits = math.log(self.k) / LOG2
        ig = sum(x + uniform_bits for x in seg) / len(seg)
        igb = sum(a - b for a, b in zip(seg, segb)) / len(seg)
        return ig, igb

    def ig_all(self, n_end: Optional[int] = None) -> float:
        """Info gain over the whole post-burn-in history (not just the window).

        O(1) via running sums. Because the accumulator is only updated *after*
        a step is scored, calling this mid-step returns the figure computed
        from data that excludes the current outcome — exactly what the
        walk-forward gate needs.
        """
        if n_end is None or n_end >= self.n_obs:
            n, total = self._ig_n, self._ig_sum
        else:
            lo = self.min_data
            n = max(0, n_end - lo)
            total = sum(self.oos_logp[lo:n_end]) if n else 0.0
        if n <= 0:
            return 0.0
        return total / n + math.log(self.k) / LOG2

    def roi_stats(self) -> Dict[str, float]:
        """Walk-forward paper-trading results for "1 unit on the top colour".

        A one-sample t-test on the per-step return: the null is "this model
        makes no money at these odds". Because the returns are settled at the
        game's real payouts, a positive and significant mean is the only
        evidence that actually justifies staking — significance of a colour's
        *frequency* is not the same claim, and for a model that switches its
        favourite (transition patterns) the frequency test throws the signal
        away.
        """
        n = self._roi_n
        out = {"n": float(n), "mean_pct": 0.0, "se_pct": 0.0, "t": 0.0,
               "p_value": 1.0, "recent_mean_pct": 0.0, "recent_n": float(len(self._roi_ring)),
               "recent_p_value": 1.0, "hit_rate_pct": 0.0}
        if n >= 2:
            mean = self._roi_sum / n
            var = max(self._roi_sumsq / n - mean * mean, 0.0) * n / (n - 1)
            out.update({"mean_pct": 100.0 * mean, "se_pct": 100.0 * math.sqrt(var / n)
                        if var > 0 else 0.0, "t": _t_stat(mean, var, n),
                        "p_value": _p_from(mean, var, n)})
        rn = len(self._roi_ring)
        if rn >= 2:
            rm = self._roi_ring_sum / rn
            rvar = max(sum((x - rm) ** 2 for x in self._roi_ring) / (rn - 1), 0.0)
            out.update({"recent_mean_pct": 100.0 * rm,
                        "recent_p_value": _p_from(rm, rvar, rn)})
        return out

    def _p_bias(self, fast: bool = False) -> Tuple[float, float]:
        tot = sum(self.counts.values()) or 1.0
        chi2 = stats.chi_square_uniform(self.counts, tot, self.k)
        p = stats.chi_square_sf_fast(chi2, self.k - 1) if fast \
            else stats.chi_square_sf(chi2, self.k - 1)
        return chi2, p

    # ------------------------------------------------------------- the gate
    def _evidence(self, top: str, conf: float, ig_all: float, ig_win: float,
                  fast: bool) -> Dict[str, float]:
        """Assemble every significance number the gate consumes.

        The headline test is ``p_edge``: a one-sided binomial test that the
        predicted favourite's *observed frequency* exceeds its break-even
        frequency (1 / payout). That is the exact question the money asks, and
        it is far more powerful than an omnibus chi-square, which spreads its
        sensitivity across all k-1 degrees of freedom.
        """
        n = self.n_obs
        be = self.break_even.get(top, self.uniform) if top else self.uniform
        tot = sum(self.counts.values()) or 1.0
        cnt_top = self.counts.get(top, 0.0) if top else 0.0
        w = self.window if self.window > 0 else 0
        recent = self.oos_actual[-w:] if w else []
        cnt_top_rec = sum(1 for x in recent if x == top) if top else 0
        if fast:
            p_edge = _p_greater_normal(int(cnt_top), n, be)
            p_edge_rec = _p_greater_normal(cnt_top_rec, len(recent), be) if recent else 1.0
            p_hits = _p_greater_normal(self._hits_run, n, self.uniform)
            p_hits_rec = (_p_greater_normal(self._ring_hits, len(self._ring), self.uniform)
                          if self._ring else 1.0)
            p_bias = self._p_bias(fast=True)[1]
        else:
            p_edge = stats.binom_test_greater(int(cnt_top), n, be) if n else 1.0
            p_edge_rec = (stats.binom_test_greater(cnt_top_rec, len(recent), be)
                          if recent else 1.0)
            p_hits = stats.binom_test_greater(self._hits_run, n, self.uniform) if n else 1.0
            p_hits_rec = (stats.binom_test_greater(self._ring_hits, len(self._ring),
                                                   self.uniform) if self._ring else 1.0)
            p_bias = self._p_bias(fast=False)[1]
        roi = self.roi_stats()
        return {"n": float(n), "conf": conf, "ig_all": ig_all, "ig_win": ig_win,
                "break_even": 100.0 * be,
                "top_freq": 100.0 * cnt_top / tot if tot else 0.0,
                "top_count": cnt_top,
                "p_edge": p_edge, "p_edge_recent": p_edge_rec,
                "p_hits": p_hits, "p_hits_recent": p_hits_rec, "p_bias": p_bias,
                "roi_pct": roi["mean_pct"], "roi_p_value": roi["p_value"],
                "roi_recent_pct": roi["recent_mean_pct"],
                "roi_recent_p_value": roi["recent_p_value"],
                "roi_n": roi["n"]}

    def _tier(self, ev: Dict[str, float], top: str
              ) -> Tuple[str, float, List[str], List[str]]:
        """commit / provisional / pass, with the reasoning spelled out.

        ``commit`` needs three things at once, which is deliberately hard:

        1. confidence above the configured gate;
        2. a **positive and significant walk-forward paper-trade**: betting
           1 unit on the model's favourite colour at the game's real odds,
           every turn since warm-up, made money — tested with a one-sample
           t-test on the per-turn returns, at a Bonferroni-corrected alpha
           (we inspect k colours, and this test is run every turn, so a
           naive 5% would manufacture a "system" out of a fair game);
        3. a positive **out-of-sample** compression edge over the whole
           post-warm-up history, i.e. proof it generalises, not just fits.

        ``provisional`` means the paper-trade is positive but not yet
        Bonferroni-significant, or the compression edge is still short of
        the bar: real signal, unproven edge. The bot then stakes only a
        fraction of Kelly and says so out loud.
        """
        blockers: List[str] = []
        reasons: List[str] = []
        n = int(ev["n"])
        if n < self.min_data:
            return "pass", 0.0, [f"warming up — {n}/{self.min_data} results seen"], []

        bonf = self.max_p / self.k
        conf, ig_all = ev["conf"], ev["ig_all"]
        roi_pct = ev["roi_pct"]
        # a non-positive paper trade is not "unsignificant", it is disqualifying,
        # so its p-value is pinned to 1.0 rather than reported as something small
        p_roi = ev["roi_p_value"] if roi_pct > 0 else 1.0
        p_roi_rec = ev["roi_recent_p_value"]
        p_edge_best = min(ev["p_edge"], ev["p_edge_recent"])

        ok_conf = conf >= self.conf_thresh
        ok_roi = roi_pct > 0 and p_roi <= self.max_p
        ok_roi_strict = roi_pct > 0 and p_roi <= bonf
        ok_oos = ig_all >= self.min_ig

        if ok_conf:
            reasons.append(f"confidence {conf:.1f}% clears the {self.conf_thresh:.0f}% gate")
        else:
            blockers.append(f"confidence {conf:.1f}% below the {self.conf_thresh:.0f}% gate")

        if ok_roi:
            star = " (Bonferroni-significant)" if ok_roi_strict else ""
            reasons.append(f"paper trade: 1 unit on the favourite every turn since warm-up "
                           f"returns {roi_pct:+.1f}% (p={p_roi:.4f}){star}")
        else:
            blockers.append(f"paper trade is {roi_pct:+.1f}% per unit staked — no proven "
                            f"profit at these odds (p={p_roi:.3f})")

        if ok_oos:
            reasons.append(f"{ig_all:+.4f} bits/symbol of out-of-sample edge over the whole "
                           f"post-warm-up history — it generalises, not just fits")
        else:
            blockers.append(f"out-of-sample edge is only {ig_all:+.4f} bits/symbol "
                            f"(needs {self.min_ig}) — the bias is not yet proven on unseen data")

        if p_edge_best <= self.max_p:
            reasons.append(f"{(top or '?').upper()} also beats its {ev['break_even']:.1f}% "
                           f"break-even frequency on its own (p={p_edge_best:.4f})")
        if min(ev["p_hits"], ev["p_hits_recent"]) <= self.max_p:
            reasons.append(f"top-pick hit rate beats chance "
                           f"(p={min(ev['p_hits'], ev['p_hits_recent']):.4f})")
        if roi_pct > 0 and p_roi_rec <= self.max_p:
            reasons.append(f"the recent window agrees: {ev['roi_recent_pct']:+.1f}% "
                           f"(p={p_roi_rec:.4f})")

        if ok_conf and ok_roi_strict and ok_oos:
            return "commit", 1.0, [], reasons

        # ------------------------------------------------- topping up to a stake
        # Failing the commit bar does not automatically mean "pass": there are
        # two independent ways to be right, and requiring both is too strict.
        #
        #   (a) the colour you back comes in more often than its break-even
        #       rate  -> profitable regardless of how sharp your probabilities are
        #   (b) your probabilities are sharper than uniform  -> the paper trade
        #       proves it with money
        #
        # Either can be real on its own, so a stake is licensed by ONE line of
        # evidence that survives the Bonferroni correction for the k colours we
        # inspect every single turn.
        #
        # What must NOT license a stake is a signal that only passes at the
        # UNCORRECTED 5% bar. That bar is evaluated every turn and across every
        # colour, so on a fair game it fires constantly and the small "hedged"
        # positions compound into ruinous variance — measured at 74-82% peak
        # drawdowns on simulated fair games. Marginal evidence buys nothing.
        #
        # So: a stake requires at least one line of evidence that survives the
        # Bonferroni correction, and (because backing your own favourite at a
        # loss is self-refuting whatever the frequency says) a paper trade that
        # is not negative.
        roi_corrected = p_roi <= bonf                       # money says yes, corrected
        freq_corrected = roi_pct >= 0 and p_edge_best <= bonf  # frequency says yes, corrected
        if ok_conf and (roi_corrected or freq_corrected):
            return self.provisional_tier, self.provisional_scale, blockers, reasons

        if ok_conf and min(p_roi, p_edge_best) <= self.max_p:
            blockers.append(
                f"the only supporting evidence is uncorrected (p="
                f"{min(p_roi, p_edge_best):.4f}, needs {bonf:.4f} across {self.k} "
                f"colours) — it would fire on a fair game too, so no stake")
        return "pass", 0.0, blockers, reasons

    # --------------------------------------------------------------- predict
    def predict(self, extra: Sequence[str] = (), fast: bool = False) -> Prediction:
        """Forecast the next symbol (``extra`` = results not yet observed).

        ``fast=True`` swaps the exact binomial tail for its normal
        approximation. The live game uses exact arithmetic (it is human-paced);
        the auto-simulator uses fast, since it evaluates thousands of turns.
        """
        hist = self.hist if not extra else self.hist + list(extra)
        weights = self._normalised_weights()
        ops = self._order_probs(hist)
        ens = self._blend(ops, weights)
        top = max(ens, key=lambda s: ens[s])
        conf = 100.0 * ens[top]

        n = self.n_obs
        ig, igb = self._ig_window(n)
        tot = sum(self.counts.values()) or 1.0
        base_rates = {s: self.counts[s] / tot for s in self.symbols}
        ev = self._evidence(top, conf, self.ig_all(), ig, fast=fast)
        tier, scale, blockers, reasons = self._tier(ev, top)

        return Prediction(
            probs=ens, top=top, confidence=conf, committed=(tier == "commit"),
            reasons=reasons, blockers=blockers, n_obs=n,
            info_gain_bits=ig, info_gain_vs_base_bits=igb,
            p_value=ev["p_hits"], p_value_bias=ev["p_bias"],
            p_value_recent=ev["p_hits_recent"],
            base_rates=base_rates,
            order_weights={o: weights[o] for o in range(len(weights))},
            order_losses={o: self.total_loss[o] / max(n, 1) for o in range(len(weights))},
            entropy_bits=stats.entropy_bits(ens.values()),
            p_edge=ev["p_edge"], p_edge_recent=ev["p_edge_recent"],
            break_even_pct=ev["break_even"],
            edge_top_pct=ev["top_freq"] - ev["break_even"],
            tier=tier, kelly_scale=scale,
            roi_pct=ev["roi_pct"], roi_p_value=ev["roi_p_value"],
            roi_recent_pct=ev["roi_recent_pct"], roi_n=ev["roi_n"],
        )

    # ---------------------------------------------------------------- extras
    def pattern_report(self, order: int = 2, min_n: int = 6,
                       seq: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Per-pattern accuracy: after context X, what actually follows?"""
        seq = list(seq if seq is not None else self.hist)
        buckets: Dict[Tuple[str, ...], Dict[str, int]] = {}
        for i in range(order, len(seq)):
            ctx = tuple(seq[i - order:i])
            buckets.setdefault(ctx, {s: 0 for s in self.symbols})[seq[i]] += 1
        tot_all = max(len(seq), 1)
        glob = {s: sum(1 for x in seq if x == s) / tot_all for s in self.symbols}
        out: List[Dict[str, Any]] = []
        for ctx, cnt in buckets.items():
            n = sum(cnt.values())
            if n < min_n:
                continue
            top = max(cnt, key=lambda s: cnt[s])
            share = cnt[top] / n
            lift = share / glob[top] if glob[top] > 0 else 0.0
            p = stats.binom_test_greater(cnt[top], n, max(glob[top], 1e-9))
            out.append({
                "context": list(ctx),
                "label": "".join(ctx).upper(),
                "n": n,
                "counts": dict(cnt),
                "top": top,
                "share": round(share, 4),
                "base": round(glob[top], 4),
                "lift": round(lift, 3),
                "p_value": round(p, 5),
                "significant": p <= self.max_p,
                "edges": {s: round(cnt[s] / n, 4) for s in self.symbols},
            })
        out.sort(key=lambda r: (not r["significant"], -r["lift"], -r["n"]))
        return out

    def curves(self, buckets: int = 140) -> Dict[str, List[float]]:
        """Downsampled learning curves for the dashboard."""
        acc, ig = self.curve_accuracy, self.curve_ig
        if not acc:
            return {"accuracy": [], "info_gain": []}
        if len(acc) <= buckets:
            return {"accuracy": [round(a, 3) for a in acc],
                    "info_gain": [round(g, 5) for g in ig]}
        step = len(acc) / buckets
        return {"accuracy": [round(acc[int(i * step)], 3) for i in range(buckets)],
                "info_gain": [round(ig[int(i * step)], 5) for i in range(buckets)]}

    def stats_snapshot(self) -> Dict[str, Any]:
        n = self.n_obs
        hits = sum(1 for h in self.oos_hit if h)
        tot = sum(self.counts.values()) or 1.0
        return {
            "n_obs": n,
            "oos_hit_rate_pct": round(100.0 * hits / n, 2) if n else 0.0,
            "oos_hits": hits,
            "chance_pct": round(100.0 * self.uniform, 2),
            "contexts_learned": sum(t.contexts() for t in self.tables),
            "log_loss_bits": round(-sum(self.oos_logp) / n, 4) if n else round(math.log(self.k) / LOG2, 4),
            "chance_log_loss_bits": round(math.log(self.k) / LOG2, 4),
            "ig_window_bits": round(self._last_ig, 5),
            "ig_all_bits": round(self.ig_all(), 5),
            "ig_vs_base_bits": round(self._last_ig_base, 5),
            "committed_steps": sum(1 for c in self.oos_committed if c),
            "provisional_steps": sum(1 for t in self.oos_tier if t == "provisional"),
            "paper_roi_pct": round(self.roi_stats()["mean_pct"], 2),
            "paper_roi_p_value": round(self.roi_stats()["p_value"], 5),
            "counts": {s: int(self.counts[s]) for s in self.symbols},
            "freq_pct": {s: round(100.0 * self.counts[s] / tot, 2) for s in self.symbols},
            "order_weights": {str(o): round(w, 4)
                              for o, w in enumerate(self._normalised_weights())},
            "order_avg_loss_bits": {str(o): round(self.total_loss[o] / max(n, 1), 4)
                                    for o in range(self.max_order + 1)},
        }
