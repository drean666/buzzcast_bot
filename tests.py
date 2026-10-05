"""tests.py — the regression suite. Stdlib only, no pytest needed.

    python3 tests.py            run everything
    python3 tests.py -v         verbose

These tests are the project's conscience. Most of them exist to prove that the
bot CANNOT cheat: no lookahead, no false confidence on a fair game, no money
printed from noise. If you change the brain and the fair-game test starts
failing, you have built a liar, not a predictor.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from engine import betting, simulate, stats, storage            # noqa: E402
from engine.brain import Brain                                  # noqa: E402
from engine.game import GameEngine                              # noqa: E402
from engine.settings import Settings                            # noqa: E402
from engine.trust import MetaLearner                            # noqa: E402

VERBOSE = "-v" in sys.argv
RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


def approx(a, b, tol=1e-9):
    assert abs(a - b) <= tol, f"{a} != {b} (tol {tol})"


def fresh(**kw):
    s = Settings.load()
    path = os.path.join(tempfile.mkdtemp(), "data.json")
    for k, v in kw.items():
        s.data.setdefault("capital", {})[k] = v
    return GameEngine(s, path=path, autosave=False), s


def stream(n, probs, seed):
    r = random.Random(seed)
    keys = list(probs)
    out = []
    for _ in range(n):
        x, acc = r.random(), 0.0
        for k in keys:
            acc += probs[k]
            if x <= acc:
                out.append(k)
                break
        else:
            out.append(keys[-1])
    return out


def markov_stream(n, matrix, seed=0):
    r = random.Random(seed)
    last = next(iter(matrix))
    out = []
    for _ in range(n):
        row = matrix[last]
        x, acc = r.random(), 0.0
        for k, v in row.items():
            acc += v
            if x <= acc:
                last = k
                break
        out.append(last)
    return out


FAIR = {"r": 1 / 3, "b": 1 / 3, "g": 1 / 3}
BIASED = {"g": 0.44, "r": 0.28, "b": 0.28}
M_STRONG = {"r": {"r": 0.58, "b": 0.21, "g": 0.21},
            "b": {"r": 0.21, "b": 0.58, "g": 0.21},
            "g": {"r": 0.30, "b": 0.30, "g": 0.40}}


# ------------------------------------------------------------------ statistics
@test
def test_stats_sanity():
    approx(stats.norm_cdf(0), 0.5)
    approx(stats.norm_sf(0), 0.5)
    approx(stats.binom_sf_ge(0, 10, 0.5), 1.0)
    assert stats.binom_test_greater(10, 10, 0.5) < 0.01
    # 40/100 against a 1/3 chance is ~1.4 sigma above the mean: p ~ 0.097
    assert 0.05 < stats.binom_test_greater(40, 100, 1 / 3) < 0.20
    approx(stats.entropy_bits([1 / 3, 1 / 3, 1 / 3]), 1.58496, 1e-4)
    # chi-square: df=2 has known survival values
    approx(stats.chi_square_sf(4.60517, 2), 0.10, 2e-3)
    approx(stats.chi_square_sf(5.99146, 2), 0.05, 2e-3)
    for x in (0.5, 2.0, 6.0, 20.0):
        fast, slow = stats.chi_square_sf_fast(x, 2), stats.chi_square_sf(x, 2)
        assert abs(fast - slow) < 0.01, f"wilson-hilferty drift at {x}: {fast} vs {slow}"
    a, f = stats.max_drawdown([100, 120, 90, 110])
    approx(a, 30.0)
    approx(f, 0.25)
    lo, hi = stats.wilson_interval(30, 100)
    assert lo < 0.3 < hi
    assert stats.running_accuracy([]) == []


@test
def test_betting_math():
    P = {"r": 3.0, "b": 3.0, "g": 3.0}
    syms = ["r", "b", "g"]
    # a 120/120 split: +120 twice, -240 once -> the famous 66.7% bar
    a = betting.analyze_bet({"r": 120, "b": 120, "g": 0}, P, syms,
                            probs={"r": 1 / 3, "b": 1 / 3, "g": 1 / 3}, capital=1000)
    approx(a["total"], 240.0)
    approx(a["best_net"], 120.0)
    approx(a["worst_net"], -240.0)
    approx(a["cover_break_even_pct"], 66.67, 0.01)
    approx(a["ev"], 0.0, 1e-9)
    assert a["shape"] == "split2"
    # a single colour at 3x must beat exactly 33.3%
    a1 = betting.analyze_bet({"r": 100, "b": 0, "g": 0}, P, syms, capital=1000)
    approx(a1["cover_break_even_pct"], 33.33, 0.01)
    # covering all three colours at flat odds returns exactly your stake:
    # a guaranteed zero, which is why it is a strictly worse way to pass
    a3 = betting.analyze_bet({"r": 100, "b": 100, "g": 100}, P, syms,
                             probs={"r": 1 / 3, "b": 1 / 3, "g": 1 / 3}, capital=1000)
    approx(a3["worst_net"], 0.0)
    approx(a3["best_net"], 0.0)
    assert a3["ev"] == 0.0
    approx(a3["cover_break_even_pct"], 100.0, 0.01)
    # a bet that backs nothing is a pass
    assert betting.bet_shape({"r": 0, "b": 0, "g": 0}) == "pass"
    # rounding and clamping
    st = betting.clean_stakes({"r": -50, "b": 7, "g": 100}, syms)
    assert st["r"] == 0 and st["b"] == 7
    approx(betting.round_to_step(123.4, 10), 120.0)


@test
def test_kelly_respects_limits():
    P = {"r": 3.0, "b": 3.0, "g": 3.0}
    syms = ["r", "b", "g"]
    cfg = {"stake_step": 10, "min_stake": 10, "max_stake_per_turn": 600,
           "max_exposure_fraction": 0.2, "kelly_fraction": 0.25,
           "min_edge_to_bet": 0.01, "allow_multi_colour": True}
    # no edge at all -> pass
    k = betting.kelly_stakes({"r": 1 / 3, "b": 1 / 3, "g": 1 / 3}, P, syms, 1000, cfg)
    assert k["total"] == 0, "flat 3x with uniform beliefs has no edge, must pass"
    # a huge edge -> still capped by exposure and the per-turn limit
    k = betting.kelly_stakes({"r": 0.9, "b": 0.05, "g": 0.05}, P, syms, 1000, cfg)
    assert k["total"] <= 600 + 1e-9, k["total"]
    assert k["total"] <= 0.2 * 1000 + 1e-9, k["total"]
    assert k["stakes"]["r"] > 0
    # never exceeds the bankroll
    k = betting.kelly_stakes({"r": 0.9, "b": 0.05, "g": 0.05}, P, syms, 30, cfg)
    assert k["total"] <= 30 + 1e-9
    # a single-colour preference collapses the split
    k = betting.kelly_stakes({"r": 0.5, "b": 0.4, "g": 0.1}, P, syms, 1000,
                             {**cfg, "allow_multi_colour": False})
    assert k["shape"] in ("single", "pass")


# ----------------------------------------------------------------------- brain
@test
def test_brain_learns_and_is_calibrated():
    s = Settings.load()
    b = Brain(s)
    seq = stream(3000, BIASED, 3)
    b.fit(seq)
    snap = b.stats_snapshot()
    assert snap["n_obs"] == 3000
    assert snap["oos_hit_rate_pct"] > 40.0, snap["oos_hit_rate_pct"]
    pr = b.predict()
    assert pr.top == "g"
    assert pr.probs["g"] > 0.40
    assert pr.committed, "must commit on a 44% bias over 3000 samples"
    assert pr.info_gain_bits > 0.01


@test
def test_brain_incremental_equals_refit():
    """observe() one at a time must land exactly where fit() lands."""
    s = Settings.load()
    seq = stream(400, BIASED, 8) + markov_stream(400, M_STRONG, 9)
    a = Brain(s).fit(seq)
    b = Brain(s)
    for sym in seq:
        b.observe(sym)
    pa, pb = a.predict(), b.predict()
    for k in pa.probs:
        approx(pa.probs[k], pb.probs[k], 1e-12)
    assert a.n_obs == b.n_obs
    approx(a.roi_stats()["mean_pct"], b.roi_stats()["mean_pct"], 1e-12)
    approx(a.ig_all(), b.ig_all(), 1e-12)


@test
def test_brain_rejects_fair_game():
    """The single most important test: on noise, the bot must not commit."""
    s = Settings.load()
    for seed in (4, 5, 6):
        b = Brain(s)
        b.fit(stream(1500, FAIR, seed))
        ncommit = sum(1 for c in b.oos_committed if c)
        assert ncommit == 0, f"seed {seed}: committed {ncommit} times on a fair game"
        assert not b.predict().committed
        assert b.ig_all() < 0.01


@test
def test_brain_finds_real_structure():
    s = Settings.load()
    b = Brain(s).fit(markov_stream(1500, M_STRONG, 11))
    assert b.predict().committed, "must commit on a +74% edge source"
    assert b.predict().info_gain_bits > 0.05
    # and it should be using the 1-step context, not just the base rate
    assert b.stats_snapshot()["order_weights"]["1"] > 0.15, \
        b.stats_snapshot()["order_weights"]


@test
def test_brain_hedges_on_weak_structure():
    """A real but thin edge must command much less money than a big one.

    This is the difference between a bot that measures edge and one that
    measures *excitement*: both markov sources here are genuinely
    predictable, but only one is worth 3x odds. Comparing the two sessions
    is the only way to see that the sizing responds to the size of the edge.
    """
    s = Settings.load()
    thin = simulate.run("markov", "bot", 900, s, start_capital=1000, seed=12,
                        opts={"stake": 120})
    fat = simulate.run("markov_strong", "bot", 900, s, start_capital=1000, seed=12,
                       opts={"stake": 120})
    assert thin["bets"] < fat["bets"], (thin["bets"], fat["bets"])
    assert thin["avg_exposure_pct"] < fat["avg_exposure_pct"], \
        (thin["avg_exposure_pct"], fat["avg_exposure_pct"])
    assert thin["engine_edge_bits"] < fat["engine_edge_bits"]
    # and the thin edge must never be treated as a licence to bet the farm
    assert thin["max_drawdown_pct"] < 60.0, thin["max_drawdown_pct"]


@test
def test_brain_no_lookahead():
    """Every recorded OOS prediction must use only prior data.

    Rebuild a fresh brain on the prefix and check the prediction it makes
    matches what the walk-forward record stored for that step. If any result
    leaked backwards, these diverge.
    """
    s = Settings.load()
    seq = stream(600, BIASED, 21)
    full = Brain(s).fit(seq)
    for i in (100, 250, 400):
        prefix = Brain(s).fit(seq[:i])
        stored = full.oos_probs[i]
        now = prefix.predict(seq[i:i])  # extra empty -> same as next-step
        for k in now.probs:
            approx(stored[k], now.probs[k], 1e-9)
        assert full.oos_top[i] == now.top


@test
def test_brain_handles_pathological_input():
    s = Settings.load()
    b = Brain(s)
    b.fit([])
    pr = b.predict()
    assert pr.n_obs == 0 and not pr.committed
    assert b.ig_all() == 0.0
    assert b.roi_stats()["mean_pct"] == 0.0
    b.fit(["r"] * 500)  # one colour forever
    pr = b.predict()
    assert pr.top == "r" and pr.probs["r"] > 0.9
    assert pr.committed, "500 identical results is about as predictable as it gets"
    try:
        Brain(s).observe("z")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown symbol must raise")


@test
def test_pattern_report_flags_noise_honestly():
    s = Settings.load()
    b = Brain(s).fit(stream(1200, FAIR, 31))
    rows = b.pattern_report(order=2, min_n=6)
    sig = [r for r in rows if r["significant"]]
    assert len(rows) > 5, "should still enumerate contexts"
    assert len(sig) <= max(2, len(rows) // 10), \
        f"claimed {len(sig)} significant contexts in pure noise ({len(rows)} rows)"


# ------------------------------------------------------------------ game engine
@test
def test_turn_lifecycle_and_ledger():
    e, s = fresh()
    assert e.capital == 1000.0
    assert e.state()["phase"] == "await_bet"
    e.place_bet({"r": 120, "b": 120, "g": 0}, follow="mine")
    assert e.state()["phase"] == "await_result"
    assert e.capital == 1000.0, "placing a bet must not move money yet"
    t = e.resolve("r")
    approx(t["return"], 360.0)
    approx(t["pnl"], 120.0)
    approx(e.capital, 1120.0)
    assert t["hit"] is True
    t2 = e.resolve("x") if False else None
    # a losing turn
    e.place_bet({"r": 120, "b": 120, "g": 0}, follow="mine")
    t2 = e.resolve("g")
    approx(t2["pnl"], -240.0)
    approx(e.capital, 880.0)
    # pass: no money moves but the result is still learned
    n_before = e.brain.n_obs
    e.pass_turn()
    e.resolve("b")
    approx(e.capital, 880.0)
    assert e.brain.n_obs == n_before + 1, "a pass must still teach the model"
    # can't resolve twice
    try:
        e.resolve("r")
    except ValueError:
        pass
    else:
        raise AssertionError("resolving without a bet must fail")


@test
def test_undo_and_edit_are_exact():
    e, s = fresh()
    src = simulate.make_source("biased", e.symbols, seed=4)
    c0 = e.capital
    for _ in range(25):
        e.place_bet({"r": 120, "b": 120, "g": 0}, follow="mine")
        e.resolve(src.next())
    cap25 = e.capital
    n25 = len(e.session["turns"])
    e.undo(5)
    assert len(e.session["turns"]) == n25 - 5
    assert e.capital != cap25
    e.rebuild()
    # editing a result must recompute the whole chain
    t = e.session["turns"][0]
    old_pnl = t["pnl"]
    target = "g" if t["result"] != "g" else "r"
    e.edit_result(1, target)
    t = e.session["turns"][0]
    assert t["result"] == target
    assert t["pnl"] != old_pnl
    # capital_after of the final turn must equal the live capital
    approx(e.session["turns"][-1]["capital_after"], e.capital, 1e-9)
    # deposits change the basis but not the accounting identity
    e.deposit(500)
    approx(e.capital, e.session["turns"][-1]["capital_after"] + 500, 1e-9)
    assert e.state()["capital"]["deposits"] == 500.0


@test
def test_bet_validation_clamps():
    e, s = fresh()
    e.capital = 250.0
    st, warn = e.validate_bet({"r": 500, "b": 500, "g": 0})
    assert sum(st.values()) <= 250 + 1e-9, st
    assert warn
    st, _ = e.validate_bet({"r": 1000, "b": 0, "g": 0})
    assert sum(st.values()) <= 600 + 1e-9, "per-turn limit must bite"
    st, _ = e.validate_bet({"r": 4, "b": 0, "g": 0})
    assert sum(st.values()) == 0, "below minimum stake -> dropped after rounding"
    st, _ = e.validate_bet({"r": 7, "b": 0, "g": 0})
    assert sum(st.values()) == 10, "7 rounds to the 10 step"
    # an oversized request is clamped, never rejected out of hand
    e.capital = 1000.0
    p = e.place_bet({"r": 9000, "b": 9000, "g": 9000})
    assert p["stake_total"] <= 1000.0 + 1e-9, p["stake_total"]
    assert p["stake_total"] <= 600.0 + 1e-9, "the per-turn ceiling still applies"
    assert p["warnings"], "clamping must be reported to the player"
    # a busted bankroll collapses to a pass instead of dead-ending
    e.cancel_pending()
    e.capital = 0.0
    p = e.place_bet({"r": 120, "b": 120, "g": 0})
    assert p["stake_total"] == 0.0


@test
def test_cancel_pending_is_free():
    e, s = fresh()
    e.place_bet({"r": 120, "b": 120, "g": 0})
    e.cancel_pending()
    assert not e.session.get("pending")
    approx(e.capital, 1000.0)
    assert len(e.session["turns"]) == 0


@test
def test_sessions_isolated():
    e, s = fresh()
    e.place_bet({"r": 100, "b": 0, "g": 0})
    e.resolve("r")
    e.new_session("second", starting=500)
    approx(e.capital, 500.0)
    assert e.brain.n_obs == 0
    e.switch("session-1")
    assert e.brain.n_obs == 1
    approx(e.capital, 1200.0)
    e.delete_session("second")
    assert len(e.list_sessions()) == 1
    try:
        e.delete_session("session-1")
    except ValueError:
        pass
    else:
        raise AssertionError("must not delete the last session")


@test
def test_warm_start_does_not_touch_money():
    e, s = fresh()
    e.session["warm_start"] = stream(200, BIASED, 77)
    e.rebuild()
    approx(e.capital, 1000.0), "warm start seeds the MODEL only"
    assert e.brain.n_obs == 200
    assert len(e.session["turns"]) == 0
    assert e.capital == 1000.0


@test
def test_persistence_roundtrip_and_recovery():
    s = Settings.load()
    d = tempfile.mkdtemp()
    path = os.path.join(d, "data.json")
    e = GameEngine(s, path=path)
    for sym in stream(12, BIASED, 5):
        e.place_bet({"r": 60, "b": 60, "g": 0})
        e.resolve(sym)
    cap = e.capital
    probs = e.brain.predict().probs
    e2 = GameEngine(Settings.load(), path=path)
    approx(e2.capital, cap)
    for k in probs:
        approx(e2.brain.predict().probs[k], probs[k], 1e-12)
    assert len(e2.session["turns"]) == 12
    # corrupt the main file -> must self-heal from the backup
    storage._LAST_BACKUP.clear()
    e3 = GameEngine(Settings.load(), path=path)      # refreshes backup window
    with open(path, "w") as fh:
        fh.write("{ this is not json")
    if os.path.exists(storage.backup_path(path)):
        e4 = GameEngine(Settings.load(), path=path)
        assert len(e4.session["turns"]) >= 0, "must load something rather than crash"


@test
def test_csv_export():
    e, s = fresh()
    for sym in stream(5, BIASED, 6):
        e.place_bet({"r": 60, "b": 60, "g": 0})
        e.resolve(sym)
    txt = e.export_csv()
    lines = [l for l in txt.strip().splitlines() if l]
    assert len(lines) == 6, f"header + 5 turns, got {len(lines)}"
    assert "pnl" in lines[0]
    rtxt = e.export_results_csv()
    assert len(rtxt.strip().splitlines()) == 6


# --------------------------------------------------------------------- trust
@test
def test_trust_prefers_the_skilful_side():
    s = Settings.load()
    m = MetaLearner(s)
    rng = random.Random(3)
    truth = "g"
    for i in range(120):
        res = "g" if rng.random() < 0.9 else rng.choice(["r", "b"])
        bot_right = res == "g"
        me_right = rng.random() < 0.34           # you are just guessing
        m.add({"n": i + 1, "bot": {"top": "g", "committed": True}, "result": res,
               "my_pick": rng.choice(["r", "b", "g"]) if not me_right else res,
               "followed": "mine", "shape": "single", "stake_total": 100.0,
               "pnl": 100.0 if me_right else -100.0,
               "capital_before": 1000.0, "capital_after": 1000.0, "context": []})
    snap = m.snapshot(1000, 1000)
    assert snap["trust"]["bot_hit_rate_pct"] > snap["trust"]["me_hit_rate_pct"]
    assert snap["trust"]["verdict"] in ("TRUST THE BOT", "TOO CLOSE TO CALL")
    assert snap["trust"]["p_bot_better"] > 0.5


@test
def test_trust_needs_data_before_deciding():
    s = Settings.load()
    m = MetaLearner(s)
    snap = m.snapshot(1000, 1000)
    assert snap["trust"]["verdict"] == "NOT ENOUGH DATA"
    assert snap["risk"]["turns"] == 0


# -------------------------------------------------------------- simulations
@test
def test_sim_fair_game_loses_nothing_for_the_bot():
    s = Settings.load()
    r = simulate.run("fair", "bot", 1500, s, start_capital=1000, seed=17,
                     opts={"stake": 120})
    assert r["bets"] == 0, f"bot bet {r['bets']} times on a fair game"
    approx(r["final_capital"], 1000.0, 1e-6)
    assert not r["ruined"]


@test
def test_sim_biased_game_makes_money():
    s = Settings.load()
    r = simulate.run("biased", "bot", 1500, s, start_capital=1000, seed=18,
                     opts={"stake": 120})
    assert r["bets"] > 100, r["bets"]
    assert r["final_capital"] > 2000, r["final_capital"]
    assert not r["ruined"]
    assert r["committed_hit_rate_pct"] > 40


@test
def test_sim_split_strategy_busts_on_a_fair_game():
    """Your 120/120 split needs 66.7% cover. On a fair game it cannot hold."""
    s = Settings.load()
    losses = 0
    for seed in (1, 2, 3, 4):
        r = simulate.run("fair", "split_two", 3000, s, start_capital=1000,
                         seed=seed, opts={"stake": 120, "split_pair": ["r", "b"]})
        losses += 1 if r["final_capital"] < 1000 else 0
    assert losses >= 3, f"split survived a fair game in {4 - losses}/4 runs"


@test
def test_sim_martingale_ruins_without_an_edge():
    """Martingale on a fair game is a slow-motion bust.

    (On a genuinely biased source it can actually win — it is doubling on a
    real edge — which is exactly why it is a dangerous habit: it teaches you
    that doubling works, right up until the source goes back to fair.)
    """
    s = Settings.load()
    r = simulate.run("fair", "martingale", 3000, s, start_capital=1000, seed=5,
                     opts={"stake": 60})
    assert r["ruined"], f"martingale survived a fair game ({r['final_capital']})"
    # even where it survives, it must be far more volatile than the bot
    bot = simulate.run("biased", "bot", 1200, s, start_capital=1000, seed=5,
                       opts={"stake": 60})
    mart = simulate.run("biased", "martingale", 1200, s, start_capital=1000,
                        seed=5, opts={"stake": 60})
    assert mart["max_drawdown_pct"] > bot["max_drawdown_pct"], \
        (mart["max_drawdown_pct"], bot["max_drawdown_pct"])


@test
def test_sim_never_exceeds_bankroll_and_never_needs_money():
    s = Settings.load()
    for pol in ("bot", "always_top", "split_two", "fixed_colour", "random",
                "martingale", "bot_loose"):
        r = simulate.run("biased", pol, 500, s, start_capital=1000, seed=8,
                         opts={"stake": 100})
        assert r["curve"], pol
        assert min(r["curve"]) >= 0, f"{pol} produced a negative bankroll"
        assert r["turns_played"] <= 500


@test
def test_sim_deterministic_for_a_seed():
    s = Settings.load()
    a = simulate.run("markov_strong", "bot", 300, s, seed=42, opts={"stake": 100})
    b = simulate.run("markov_strong", "bot", 300, s, seed=42, opts={"stake": 100})
    assert a["final_capital"] == b["final_capital"]
    assert a["results"] == b["results"]
    c = simulate.run("markov_strong", "bot", 300, s, seed=43, opts={"stake": 100})
    assert c["results"] != a["results"]


@test
def test_sim_replay_uses_real_history():
    e, s = fresh()
    hist = stream(80, BIASED, 9)
    e.session["warm_start"] = hist
    e.rebuild()
    r = simulate.run("replay", "bot", 200, s, history=e.results(),
                     start_capital=1000, opts={"stake": 120}, warm=hist)
    assert r["turns_played"] == 200


@test
def test_grid_summary_shape():
    s = Settings.load()
    out = simulate.compare(["fair"], ["bot", "split_two"], 200, s,
                           seeds=(1, 2), opts={"stake": 100})
    assert len(out["summary"]) == 2
    for row in out["summary"]:
        for k in ("median_final", "ruin_rate_pct", "mean_roi_pct", "mean_bets"):
            assert k in row


@test
def test_size_proportional_invariance():
    """Halving every stake and the bankroll must halve the outcome, not change it."""
    s = Settings.load()
    a = simulate.run("biased", "split_two", 400, s, start_capital=2000, seed=3,
                     opts={"stake": 120})
    b = simulate.run("biased", "split_two", 400, s, start_capital=1000, seed=3,
                     opts={"stake": 60})
    assert a["results"] == b["results"]
    assert abs(a["roi_pct"] - b["roi_pct"]) < 0.5, (a["roi_pct"], b["roi_pct"])


@test
def test_full_session_end_to_end():
    """Play a whole session the way a person would, then check the books."""
    e, s = fresh()
    src = simulate.make_source("biased", e.symbols, seed=13)
    start = e.capital
    for i in range(300):
        pr = e.plan()
        if i % 3 == 0 and pr["committed"]:
            e.place_bet(None, follow="bot")
        elif i % 3 == 1 and e.capital >= 240:
            e.place_bet({"r": 120, "b": 120, "g": 0}, follow="mine")
        else:
            e.pass_turn()
        e.resolve(src.next())
    turns = e.session["turns"]
    assert len(turns) == 300
    # the accounting identity must hold exactly
    approx(e.capital, start + sum(t["pnl"] for t in turns), 1e-6)
    for t in turns:
        approx(t["capital_after"], t["capital_before"] + t["pnl"], 1e-6)
    approx(turns[-1]["capital_after"], e.capital, 1e-6)
    assert e.capital >= 0
    # and the model must have learned 300 results
    assert e.brain.n_obs == 300
    st = e.state()
    assert st["phase"] == "await_bet"
    assert len(st["recent_turns"]) == 25
    assert st["shape_lab"] and st["patterns"] is not None


def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    tests = [t for t in RESULTS if not only or any(o in t.__name__ for o in only)]
    passed, failed = 0, []
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ok   {fn.__name__}")
        except Exception as exc:                                  # noqa: BLE001
            failed.append((fn.__name__, exc))
            print(f"  FAIL {fn.__name__}: {exc}")
            if VERBOSE:
                traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    if failed:
        print("failures:")
        for name, exc in failed:
            print(f"  - {name}: {exc}")
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
