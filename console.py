"""console.py — the same engine, no browser. Useful on a machine without one.

    python3 console.py play          interactive turn loop
    python3 console.py state         one-shot report
    python3 console.py sim           headless simulation
    python3 console.py grid          full source x policy grid
    python3 console.py seed          load the old 70 results as a warm start
    python3 console.py undo [n]      roll back the last n turns
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from engine import simulate                          # noqa: E402
from engine.game import GameEngine                   # noqa: E402
from engine.settings import Settings                 # noqa: E402

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def bar(p: float, width: int = 24, ch: str = "\u2588") -> str:
    n = int(round(max(0.0, min(1.0, p)) * width))
    return ch * n + "\u00b7" * (width - n)


def show_state(e: GameEngine) -> None:
    st = e.state()
    cap, pay = st["capital"], st["payouts"]
    print(f"\n{BOLD}capital {cap['value']:.0f}{RESET}  "
          f"(start {cap['start']:.0f}, net {cap['net']:+.0f}, "
          f"deposits {cap['deposits']:+.0f}, {cap['turns']} turns)")
    pr = st["prediction"]
    print(f"{BOLD}next prediction{RESET}  tier={pr['tier'].upper()}  "
          f"confidence {pr['confidence']:.1f}%  n={pr['n_obs']}")
    for s in st["symbols"]:
        print(f"   {e.settings.name_of[s]:<5} {bar(pr['probs'][s])} "
              f"{100*pr['probs'][s]:5.1f}%")
    print(f"   paper trade {pr['roi_pct']:+.1f}%/unit (p={pr['roi_p_value']:.4f})  "
          f"edge {pr['info_gain_bits']:+.4f} bits  "
          f"significance {pr.get('significance') or 'ns'}")
    for r in pr["reasons"]:
        print(f"   {DIM}+ {r}{RESET}")
    for b in pr["blockers"]:
        print(f"   {DIM}- {b}{RESET}")
    b = pr.get("bet") or {}
    if b.get("total"):
        parts = " + ".join(f"{int(v)} {s.upper()}" for s, v in b["stakes"].items() if v)
        print(f"   {BOLD}bot says:{RESET} stake {int(b['total'])}  ({parts})  "
              f"EV {b['ev']:+.1f} ({b['ev_pct']:+.1f}%)")
    else:
        print(f"   {BOLD}bot says:{RESET} pass")
    t = st["meta"]["trust"]
    print(f"   {DIM}meta-learner: {t['verdict']} — you {t['me_hit_rate_pct']:.0f}%, "
          f"bot {t['bot_hit_rate_pct']:.0f}%  (p_bot_better={t['p_bot_better']:.3f}){RESET}")


def play(e: GameEngine) -> None:
    print("Enter your bet as e.g. '120 120' (first two colours) or 'r120 b120', "
          "'top 100' for the bot's colour, or blank to pass.")
    while True:
        show_state(e)
        if e.session.get("pending"):
            res = input("real result [r/b/g, q=quit] > ").strip().lower()
            if res == "q":
                return
            e.resolve(res)
            continue
        raw = input("your bet > ").strip().lower()
        if raw == "q":
            return
        if not raw:
            e.pass_turn()
            continue
        st = {s: 0.0 for s in e.symbols}
        try:
            for tok in raw.replace(",", " ").split():
                if tok.isdigit():
                    for s in e.symbols:
                        if st[s] == 0:
                            st[s] = float(tok)
                            break
                else:
                    sym = tok[0]
                    num = float("".join(c for c in tok[1:] if c.isdigit() or c == "."))
                    st[sym] = num
        except (KeyError, ValueError):
            print("could not read that; try '120 120' or 'r120 b120'")
            continue
        follow = input("follow [m]ine / [b]ot / bl[e]nd (enter=mine) > ").strip().lower()
        follow = {"b": "bot", "e": "blend"}.get(follow[:1], "mine")
        e.place_bet(st, follow=follow)


def main() -> None:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "state").lower()
    s = Settings.load()
    e = GameEngine(s)
    if cmd == "play":
        play(e)
    elif cmd == "state":
        show_state(e)
    elif cmd == "undo":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        print(e.undo(n))
    elif cmd == "seed":
        import archive_old_history
        seq = archive_old_history.load()
        e.session["warm_start"] = seq
        e.rebuild()
        e.save()
        print(f"seeded {len(seq)} archived results into {e.name}")
    elif cmd == "sim":
        src = sys.argv[2] if len(sys.argv) > 2 else "fair"
        pol = sys.argv[3] if len(sys.argv) > 3 else "bot"
        turns = int(sys.argv[4]) if len(sys.argv) > 4 else 500
        r = simulate.run(src, pol, turns, s, start_capital=e.capital,
                         history=e.results(), opts={"stake": 120})
        width = 46
        for k in ("final_capital", "roi_pct", "bets", "win_rate_pct",
                  "max_drawdown_pct", "ruined", "committed_hit_rate_pct",
                  "top_hit_rate_pct", "engine_edge_bits"):
            print(f"{k:<24} {r[k]}")
        curve = r.get("curve", [])
        if curve:
            # log scale: a compounding bankroll spends most of its time near
            # the bottom of a linear chart, which makes the shape invisible
            import math
            lo = max(min(curve), 1e-9)
            hi = max(max(curve), lo * 1.001)
            llo, lhi = math.log(lo), math.log(hi)
            span = (lhi - llo) or 1.0
            step = max(1, len(curve) // 24)
            for i in range(0, len(curve), step):
                v = curve[i]
                row = int((math.log(max(v, 1e-9)) - llo) / span * (width - 1))
                print(f"{i:>5} {v:>10,.0f} |{' ' * row}*")
    elif cmd == "grid":
        turns = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        out = simulate.compare(["fair", "biased", "markov", "markov_strong"],
                               ["bot", "bot_loose", "split_two", "always_top",
                                "fixed_colour", "martingale"],
                               turns, s, seeds=(1, 2, 3), start_capital=e.capital,
                               history=e.results(), opts={"stake": 120})
        print(f"{'source':<14}{'policy':<14}{'mean final':>12}{'mean ROI%':>12}"
              f"{'ruin%':>8}{'maxDD%':>8}")
        for row in out["summary"]:
            print(f"{row['source']:<14}{row['policy']:<14}"
                  f"{row['mean_final']:>12,.0f}{row['mean_roi_pct']:>+12.1f}"
                  f"{row['ruin_rate_pct']:>8.1f}{row['mean_dd_pct']:>8.1f}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
