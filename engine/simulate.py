"""simulate.py — the headless lab.

Answers the question a tracker can't: *"if I keep playing this way, what
happens to my bankroll over 2,000 turns?"* It runs the exact same brain and
betting math as live play, but the results come from a synthetic source with
known ground truth — so a strategy's real edge (or lack of one) shows up
instead of hiding behind luck.

Sources
    fair           uniform 1/3 each — the null hypothesis. Nothing beats it.
    biased         one colour over-represented (defaults to your old data's
                   green lean, 44%), exploitable by base rate alone
    markov         subtle sequential structure — real, but too weak to be
                   worth 3x odds; the correct play is to hedge, and a bot
                   that bets hard here is lying to you
    markov_strong  strong streaks (+74% edge after a repeat) — a working bot
                   must find this and stake up
    replay         loops your own recorded results
    custom         probabilities you supply

Policies
    bot            follow the brain, but only when the honesty gate commits
    bot_loose      follow the brain whenever any colour has positive EV
    split_two      YOUR strategy: fixed stake on a fixed pair of colours
    always_top     fixed stake on the brain's top colour, gate ignored
    fixed_colour   fixed stake on one colour forever
    martingale     double after a loss, reset after a win
    mirror_you     replay your own recorded stake vectors, cycled
    random         random colour, fixed stake

Every policy is run under identical rules: it predicts before the symbol is
drawn, stakes are clamped to available capital, and a bankroll below the
minimum stake is a bust that ends the run.
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import betting, stats
from .brain import Brain
from .settings import Settings

# Two transition matrices, so the lab can show the difference between
# "looks streaky" and "is worth 3x odds".
#
# MARKOV_DEMO has real but *subtle* dependence: the long-run frequencies stay
# near 1/3, so the exploit is worth only a couple of tenths of a percent per
# turn. A naive system would bet this happily. The honest answer is to hedge.
MARKOV_DEMO = {
    "r": {"r": 0.46, "b": 0.29, "g": 0.25},
    "b": {"r": 0.27, "b": 0.47, "g": 0.26},
    "g": {"r": 0.33, "b": 0.33, "g": 0.34},
}
# MARKOV_STRONG is unmistakably exploitable: after red you get red 58% of the
# time, i.e. +74% edge on a 3x payout. If the bot cannot find THIS, it is
# broken; if it bets hard on MARKOV_DEMO, it is over-trading.
MARKOV_STRONG = {
    "r": {"r": 0.58, "b": 0.21, "g": 0.21},
    "b": {"r": 0.21, "b": 0.58, "g": 0.21},
    "g": {"r": 0.30, "b": 0.30, "g": 0.40},
}


class Source:
    """A result generator with known ground truth."""

    def __init__(self, kind: str, symbols: Sequence[str], rng: random.Random,
                 probs: Optional[Dict[str, float]] = None,
                 matrix: Optional[Dict[str, Dict[str, float]]] = None,
                 history: Optional[Sequence[str]] = None):
        self.kind = kind
        self.symbols = list(symbols)
        self.rng = rng
        self.probs = probs or {s: 1.0 / len(self.symbols) for s in self.symbols}
        self.matrix = matrix
        self.history = list(history or [])
        self.i = 0
        self.last: Optional[str] = None
        self._cum = self._cumulative(self.probs)
        self.drawn = 0

    @staticmethod
    def _cumulative(probs: Dict[str, float]) -> List[tuple]:
        tot = sum(probs.values()) or 1.0
        acc, out = 0.0, []
        for s, p in probs.items():
            acc += p / tot
            out.append((s, acc))
        return out

    def _draw(self, probs: Dict[str, float]) -> str:
        x = self.rng.random()
        for s, c in self._cumulative(probs):
            if x <= c:
                return s
        return self.symbols[-1]

    def next(self) -> str:
        self.drawn += 1
        if self.kind == "replay":
            if not self.history:
                return self._draw(self.probs)
            s = self.history[self.i % len(self.history)]
            self.i += 1
            self.last = s
            return s
        if self.kind in ("markov", "markov_strong") and self.last and self.matrix:
            s = self._draw(self.matrix.get(self.last, self.probs))
        else:
            s = self._draw(self.probs)
        self.last = s
        return s


def make_source(kind: str, symbols: Sequence[str], seed: Optional[int] = None,
                history: Optional[Sequence[str]] = None,
                probs: Optional[Dict[str, float]] = None,
                matrix: Optional[Dict[str, Dict[str, float]]] = None) -> Source:
    rng = random.Random(seed)
    syms = list(symbols)
    if kind == "fair":
        p = {s: 1.0 / len(syms) for s in syms}
    elif kind == "biased":
        p = probs or {syms[0]: 0.28, syms[1]: 0.28, syms[2]: 0.44}
    elif kind == "markov":
        p = probs or {s: 1.0 / len(syms) for s in syms}
        matrix = matrix or MARKOV_DEMO
    elif kind == "markov_strong":
        p = probs or {s: 1.0 / len(syms) for s in syms}
        matrix = matrix or MARKOV_STRONG
    elif kind == "replay":
        p = probs or {s: 1.0 / len(syms) for s in syms}
    elif kind == "custom":
        p = probs or {s: 1.0 / len(syms) for s in syms}
        tot = sum(p.values())
        p = {s: v / tot for s, v in p.items()}
    else:
        raise ValueError(f"unknown source {kind!r}")
    return Source(kind, syms, rng, probs=p, matrix=matrix, history=history)


# ------------------------------------------------------------------- policies
def make_policy(name: str, settings: Settings, opts: Dict[str, Any]) -> Callable[..., Dict[str, float]]:
    symbols = settings.symbols
    payouts = settings.payouts
    cap = settings.data["capital"]
    bot_cfg = settings.data["bot_bet"]
    bet_cfg = {"stake_step": cap["stake_step"], "min_stake": cap["min_stake"],
               "max_stake_per_turn": cap["max_stake_per_turn"],
               "max_exposure_fraction": cap["max_exposure_fraction"],
               "provisional_kelly_scale":
                   settings.g("honesty", "provisional_kelly_scale", default=0.3),
               **bot_cfg}
    step = float(cap["stake_step"])
    flat = float(opts.get("stake", cap.get("default_split_stake", 120)))
    pair = list(opts.get("split_pair") or [symbols[0], symbols[1]])
    colour = opts.get("colour") or symbols[0]
    mirror = list(opts.get("mirror_bets") or [])
    rng = random.Random(opts.get("seed", 7))
    state: Dict[str, Any] = {"stake": flat, "step": 0}

    def clamp(st: Dict[str, float], capital: float) -> Dict[str, float]:
        st = {s: max(0.0, float(v)) for s, v in st.items() if s in symbols}
        st = {s: betting.round_to_step(v, step) for s, v in st.items()}
        st = {s: v for s, v in st.items() if v >= float(cap["min_stake"])}
        tot = sum(st.values())
        if tot > capital:
            k = capital / tot
            st = {s: betting.round_to_step(v * k, step) for s, v in st.items()}
            st = {s: v for s, v in st.items() if v >= float(cap["min_stake"])}
        return {s: st.get(s, 0) for s in symbols}

    def zero() -> Dict[str, float]:
        return {s: 0 for s in symbols}

    def policy(pred, capital: float, ctx: Dict[str, Any]) -> Dict[str, float]:
        if name == "bot":
            if not pred.committed:
                return zero()
            return clamp(betting.kelly_stakes(pred.probs, payouts, symbols,
                                              capital, bet_cfg)["stakes"], capital)
        if name == "bot_loose":
            k = betting.kelly_stakes(pred.probs, payouts, symbols, capital, bet_cfg)
            return clamp(k["stakes"], capital) if k.get("total") else zero()
        if name == "split_two":
            st = zero()
            st[pair[0]] = flat
            if len(pair) > 1:
                st[pair[1]] = flat
            return clamp(st, capital)
        if name == "always_top":
            return clamp({**zero(), pred.top: flat}, capital)
        if name == "fixed_colour":
            return clamp({**zero(), colour: flat}, capital)
        if name == "martingale":
            prev_pnl = ctx.get("prev_pnl")
            if prev_pnl is not None:
                if prev_pnl < 0 and state["step"] < int(opts.get("max_steps", 6)):
                    state["step"] += 1
                elif prev_pnl > 0:
                    state["step"] = 0
            stake = flat * (2 ** state["step"])
            return clamp({**zero(), pred.top: stake}, capital)
        if name == "mirror_you":
            if not mirror:
                return zero()
            st = mirror[ctx["turn"] % len(mirror)]
            return clamp(st, capital)
        if name == "random":
            return clamp({**zero(), rng.choice(symbols): flat}, capital)
        raise ValueError(f"unknown policy {name!r}")

    policy.name = name          # type: ignore[attr-defined]
    return policy


# ----------------------------------------------------------------------- run
def run(source_kind: str, policy_name: str, turns: int, settings: Settings,
        start_capital: Optional[float] = None, seed: int = 0,
        opts: Optional[Dict[str, Any]] = None,
        history: Optional[Sequence[str]] = None,
        probs: Optional[Dict[str, float]] = None,
        warm: Optional[Sequence[str]] = None,
        collect_curve: bool = True) -> Dict[str, Any]:
    """Run one headless session. Returns metrics + bankroll curve."""
    opts = dict(opts or {})
    symbols = settings.symbols
    payouts = settings.payouts
    min_stake = float(settings.g("capital", "min_stake", default=10))
    capital = float(start_capital if start_capital is not None
                    else settings.g("capital", "starting", default=1000))
    start = capital
    src = make_source(source_kind, symbols, seed=seed, history=history, probs=probs)
    brain = Brain(settings)
    if warm:
        brain.fit(list(warm))
    policy = make_policy(policy_name, settings, opts)

    curve: List[float] = [capital]
    peak = capital
    max_dd = 0.0
    max_dd_frac = 0.0
    bets = wins = losses = pushes = 0
    staked_total = 0.0
    pnl_total = 0.0
    top_hits = top_n = 0
    committed_hits = committed_n = 0
    results: List[str] = []
    ruined_at = None
    prev_pnl: Optional[float] = None
    exposure_sum = 0.0

    for i in range(turns):
        if capital < min_stake:
            ruined_at = i
            break
        pred = brain.predict(fast=True)
        stakes = policy(pred, capital, {"turn": i, "prev_pnl": prev_pnl,
                                        "capital": capital, "history": results[-8:]})
        total = sum(stakes.values())
        sym = src.next()
        results.append(sym)
        top_n += 1
        top_hits += 1 if pred.top == sym else 0
        if pred.committed:
            committed_n += 1
            committed_hits += 1 if pred.top == sym else 0
        if total > 0:
            total = min(total, capital)
            k = total / max(sum(stakes.values()), 1e-9)
            stakes = {s: v * k for s, v in stakes.items()}
            ret = payouts[sym] * stakes.get(sym, 0.0)
            pnl = ret - total
            capital += pnl
            staked_total += total
            pnl_total += pnl
            exposure_sum += total / max(start, 1e-9)
            bets += 1
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            else:
                pushes += 1
            prev_pnl = pnl
        else:
            prev_pnl = 0.0
        brain.observe(sym)
        curve.append(capital)
        peak = max(peak, capital)
        dd = peak - capital
        if dd > max_dd:
            max_dd = dd
            max_dd_frac = dd / peak if peak > 0 else 0.0

    n_played = len(curve) - 1
    dd_abs, dd_frac = stats.max_drawdown(curve)
    out: Dict[str, Any] = {
        "source": source_kind, "policy": policy_name, "seed": seed,
        "turns_requested": turns, "turns_played": n_played,
        "start_capital": round(start, 2),
        "final_capital": round(capital, 2),
        "pnl": round(capital - start, 2),
        "roi_pct": round(100 * (capital - start) / start, 2) if start else 0.0,
        "bets": bets, "wins": wins, "losses": losses, "pushes": pushes,
        "pass_turns": n_played - bets,
        "win_rate_pct": round(100 * wins / bets, 2) if bets else 0.0,
        "staked": round(staked_total, 2),
        "stake_roi_pct": round(100 * pnl_total / staked_total, 2) if staked_total else 0.0,
        "avg_exposure_pct": round(100 * exposure_sum / max(bets, 1), 2) if bets else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(100 * max_dd_frac, 2),
        "peak": round(peak, 2),
        "ruined": capital < min_stake,
        "ruined_at_turn": ruined_at,
        "top_hit_rate_pct": round(100 * top_hits / top_n, 2) if top_n else 0.0,
        "committed_turns": committed_n,
        "committed_hit_rate_pct": round(100 * committed_hits / committed_n, 2) if committed_n else 0.0,
        "engine_edge_bits": round(brain._last_ig, 5) if brain.n_obs else 0.0,
        "engine_hit_rate_pct": round(brain.stats_snapshot()["oos_hit_rate_pct"], 2),
        "results": "".join(results[-120:]),
    }
    if collect_curve:
        out["curve"] = _downsample(curve, 240)
    return out


def _downsample(curve: Sequence[float], buckets: int) -> List[float]:
    if len(curve) <= buckets:
        return [round(v, 2) for v in curve]
    step = len(curve) / buckets
    return [round(curve[int(i * step)], 2) for i in range(buckets)]


def compare(sources: Sequence[str], policies: Sequence[str], turns: int,
            settings: Settings, seeds: Sequence[int] = (1, 2, 3),
            start_capital: Optional[float] = None,
            opts: Optional[Dict[str, Any]] = None,
            history: Optional[Sequence[str]] = None,
            probs: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Run the full grid and aggregate across seeds (mean / median / p10 / p90)."""
    opts = opts or {}
    grid: List[Dict[str, Any]] = []
    for src in sources:
        for pol in policies:
            for sd in seeds:
                grid.append(run(src, pol, turns, settings, start_capital=start_capital,
                                seed=sd, opts=opts, history=history, probs=probs))
    summary: List[Dict[str, Any]] = []
    for src in sources:
        for pol in policies:
            rows = [g for g in grid if g["source"] == src and g["policy"] == pol]
            if not rows:
                continue
            fin = sorted(r["final_capital"] for r in rows)
            roi = sorted(r["roi_pct"] for r in rows)
            summary.append({
                "source": src, "policy": pol, "runs": len(rows), "turns": turns,
                "mean_final": round(stats.mean(fin), 2),
                "median_final": round(_median(fin), 2),
                "p10_final": round(_pct(fin, 0.10), 2),
                "p90_final": round(_pct(fin, 0.90), 2),
                "mean_roi_pct": round(stats.mean(roi), 2),
                "best_roi_pct": round(roi[-1], 2),
                "worst_roi_pct": round(roi[0], 2),
                "ruin_rate_pct": round(100 * sum(1 for r in rows if r["ruined"]) / len(rows), 1),
                "mean_dd_pct": round(stats.mean([r["max_drawdown_pct"] for r in rows]), 2),
                "mean_win_rate_pct": round(stats.mean([r["win_rate_pct"] for r in rows]), 2),
                "mean_bets": round(stats.mean([r["bets"] for r in rows]), 1),
                "mean_committed_hit_pct": round(
                    stats.mean([r["committed_hit_rate_pct"] for r in rows]), 2),
            })
    summary.sort(key=lambda r: (r["source"], -r["mean_roi_pct"]))
    return {"grid": grid, "summary": summary, "turns": turns,
            "seeds": list(seeds), "sources": list(sources), "policies": list(policies)}


def _median(xs: Sequence[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0.0
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def _pct(xs: Sequence[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def ledger_bets(turns: Sequence[Dict[str, Any]], symbols: Sequence[str]) -> List[Dict[str, float]]:
    """Extract your recorded stake vectors, for the ``mirror_you`` policy."""
    out = []
    for t in turns:
        st = t.get("played_bet") or {}
        out.append({s: float(st.get(s, 0) or 0) for s in symbols})
    return out or [{s: 0 for s in symbols}]
