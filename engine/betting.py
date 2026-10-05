"""betting.py — money math: bet shapes, Kelly staking, EV / variance / ruin.

At flat 3.0x odds across three mutually exclusive outcomes the implied
probabilities sum to exactly 1.00, so the book is *perfectly fair*: no house
edge and no arbitrage. Consequences worth internalising, all of which this
module reports rather than hides:

* EV of any bet = 3 * (sum of p_c * stake_c) - total_stake. Pure prediction
  skill, nothing else, moves it off zero.
* A single-colour bet breaks even at a 33.3% hit rate.
* A **two-colour split** (the user's 120 + 120 shape) wins often but small:
  +50% of stake two-thirds of the time, -100% one-third of the time, so it
  breaks even at a **66.7% cover rate**. It trades accuracy requirements for
  a much smoother bankroll curve. That trade is the whole point of the shape
  lab below.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ------------------------------------------------------------------- helpers
def clean_stakes(raw: Optional[Dict[str, Any]], symbols: Sequence[str]) -> Dict[str, float]:
    """Coerce user/API input into a stake dict over the symbol set."""
    out = {s: 0.0 for s in symbols}
    for s, v in (raw or {}).items():
        if s in out:
            try:
                out[s] = max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    return out


def round_to_step(x: float, step: float) -> float:
    if step <= 0:
        return round(x, 2)
    return round(step * round(x / step), 6)


def bet_shape(stakes: Dict[str, float]) -> str:
    covered = [s for s, v in stakes.items() if v > 0]
    total = sum(stakes.values())
    if total <= 0:
        return "pass"
    if len(covered) == 1:
        return "single"
    return f"split{len(covered)}"


def top_pick(stakes: Dict[str, float]) -> Optional[str]:
    """The colour the stake allocation says you actually believe in."""
    covered = {s: v for s, v in stakes.items() if v > 0}
    if not covered:
        return None
    best = max(covered.values())
    winners = [s for s, v in covered.items() if v == best]
    return winners[0] if len(winners) == 1 else None   # ambiguous on an exact tie


# --------------------------------------------------------------- bet analysis
def analyze_bet(stakes: Dict[str, float], payouts: Dict[str, float],
                symbols: Sequence[str],
                probs: Optional[Dict[str, float]] = None,
                capital: Optional[float] = None) -> Dict[str, Any]:
    """Full breakdown of one bet vector: what each outcome pays, EV, risk."""
    stakes = clean_stakes(stakes, symbols)
    total = sum(stakes.values())
    covered = [s for s in symbols if stakes[s] > 0]
    shape = bet_shape(stakes)

    outcomes: Dict[str, Dict[str, Any]] = {}
    for s in symbols:
        ret = payouts[s] * stakes[s]
        net = ret - total
        outcomes[s] = {
            "return": round(ret, 2),
            "net": round(net, 2),
            "net_pct": round(100.0 * net / total, 2) if total > 0 else 0.0,
            "prob": round(probs[s], 5) if probs else None,
            "covers": stakes[s] > 0,
            # Probability this colour alone would need, to break this bet even.
            "break_even_prob_pct": round(100.0 * total / ret, 2) if ret > 0 else None,
        }

    res: Dict[str, Any] = {
        "stakes": {s: round(stakes[s], 2) for s in symbols},
        "total": round(total, 2),
        "shape": shape,
        "covered": covered,
        "outcomes": outcomes,
        "top_pick": top_pick(stakes),
        "best_net": round(max(o["net"] for o in outcomes.values()), 2),
        "worst_net": round(min(o["net"] for o in outcomes.values()), 2),
        "exposure_pct_of_capital": round(100.0 * total / capital, 2) if capital else None,
        "guaranteed_profit": total > 0 and min(o["net"] for o in outcomes.values()) > 0,
    }

    # ------------------------------------------------------------------
    # Cover break-even: how often the colour(s) you backed must come in for
    # this bet to be worth making.
    #
    # EV = sum_c p_c * d_c * s_c - T.  Write q for the total probability of
    # landing on a covered colour. To express EV in terms of q alone we need
    # the split *within* the covered set; the fair assumption (the one that
    # makes the answer independent of the bookmaker's lean) is that covered
    # colours are hit in proportion to their implied probability 1/d. Then
    #
    #     q* = T * sum_c(1/d_c) / sum_c(s_c)
    #
    # Check it against the cases you already know:
    #   one colour at 3x          -> q* = 1/3   (33.3%, the single-colour bar)
    #   120 on red + 120 on blue  -> q* = 2/3   (66.7%, the split's real bar)
    #   covering all three        -> q* = 1.0   (a guaranteed loss at flat odds)
    # ------------------------------------------------------------------
    if total > 0:
        inv = sum(1.0 / payouts[s] for s in covered)
        stake_c = sum(stakes[s] for s in covered)
        if inv > 0 and stake_c > 0:
            q = total * inv / stake_c
            res["cover_break_even_pct"] = round(100.0 * q, 2)
            res["cover_payout_ratio"] = round(1.0 / q, 4) if q > 0 else None
            res["cover_break_even_prob_per_colour"] = {
                s: round(100.0 * q * (1.0 / payouts[s]) / inv, 2) for s in covered}

    if probs and total > 0:
        ev = sum(probs[s] * outcomes[s]["net"] for s in symbols)
        var = sum(probs[s] * (outcomes[s]["net"] - ev) ** 2 for s in symbols)
        res.update({
            "ev": round(ev, 3),
            "ev_pct": round(100.0 * ev / total, 3),
            "sigma": round(math.sqrt(max(var, 0.0)), 3),
            "win_rate_pct": round(100.0 * sum(probs[s] for s in symbols
                                              if outcomes[s]["net"] > 0), 2),
            "lose_rate_pct": round(100.0 * sum(probs[s] for s in symbols
                                               if outcomes[s]["net"] < 0), 2),
            "ev_per_coin": round(ev / total, 5),
        })
        if capital and capital > 0:
            losing = sum(probs[s] for s in symbols if outcomes[s]["net"] < 0)
            streaks = max(1, math.ceil(capital / total))
            res["consecutive_losses_to_bust"] = streaks
            res["bust_streak_probability"] = (
                round(losing ** streaks, 8) if 0 < losing < 1 else (0.0 if losing <= 0 else 1.0))
    return res


# ------------------------------------------------------------------- staking
def kelly_stakes(probs: Dict[str, float], payouts: Dict[str, float],
                 symbols: Sequence[str], capital: float, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fractional-Kelly allocation across colours, capped and rounded.

    For a single mutually-exclusive bet at decimal odds d the Kelly fraction
    is f* = (d*p - 1) / (d - 1). Staking several colours at once over-bets if
    you simply sum those fractions, so the total is clamped to
    ``max_exposure_fraction`` of bankroll and then multiplied by
    ``kelly_fraction`` (fractional Kelly), which also buys robustness against
    over-confident probabilities.
    """
    step = float(cfg.get("stake_step", 10))
    min_stake = float(cfg.get("min_stake", 10))
    max_turn = float(cfg.get("max_stake_per_turn", 0) or 0)
    max_exp = float(cfg.get("max_exposure_fraction", 0.2))
    frac = float(cfg.get("kelly_fraction", 0.25))
    min_edge = float(cfg.get("min_edge_to_bet", 0.0))
    multi = bool(cfg.get("allow_multi_colour", True))
    # A "provisional" prediction has seen real signal but no proven edge yet,
    # so the stake multiple is shrunk rather than the bet being refused.
    tier_scale = float(cfg.get("kelly_scale", 1.0) or 0.0)
    if tier_scale != 1.0:
        frac *= tier_scale

    edges = {s: payouts[s] * probs.get(s, 0.0) - 1.0 for s in symbols}
    raw = {s: edges[s] / (payouts[s] - 1.0) for s in symbols if edges[s] > min_edge}
    info: Dict[str, Any] = {
        "edges": {s: round(edges[s], 5) for s in symbols},
        "full_kelly": {s: round(max(edges[s] / (payouts[s] - 1.0), 0.0), 5)
                       for s in symbols},
        "kelly_fraction": frac,
        "max_exposure_fraction": max_exp,
    }
    if not raw or capital <= 0:
        info.update({"stakes": {s: 0 for s in symbols}, "total": 0,
                     "reason": "PASS - no colour clears the edge threshold",
                     "capped": False, "exposure_pct": 0.0})
        return info
    if not multi:
        best = max(raw, key=lambda s: raw[s])
        raw = {best: raw[best]}

    tot_f = sum(raw.values())
    scale = min(1.0, max_exp / tot_f) if tot_f > 0 else 0.0
    capped = scale < 1.0
    stakes = {s: capital * raw[s] * frac * scale for s in raw}

    stakes = {s: round_to_step(v, step) for s, v in stakes.items()}
    stakes = {s: v for s, v in stakes.items() if v >= min_stake}
    total = sum(stakes.values())

    # Hard limits: per-turn cap, then available capital.
    for limit in (max_turn, capital):
        if limit and total > limit:
            k = limit / total
            stakes = {s: round_to_step(v * k, step) for s, v in stakes.items()}
            stakes = {s: v for s, v in stakes.items() if v >= min_stake}
            total = sum(stakes.values())
            capped = True

    full = {s: stakes.get(s, 0) for s in symbols}
    ev = sum(probs.get(s, 0.0) * payouts[s] * full[s] for s in symbols) - sum(full.values())
    info.update({
        "stakes": {s: int(round(v)) if float(v).is_integer() else v for s, v in full.items()},
        "total": round(sum(full.values()), 2),
        "capped": capped,
        "exposure_pct": round(100.0 * sum(full.values()) / capital, 2) if capital else 0.0,
        "ev": round(ev, 3),
        "ev_pct": round(100.0 * ev / max(sum(full.values()), 1e-9), 2) if sum(full.values()) else 0.0,
        "reason": ("bet" if full else "PASS - stakes rounded below the minimum"),
        "shape": bet_shape(full),
    })
    return info


