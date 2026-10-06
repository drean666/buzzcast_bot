"""analyze.py — read your own results and tell you the truth about them.

    python3 analyze.py                    # your live session (data.json)
    python3 analyze.py results.csv        # an exported results file
    python3 analyze.py turns.csv          # an exported turns file
    python3 analyze.py archive/old_history.json

Answers three questions and nothing else:

    1. Do any colours come up more than they should?
    2. Does the trend bet actually work here? (two-colour runs continuing
       more than the 66.7% it needs to break even)
    3. How much more data until that answer is trustworthy?

Everything printed is measured on your data. Nothing is extrapolated, and no
number is reported as meaningful before it is.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from engine import simulate, stats                      # noqa: E402
from engine.settings import Settings                    # noqa: E402

W = 76
BREAK_EVEN = 100.0 * 2.0 / 3.0        # what a two-colour bet needs


def rule(ch: str = "-") -> str:
    return ch * W


def pct(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}%"


def turns_needed(p: float, p0: float = 2.0 / 3.0, power: float = 0.8,
                 alpha: float = 0.05) -> int:
    """Trend turns required to detect a true rate ``p`` with 80% power.

    Standard one-sided two-proportion sample size. Used to tell you honestly
    how much further you have to go instead of leaving "not enough data" as a
    vague shrug.
    """
    if p <= p0:
        return 10 ** 9
    z_a = 1.6449 if alpha == 0.05 else 1.96
    z_b = {0.8: 0.8416, 0.9: 1.2816}.get(power, 0.8416)
    num = (z_a * math.sqrt(p0 * (1 - p0)) + z_b * math.sqrt(p * (1 - p))) ** 2
    return int(math.ceil(num / ((p - p0) ** 2)))


# ------------------------------------------------------------------- loading
def load_any(path: str) -> Dict[str, Any]:
    """Accept a live data.json, a results CSV, or an exported turns CSV."""
    if not os.path.exists(path):
        raise SystemExit(f"cannot find {path}")
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # the archived v1 file has a different shape; pull results out of both
        sessions = data.get("sessions") or {}
        if not sessions and (data.get("entries") or data.get("results")):
            sessions = {"archive": data}
        if not sessions:
            raise SystemExit("no sessions found in that file")
        # Pick a session: the active one if it has anything, otherwise the
        # fullest one. The archived v1 file has an empty "Default" session
        # sitting in front of the real data, so ordering alone is not enough.
        def size(v: Dict[str, Any]) -> int:
            return len(v.get("entries") or []) + len(v.get("turns") or [])
        name = data.get("active")
        if name not in sessions or size(sessions[name]) == 0:
            name = max(sessions, key=lambda k: size(sessions[k]))
        sess = sessions[name]
        results = list(sess.get("warm_start") or [])
        turns = list(sess.get("turns") or [])
        # A live session keeps its results inside the turns; the warm_start
        # array only holds an optional seed. Missing this made the report claim
        # "no results yet" on a session with hundreds of played turns.
        for t in turns:
            if isinstance(t, dict) and t.get("result"):
                results.append(str(t["result"]).lower())
            elif isinstance(t, str):
                results.append(t.lower())
        # v1 layout: entries are {"symbol": "g", ...} or bare strings
        for entry in sess.get("entries") or []:
            if isinstance(entry, dict):
                sym = entry.get("symbol") or entry.get("result") or entry.get("value")
            else:
                sym = entry
            if sym:
                results.append(str(sym).lower())
        if isinstance(sess.get("results"), str):
            results.extend(list(sess["results"].lower()))
        return {"kind": "session", "name": name, "results": results, "turns": turns,
                "raw": data}

    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit("that file has no rows")
    cols = set(rows[0].keys())
    if "symbol" in cols:
        results = [r["symbol"].strip().lower() for r in rows if r.get("symbol")]
        return {"kind": "results-csv", "name": os.path.basename(path),
                "results": results, "turns": [], "raw": rows}
    if "stake_total" in cols:
        results = [r["result"].strip().lower() for r in rows if r.get("result")]
        return {"kind": "turns-csv", "name": os.path.basename(path),
                "results": results, "turns": rows, "raw": rows}
    raise SystemExit(f"unrecognised CSV columns: {sorted(cols)}")


def _stake_vector(t: Dict[str, Any], symbols: Sequence[str]) -> Dict[str, float]:
    """Get the stake per colour from either a ledger turn or an exported row.

    A ledger turn nests it under ``played_bet``; the CSV flattens it into
    ``stake_r``/``stake_b``/``stake_g`` columns. Reading only the first form
    silently reported "0 bets on two colours" for every exported file.
    """
    raw = t.get("played_bet")
    if isinstance(raw, dict) and raw:
        return {k: float(raw.get(k) or 0) for k in symbols}
    out = {}
    for k in symbols:
        try:
            out[k] = float(t.get(f"stake_{k}") or 0)
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def play_stats(turns: Sequence[Dict[str, Any]], symbols: Sequence[str],
               starting: float = 0.0) -> Optional[Dict[str, Any]]:
    """Your betting, restated from the ledger."""
    bets = [t for t in turns if float(t.get("stake_total") or 0) > 0]
    if not bets:
        return None
    staked = sum(float(t["stake_total"]) for t in bets)
    pnl = sum(float(t.get("pnl") or 0) for t in turns)
    wins = sum(1 for t in bets if float(t.get("pnl") or 0) > 0)
    curve = [starting] if starting else []
    cap = starting
    for t in turns:
        cap += float(t.get("pnl") or 0)
        curve.append(cap)
    dd_abs, dd_frac = stats.max_drawdown(curve) if len(curve) > 1 else (0.0, 0.0)
    nets = [float(t.get("pnl") or 0) for t in bets]
    return {"bets": len(bets), "turns": len(turns), "staked": staked, "pnl": pnl,
            "roi_pct": 100.0 * pnl / staked if staked else 0.0,
            "win_rate_pct": 100.0 * wins / len(bets),
            "best": max(nets) if nets else 0.0, "worst": min(nets) if nets else 0.0,
            "max_drawdown": dd_abs, "max_drawdown_pct": 100.0 * dd_frac,
            "shared": sum(1 for t in bets
                          if sum(1 for v in _stake_vector(t, symbols).values() if v > 0) > 1)}


# -------------------------------------------------------------------- report
def report(path: str, settings: Optional[Settings] = None) -> str:
    s = settings or Settings.load()
    data = load_any(path)
    seq = [x for x in data["results"] if x in s.symbols]
    turns = data["turns"]
    out: List[str] = []
    add = out.append
    _sec = [0]

    def section(title: str) -> None:
        _sec[0] += 1
        add("")
        add(f"{_sec[0]}. {title}")

    add(rule("="))
    add(f"buzzcast analysis — {os.path.basename(path)}")
    add(f"source: {data['kind']}   session: {data['name']}")
    add(f"{len(seq)} recorded results" +
        (f" · {len(turns)} played turns" if turns else ""))
    add(rule("="))

    if not seq:
        add("")
        add("No results in there yet. Play some turns and save, then run this again.")
        return "\n".join(out)

    # --- 1. is any colour more common than it should be?
    counts = {sym: seq.count(sym) for sym in s.symbols}
    n = len(seq)
    chi2 = stats.chi_square_uniform(counts, n, len(s.symbols))
    p_bias = stats.chi_square_sf(chi2, len(s.symbols) - 1)
    section("ARE ANY COLOURS COMING UP TOO OFTEN?")
    add("")
    for sym in sorted(s.symbols, key=lambda x: -counts[x]):
        share = 100.0 * counts[sym] / n
        dev = share - 100.0 / len(s.symbols)
        add(f"   {sym.upper():<6} {share:5.1f}%  ({counts[sym]:>4})   "
            f"{'above' if dev > 0 else 'below'} an even share by {abs(dev):.1f} points")
    add("")
    if p_bias <= 0.05:
        top = max(counts, key=lambda x: counts[x])
        add(f"   Verdict: {top.upper()} IS unusually common (p = {p_bias:.4f}).")
        need = 1.0 / s.payout(top)
        add(f"   {top.upper()} appears {100*counts[top]/n:.1f}% of the time and needs "
            f"{100*need:.1f}% to be worth backing on its own.")
    else:
        add(f"   Verdict: no colour is out of line (p = {p_bias:.2f}).")
        add("   The split between colours looks like chance.")
    add("")

    # --- does the trend bet work?
    MAX_RUN = 10
    rep = simulate.trend_report(seq, s.symbols, min_run=3, max_run=MAX_RUN)
    o = rep["overall"]
    section("DOES THE TREND BET WORK HERE?")
    add("")
    if o["n"] < 10:
        add(f"   Only {o['n']} trend turns so far — far too few to judge.")
    else:
        add(f"   {o['n']} trend turns. Two-colour runs continued "
            f"{pct(o['continued_pct'])} of the time.")
        add(f"   You need {pct(BREAK_EVEN)} just to break even.")
        gap = o["continued_pct"] - BREAK_EVEN
        add(f"   That is {gap:+.1f} points, p = {o['p_value']:.3f}"
            + (f", memory test p = {o['memory_p_value']:.3f}" if o.get("memory_p_value") is not None else ""))
        add("")
        if o["p_value"] <= 0.05 and gap > 0:
            add(f"   VERDICT: runs continue more than chance here. The trend bet is")
            add(f"   profitable on this data — but check the table below for whether a")
            add(f"   LONGER run is any better, because that is what you are betting on.")
        elif o["p_value"] <= 0.05:
            add("   VERDICT: runs are BREAKING more often than chance. Staking both")
            add("   colours is worse than a coin toss on this data.")
        else:
            add("   VERDICT: no evidence of memory. Runs are real and visible, but")
            add("   they are not predicting anything — the standard 66.7% applies.")
        add("")
        if rep["rows"]:
            add("   does a longer run predict better?")
            add(f"   {'run':>4}  {'turns':>6}  {'continued':>10}  {'vs 66.7%':>9}  {'p':>7}")
            for r in rep["rows"]:
                mark = "  <--" if r["significant"] else ""
                label = f"{r['run']}+" if r["run"] >= MAX_RUN else f"{r['run']}"
                add(f"   {label:>4}  {r['n']:>6}  {r['continued_pct']:>9.1f}%  "
                    f"{r['edge_pct']:>+8.1f}%  {r['p_value']:>7.4f}{mark}")
            add("")
            add("   A row marked <-- looks like a pattern. With this many rows tested,")
            add("   one will look good by luck alone; it needs p below 0.006 to count.")

    # --- 3. your actual betting, if we have it
    ps = play_stats(turns, s.symbols) if turns else None
    if ps:
        section("WHAT YOUR BETTING ACTUALLY DID")
        add("")
        add(f"   {ps['bets']} bets from {ps['turns']} turns "
            f"({ps['shared']} of them on two colours at once)")
        add(f"   staked {ps['staked']:,.0f} · returned "
            f"{ps['staked'] + ps['pnl']:,.0f} · profit {ps['pnl']:+,.0f}")
        add(f"   on turnover: {ps['roi_pct']:+.2f}%   "
            f"· {ps['win_rate_pct']:.1f}% of bets won")
        add(f"   best turn {ps['best']:+,.0f} · worst turn {ps['worst']:+,.0f} · "
            f"deepest dip {ps['max_drawdown_pct']:.1f}%")
        if ps["staked"]:
            exp = ps["roi_pct"]
            add("")
            if abs(exp) < 3 and ps["bets"] < 200:
                add("   That is within noise of break-even so far. Neither good nor bad.")
            elif exp < -3:
                add("   You are losing on turnover. Check the size, not just the picks:")
                add("   a big stake on a fair bet still goes broke, just faster.")
            elif exp > 3:
                add("   You are ahead on turnover. Keep the size sane and it continues.")

    # --- 4. how much further?
    section("HOW MUCH MORE DATA DO YOU NEED?")
    add("")
    have = o["n"]
    rate = o["n"] / max(n, 1)
    add(f"   you have {have} trend turns from {n} recorded results "
        f"({rate:.2f} per result)")
    add("")
    for target, label in ((0.71, "a subtle edge (71%)"), (0.76, "a clear edge (76%)")):
        need = turns_needed(target)
        if have >= need:
            add(f"   {label:<22} needs ~{need:>4} trend turns — you have enough")
        else:
            short_t = need - have
            play = int(short_t / rate) if rate > 0 else 0
            add(f"   {label:<22} needs ~{need:>4} trend turns — {short_t:>4} more,"
                f" roughly {play} more results")
    add("")
    add("   Until then, keep the total stake per turn in single digits as a")
    add("   percentage of your bankroll. Everything above is measurement; that")
    add("   single rule is what keeps you in the game long enough to be measured.")
    add("")
    add(rule("="))
    return "\n".join(out)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data.json")
    if not os.path.exists(path):
        raise SystemExit(
            f"cannot find {path}\n"
            f"Play some turns first, or point at a file:\n"
            f"  python3 analyze.py results.csv")
    print(report(path))


if __name__ == "__main__":
    main()