# ------------------------------------------------------------------ shape lab
def shape_lab(probs: Dict[str, float], payouts: Dict[str, float],
              symbols: Sequence[str], capital: float, cfg: Dict[str, Any],
              stake_total: Optional[float] = None) -> List[Dict[str, Any]]:
    """Compare every sensible bet shape head-to-head at equal exposure.

    Holding total stake constant is what makes the comparison honest: it
    isolates *shape* (where the money sits) from *size* (how much is at risk).
    """
    bot = kelly_stakes(probs, payouts, symbols, capital, cfg)
    base_total = stake_total if stake_total else bot.get("total") or 0
    if not base_total or base_total <= 0:
        base_total = max(float(cfg.get("min_stake", 10)),
                         round_to_step(capital * float(cfg.get("max_exposure_fraction", 0.2)),
                                       float(cfg.get("stake_step", 10))))
    step = float(cfg.get("stake_step", 10))
    cands: List[Tuple[str, Dict[str, float]]] = [("PASS", {s: 0 for s in symbols})]

    top = max(probs, key=lambda s: probs[s])
    cands.append((f"ALL ON TOP ({top.upper()})", {**{s: 0 for s in symbols}, top: base_total}))
    for s in symbols:
        cands.append((f"ALL ON {s.upper()}", {**{k: 0 for k in symbols}, s: base_total}))

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            half = round_to_step(base_total / 2.0, step)
            st = {s: 0 for s in symbols}
            st[a] = half
            st[b] = base_total - half
            cands.append((f"SPLIT {a.upper()}+{b.upper()} (equal)", st))
            # probability-weighted split of the same pair
            wsum = probs[a] + probs[b]
            if wsum > 0:
                sa = round_to_step(base_total * probs[a] / wsum, step)
                st2 = {s: 0 for s in symbols}
                st2[a] = sa
                st2[b] = max(0.0, base_total - sa)
                cands.append((f"SPLIT {a.upper()}+{b.upper()} (by odds)", st2))

    eq = round_to_step(base_total / len(symbols), step)
    cands.append(("COVER ALL (equal)", {s: eq for s in symbols}))
    if bot.get("total"):
        cands.append(("BOT (fractional Kelly)", {s: float(v) for s, v in bot["stakes"].items()}))

    rows = []
    for label, st in cands:
        a = analyze_bet(st, payouts, symbols, probs=probs, capital=capital)
        rows.append({"label": label, **{k: a.get(k) for k in (
            "stakes", "total", "shape", "ev", "ev_pct", "sigma", "win_rate_pct",
            "worst_net", "best_net", "cover_break_even_pct",
            "bust_streak_probability", "consecutive_losses_to_bust")}})
    rows.sort(key=lambda r: (-(r.get("ev") or 0.0), r.get("sigma") or 0.0))
    return rows


def explain_split(stakes: Dict[str, float], payouts: Dict[str, float],
                  symbols: Sequence[str], names: Dict[str, str],
                  probs: Optional[Dict[str, float]] = None) -> str:
    """Plain-English read-out of a multi-colour bet."""
    a = analyze_bet(stakes, payouts, symbols, probs=probs)
    if a["shape"] == "pass":
        return "No stake: this turn is a pass."
    parts = [f"{int(v)} on {names.get(s, s)}" for s, v in a["stakes"].items() if v > 0]
    head = " + ".join(parts) + f" = {int(a['total'])} at risk."
    lines = [head]
    for s in symbols:
        o = a["outcomes"][s]
        tag = "WIN " if o["net"] > 0 else ("PUSH" if o["net"] == 0 else "LOSE")
        p = f"  (p={100*o['prob']:.1f}%)" if o["prob"] is not None else ""
        lines.append(f"  {names.get(s, s):>5} comes up -> {tag} {o['net']:+.0f} "
                     f"({o['net_pct']:+.1f}%){p}")
    if a.get("cover_break_even_pct") is not None:
        lines.append(f"  Break-even: the covered colours must hit "
                     f"{a['cover_break_even_pct']:.1f}% of the time.")
    if probs:
        lines.append(f"  EV at the bot's current probabilities: {a['ev']:+.1f} coins/turn "
                     f"({a['ev_pct']:+.1f}%), win rate {a['win_rate_pct']:.1f}%, "
                     f"sigma {a['sigma']:.1f}.")
    return "\n".join(lines)
