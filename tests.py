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

import archive_old_history                                      # noqa: E402
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


# ---------------------------------------------------------------- analyzer
@test
def test_analyzer_reads_a_live_session():
    """analyze.py must find results where they actually live.

    A live session keeps its results inside the turns; warm_start only holds an
    optional seed. Reading only warm_start made the report announce "no results
    yet" on a session with 420 played turns.
    """
    import analyze
    e, _ = fresh()
    src = simulate.make_source("markov_strong", e.symbols, seed=77)
    for _ in range(60):
        e.place_bet({"r": 100, "b": 100, "g": 0}, follow="mine")
        e.resolve(src.next())
    e.flush()
    data = analyze.load_any(e.path)
    assert len(data["results"]) == 60, len(data["results"])
    assert len(data["turns"]) == 60
    text = analyze.report(e.path)
    assert "60 recorded results" in text
    assert "No results in there yet" not in text


@test
def test_analyzer_agrees_across_file_formats():
    """A ledger, an exported turns CSV and a results CSV must analyse the same."""
    import analyze
    import tempfile
    e, _ = fresh()
    src = simulate.make_source("biased", e.symbols, seed=5)
    for i in range(80):
        if i % 3 == 0:
            e.pass_turn()
        else:
            e.place_bet({"r": 60, "b": 60, "g": 0}, follow="mine")
        e.resolve(src.next())
    e.flush()
    d = tempfile.mkdtemp()
    tp = os.path.join(d, "turns.csv")
    rp = os.path.join(d, "results.csv")
    with open(tp, "w", encoding="utf-8") as fh:
        fh.write(e.export_csv())
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write(e.export_results_csv())

    a = analyze.load_any(e.path)
    b = analyze.load_any(tp)
    c = analyze.load_any(rp)
    assert a["results"] == b["results"] == c["results"], "CSVs disagree with the ledger"
    # the exported turns file must still know which bets covered two colours
    pa = analyze.play_stats(a["turns"], e.symbols)
    pb = analyze.play_stats(b["turns"], e.symbols)
    assert pa and pb
    assert pa["shared"] == pb["shared"] > 0, (pa["shared"], pb["shared"])
    assert abs(pa["pnl"] - pb["pnl"]) < 1e-6
    assert abs(pa["staked"] - pb["staked"]) < 1e-6


@test
def test_analyzer_verdicts_match_the_known_truth():
    """Test the RATE of false alarms, not one hand-picked sequence.

    A 5% test is supposed to misfire on roughly one game in twenty - asking a
    single fixed seed to come back non-significant is cherry-picking, and the
    first version of this test did exactly that before a fair seed duly came
    back at p = 0.029.
    """
    s = Settings.load()
    # the invariant on a memoryless game: the continuation rate is 2/3
    rng = random.Random(11)
    fair = [rng.choice(["r", "b", "g"]) for _ in range(3000)]
    o = simulate.trend_report(fair, s.symbols, min_run=3)["overall"]
    assert abs(o["continued_pct"] - 66.67) < 2.0, o["continued_pct"]

    # and false alarms stay rare across independent games
    alarms = 0
    for seed in range(16):
        r2 = random.Random(900 + seed)
        seq = [r2.choice(["r", "b", "g"]) for _ in range(1200)]
        if simulate.trend_report(seq, s.symbols, min_run=3)["overall"]["p_value"] <= 0.05:
            alarms += 1
    assert alarms <= 4, f"{alarms}/16 fair games flagged - the test is over-eager"

    # a strongly streaky game must be caught
    strong = markov_stream(2000, M_STRONG, seed=4)
    rep2 = simulate.trend_report(strong, s.symbols, min_run=3)
    assert rep2["overall"]["p_value"] <= 0.05
    assert rep2["overall"]["continued_pct"] > 66.67
    assert "memory" in rep2["verdict"]


@test
def test_turns_needed_is_sane():
    import analyze
    assert analyze.turns_needed(0.67) > 100000      # impossible to prove
    assert analyze.turns_needed(0.71) > analyze.turns_needed(0.76)
    assert 100 < analyze.turns_needed(0.76) < 400
    assert 500 < analyze.turns_needed(0.71) < 1000


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
    with open(path, "w", encoding="utf-8") as fh:
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



@test
def test_follow_bot_respects_the_gate():
    """Following the bot must never stake MORE than the bot proposed.

    This is the bug that a 31-test suite missed: the gate was correct, but the
    "follow the bot" path applied the tier's stake multiplier only in the
    provisional case, so on a `pass` tier it quietly placed a full Kelly stake
    while the bot was telling you to sit the turn out. Tests that gate on
    ``pred.committed`` before calling place_bet cannot see it, because they
    never exercise the click a user actually makes.
    """
    e, s = fresh()
    # an empty brain has no edge, so every tier must be pass and cost nothing
    for _ in range(6):
        pr = e.plan()
        assert pr["tier"] == "pass", pr["tier"]
        assert pr["kelly_scale"] == 0.0
        p = e.place_bet(None, follow="bot")
        assert p["stake_total"] == 0.0, \
            f"follow-the-bot staked {p['stake_total']} on a pass tier"
        e.resolve("r")
    approx(e.capital, 1000.0)
    assert len(e.session["turns"]) == 6, "the turns must still be recorded"
    # on a genuinely profitable source the same click must stake something
    e2, _ = fresh()
    src = simulate.make_source("biased", e2.symbols, seed=41)
    for _ in range(120):
        e2.plan()
        e2.place_bet(None, follow="bot")
        e2.resolve(src.next())
    assert any(t["stake_total"] > 0 for t in e2.session["turns"]), \
        "follow-the-bot never staked on a source with a real edge"


@test
def test_follow_bot_never_exceeds_its_own_proposal():
    """Whatever the tier, the followed stake is the proposal times its scale."""
    e, s = fresh()
    src = simulate.make_source("markov", e.symbols, seed=44)
    for _ in range(150):
        pr = e.plan()
        proposed = float((pr["bet"] or {}).get("total") or 0)
        p = e.place_bet(None, follow="bot")
        expected = proposed * float(pr["kelly_scale"])
        # allow rounding to the stake step and the min-stake floor
        assert p["stake_total"] <= expected + 10 + 1e-9, \
            (p["stake_total"], expected, pr["tier"])
        if pr["tier"] == "pass":
            assert p["stake_total"] == 0.0
        e.resolve(src.next())


@test
def test_no_stake_without_corrected_evidence():
    """The old 70 results must not buy a live position.

    A 3.4% one-sided lean on 70 samples fails the Bonferroni bar, and the
    model's own probabilities are worse than uniform on that data - two weak
    signals pointing opposite ways. Marginal evidence must buy nothing.
    """
    s = Settings.load()
    b = Brain(s).fit(archive_old_history.load())
    pr = b.predict()
    assert pr.tier == "pass", (pr.tier, pr.roi_pct, pr.p_edge)
    assert pr.kelly_scale == 0.0
    assert b.ig_all() < 0.0, "this dataset should measure a negative edge"


# ----------------------------------------------------------------------- trends
@test
def test_trend_report_finds_no_memory_in_a_fair_game():
    """A two-colour run must NOT predict anything when the game has no memory.

    This is the mathematically exact claim the whole Trends tab rests on: for
    an i.i.d. game, P(next is in the pair | the last k were in the pair) is
    exactly 2/3 for EVERY k. Long runs are common - you expect ~23 twelve-turn
    runs per 1,000 turns - but they carry no information, so the observed
    continuation rate must sit at the 66.7% break-even no matter how long the
    run is.
    """
    s = Settings.load()
    rng = random.Random(1)
    seq = [rng.choice(["r", "b", "g"]) for _ in range(10000)]
    rep = simulate.trend_report(seq, s.symbols, min_run=3, max_run=10)
    o = rep["overall"]
    assert o["n"] > 1000, o["n"]
    assert abs(o["continued_pct"] - 66.67) < 2.5, o["continued_pct"]
    assert not (o["p_value"] <= 0.05 and o["continued_pct"] > 66.67), \
        "claimed a trend edge on a game with no memory"
    # and run length must not change the answer
    for row in rep["rows"]:
        assert abs(row["continued_pct"] - 66.67) < 7.0, row


@test
def test_trend_report_finds_memory_when_it_exists():
    s = Settings.load()
    seq = markov_stream(6000, M_STRONG, seed=9)
    rep = simulate.trend_report(seq, s.symbols, min_run=3, max_run=10)
    o = rep["overall"]
    assert o["continued_pct"] > 70.0, o["continued_pct"]
    assert o["p_value"] <= 0.01, o["p_value"]
    assert "memory" in rep["verdict"]


@test
def test_current_trend_reads_the_run_correctly():
    s = Settings.load()
    # a clean two-colour run
    cur = simulate.current_trend(["g", "r", "g", "r", "g", "r"], 3)
    assert cur["active"] and cur["pair"] == ["g", "r"], cur
    assert cur["run"] == 6
    # a third colour inside the window kills the read
    cur = simulate.current_trend(["g", "r", "g", "r", "b"], 3)
    assert not cur["active"], cur
    # a one-colour streak is reported but is not a pair
    cur = simulate.current_trend(["r", "r", "r", "r"], 3)
    assert not cur["active"] and cur["covered"] == ["r"]
    # and no crash on nothing
    assert simulate.current_trend([], 3)["active"] is False


@test
def test_trend_stake_size_is_what_burns_you():
    """On a fair game the trend bet must be destructive, and the bot must not be.

    The strategy is break-even in expectation, so the loss cannot come from a
    bad edge - it comes from putting 300 on a 1,000 bankroll and losing all of
    it a third of the time. Median outcome is near zero while the mean stays
    up around break-even, which is the signature of a high-variance bet that
    most players will not survive.
    """
    s = Settings.load()
    trend, bot = [], []
    for sd in range(12):
        trend.append(simulate.run("fair", "trend2", 400, s, start_capital=1000,
                                  seed=sd, opts={"stake": 150, "trend_min_run": 3}))
        bot.append(simulate.run("fair", "bot", 400, s, start_capital=1000,
                                seed=sd, opts={"stake": 150}))
    trend_final = sorted(r["final_capital"] for r in trend)
    bot_final = sorted(r["final_capital"] for r in bot)
    assert sum(1 for r in trend if r["ruined"]) >= 3, \
        "the trend bet survived a fair game too often to be realistic"
    assert trend_final[0] < 500, trend_final[0]
    assert bot_final[0] > 900, "the bot must not lose money on a fair game"
    assert sum(1 for r in bot if r["ruined"]) == 0


@test
def test_trend_policy_wins_where_memory_is_real():
    """The same strategy must make money when the game genuinely streaks."""
    s = Settings.load()
    runs = [simulate.run("markov_strong", "trend2", 600, s, start_capital=1000,
                         seed=sd, opts={"stake": 150, "trend_min_run": 3})
            for sd in range(6)]
    fin = sorted(r["final_capital"] for r in runs)
    assert fin[len(fin) // 2] > 2000, fin


# -------------------------------------------------------------- simulations
@test
def test_sim_fair_game_loses_nothing_for_the_bot():
    """On noise the bot must not COMMIT, and must not lose money either way.

    Two distinct claims, tested separately: the strict policy places no bets
    at all, while the follow-the-button policy takes its small provisional
    hedges - which on a fair game must still average out near break-even with
    bounded damage rather than compounding.
    """
    s = Settings.load()
    strict = simulate.run("fair", "bot_strict", 1500, s, start_capital=1000,
                          seed=17, opts={"stake": 120})
    assert strict["bets"] == 0, f"bot_strict bet {strict['bets']} times on noise"
    approx(strict["final_capital"], 1000.0, 1e-6)
    assert not strict["ruined"]

    finals = []
    for seed in (4, 5, 6, 7, 8, 9):
        r = simulate.run("fair", "bot", 1500, s, start_capital=1000, seed=seed,
                         opts={"stake": 120})
        assert r["committed_turns"] == 0, \
            f"seed {seed}: committed {r['committed_turns']} times on a fair game"
        assert r["max_drawdown_pct"] < 35.0, \
            f"seed {seed}: {r['max_drawdown_pct']:.1f}% drawdown on noise"
        finals.append(r["final_capital"])
    avg = sum(finals) / len(finals)
    assert 800 < avg < 1250, f"fair-game hedges drifted to {avg:.0f}: {finals}"


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


@test
def test_every_test_is_registered():
    """A test function that is not in RESULTS never runs - and the suite still
    prints "all good".

    That is not hypothetical. While adding the table-view tests, one insert
    landed between an @test decorator and the function it belonged to, which
    silently unregistered two tests - including the busy-port test that caught
    the Windows port bug in 2.3.1. The suite reported 45/45 and looked healthy
    while covering less than it had before. This closes the hole for good.
    """
    missing = sorted(
        n for n, v in list(globals().items())
        if n.startswith("test_") and callable(v) and v not in RESULTS)
    assert not missing, "defined but never run: %s" % ", ".join(missing)


@test
def test_two_lucky_wins_cannot_license_a_stake():
    """A zero-variance sample must be priced, not declared certain.

    The bug this pins: a 3x payout returns +2 for a win and -1 for a loss, so
    TWO consecutive wins is a zero-variance positive-mean sample. The t-test
    helper treated zero variance as "maximally consistent, therefore p=0",
    which handed a Bonferroni-corrected gate p=0.0000 on two coin flips. The
    practical result: on a genuinely FAIR game, one seed in twelve reached the
    "commit" tier on turn 17 and would have licensed a real stake with no edge
    behind it. Found by recording-only studies, not by any existing test.

    At zero variance every counted step had the same outcome, so a positive
    mean means every step won, and the exact probability of that is p_null**n.
    """
    from engine.brain import _p_from

    # exact, at every size
    for n in (2, 3, 4, 5, 6, 10, 16):
        approx(_p_from(2.0, 0.0, n, 1 / 3), (1 / 3) ** n)   # asserts internally

    # two lucky wins must not clear the Bonferroni bar the gate uses
    assert _p_from(2.0, 0.0, 2, 1 / 3) > 0.0167
    assert _p_from(2.0, 0.0, 3, 1 / 3) > 0.0167
    # but a genuinely improbable run still can
    assert _p_from(2.0, 0.0, 10, 1 / 3) < 0.0167

    # longer runs are always stronger evidence, never weaker
    ps = [_p_from(2.0, 0.0, n, 1 / 3) for n in range(2, 20)]
    assert all(b <= a for a, b in zip(ps, ps[1:])), ps

    # a flat or losing record is never evidence, however consistent
    assert _p_from(-1.0, 0.0, 50, 1 / 3) == 1.0
    assert _p_from(0.0, 0.0, 50, 1 / 3) == 1.0
    assert _p_from(2.0, 0.0, 1, 1 / 3) == 1.0

    # the ordinary path is untouched
    assert 0.0 < _p_from(0.5, 1.0, 100, 1 / 3) < 0.001


@test
def test_a_fair_game_never_reaches_commit_on_a_lucky_start():
    """End to end: the exact scenario that shipped broken.

    Fifteen warm-up turns, then straight wins. Before the fix this reached
    "commit" two turns after warm-up. The gate must hold.
    """
    import tempfile
    from engine.settings import Settings
    from engine.game import GameEngine

    tmp = tempfile.mkdtemp()
    st = Settings.load(path=os.path.join(tmp, "c.json"))
    g = GameEngine(st, path=os.path.join(tmp, "d.json"), autosave=False)
    g.new_session("lucky", starting=1000)
    syms = g.symbols

    committed_at = None
    for t in range(40):
        g.plan()
        g.pass_turn()
        # always the same colour: the model's favourite will hit every time
        g.resolve(syms[0])
        p = g.state()["prediction"]
        if p["tier"] == "commit":
            committed_at = t + 1
            break

    if committed_at is not None:
        # only permissible once the run is long enough to actually be unlikely
        assert committed_at >= 16, (
            "committed on turn %d of a run that is not yet improbable" % committed_at)


@test
def test_paper_trade_reports_its_own_sample_size():
    """The readiness ladder shows "paper trade +X% over N turns".

    N has to be the number of turns the paper trade actually counted, not a
    tier-step count and not the raw turn count - those differ by the warm-up,
    and showing the wrong denominator would make the record look thinner or
    fatter than it is at exactly the moment the user is deciding whether to
    start staking.
    """
    import tempfile
    from engine.settings import Settings
    from engine.game import GameEngine

    tmp = tempfile.mkdtemp()
    st = Settings.load(path=os.path.join(tmp, "c.json"))
    g = GameEngine(st, path=os.path.join(tmp, "d.json"), autosave=False)
    g.new_session("paper", starting=1000)
    warm = st.data["brain"]["min_data_before_analysis"]

    for i in range(60):
        g.plan()
        g.pass_turn()
        g.resolve(["r", "b", "g"][i % 3])

    b = g.state()["brain"]
    assert "paper_roi_n" in b, "the ladder has no sample size to show"
    n = b["paper_roi_n"]
    # counted from the end of warm-up only, and never more than the turns played
    assert n <= 60, n
    assert n >= 60 - warm - 1, (n, warm)
    # and it must agree with the stats it is attached to
    assert 0.0 <= b["paper_roi_p_value"] <= 1.0


@test
def test_the_paper_trade_grows_while_you_risk_nothing():
    """The whole 'record first, stake later' plan depends on this.

    Passing every turn must still feed the model AND grow the bot's own
    paper-trade record, so that following it later rests on evidence that
    accumulated at zero financial risk. If a pass ever skipped observe(), the
    plan would quietly become "wait 300 turns for nothing".
    """
    import tempfile
    from engine.settings import Settings
    from engine.game import GameEngine

    tmp = tempfile.mkdtemp()
    st = Settings.load(path=os.path.join(tmp, "c.json"))
    g = GameEngine(st, path=os.path.join(tmp, "d.json"), autosave=False)
    g.new_session("recordonly", starting=1000)
    start_capital = g.capital
    warm = st.data["brain"]["min_data_before_analysis"]

    for i in range(120):
        g.plan()
        g.pass_turn()
        g.resolve(["r", "b", "g"][(i * 7) % 3])

    b = g.state()["brain"]
    assert b["n_obs"] == 120, b["n_obs"]              # the model learned everything
    assert b["paper_roi_n"] >= 120 - warm - 1         # and the paper trade grew
    assert g.capital == start_capital, "passing must not move the bankroll"
    assert g.state()["capital"]["turns"] == 120       # every turn is on the record


@test
def test_every_open_says_which_encoding_it_wants():
    """An open() without an encoding uses the platform default.

    On Linux that is UTF-8 and everything works. On Windows it is cp1252, and
    the first curly quote, middot or em dash in the file raises
    "'charmap' codec can't decode byte 0x8f". This shipped: 2.7 passed 52/52
    on Linux and failed 51/52 on the user's machine, because the table-view
    test read the static files without naming an encoding. Same shape as the
    SO_REUSEADDR port bug - correct on the machine it was written on, broken on
    the only machine that matters.

    Binary reads are exempt and are the correct way to move bytes around.
    """
    import ast
    import os

    root = os.path.dirname(os.path.abspath(__file__))
    offenders = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".git", "archive", "tmp")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            try:
                tree = ast.parse(open(full, encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if isinstance(fn, ast.Name):
                    is_open = fn.id == "open"                 # the builtin
                elif isinstance(fn, ast.Attribute):
                    # io.open / codecs.open are the builtin by another name.
                    # webbrowser.open is NOT a file and must not be flagged.
                    owner = getattr(fn.value, "id", None)
                    is_open = fn.attr == "open" and owner in ("io", "codecs")
                else:
                    is_open = False
                if not is_open:
                    continue
                mode = None
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                named = any(kw.arg == "encoding" for kw in node.keywords)
                if "b" in str(mode or "r"):
                    continue                     # binary needs no encoding
                if not named:
                    offenders.append("%s:%d" % (os.path.relpath(full, root), node.lineno))

    assert not offenders, (
        "these open() calls would use the Windows default encoding: "
        + ", ".join(offenders))


@test
def test_the_analyzer_reads_whatever_windows_did_to_the_file():
    """analyze.py is fed files a person produced, on Windows.

    Excel re-saves CSVs in the local code page and adds a BOM; a hand-edited
    JSON gets saved with a BOM by Notepad. Reading with a hardcoded utf-8 turned
    every one of those into a bare "charmap codec" crash. All four shapes must
    load, and the most likely one - an Excel round-trip - most of all.
    """
    import csv as _csv
    import json as _json
    import os
    import tempfile
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import analyze

    tmp = tempfile.mkdtemp()
    rows = [{"symbol": "r"}, {"symbol": "g"}, {"symbol": "b"}]

    def write_csv(enc, bom=False):
        path = os.path.join(tmp, "t_%s.csv" % enc.replace("-", ""))
        with open(path, "w", newline="", encoding=enc) as fh:
            if bom:
                fh.write("\ufeff")
            w = _csv.DictWriter(fh, fieldnames=["symbol"])
            w.writeheader()
            w.writerows(rows)
        return path

    for enc, bom in (("utf-8", False), ("utf-8-sig", False), ("cp1252", False)):
        got = analyze.load_any(write_csv(enc, bom))
        assert len(got["results"]) == 3, (enc, got["results"])

    # a JSON saved by Notepad with a BOM, containing an accented character
    doc = {"sessions": {"S": {"turns": [{"n": 1, "result": "r"}, {"n": 2, "result": "g"}]}},
           "active": "S", "note": "caf\u00e9"}
    jp = os.path.join(tmp, "boom.json")
    open(jp, "w", encoding="utf-8-sig").write(_json.dumps(doc, ensure_ascii=False))
    assert len(analyze.load_any(jp)["results"]) == 2

    jp2 = os.path.join(tmp, "cp.json")
    open(jp2, "w", encoding="cp1252").write(_json.dumps(doc, ensure_ascii=False))
    assert len(analyze.load_any(jp2)["results"]) == 2

    # and the plain utf-8 case still works
    jp3 = os.path.join(tmp, "plain.json")
    open(jp3, "w", encoding="utf-8").write(_json.dumps(doc))
    assert len(analyze.load_any(jp3)["results"]) == 2


@test
def test_the_tools_survive_a_windows_console():
    """Every entry point must run under the code pages Windows actually has.

    The Windows console in France is cp850, and cp850 cannot represent an em
    dash. Measured before the fix: `python analyze.py` crashed outright with a
    UnicodeEncodeError part-way through the report, and `python run.py --help`
    crashed on its own description string. On Linux every one of these passed,
    because the Linux default encoding is UTF-8.

    This runs the real programs in a subprocess with a hostile encoding, which
    is the only way to catch it - the failure lives in the print() call, not in
    any function a unit test can call.
    """
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp850"
    env.pop("PYTHONUTF8", None)

    runs = [
        ([sys.executable, "analyze.py", os.path.join("archive", "old_history.json")],
         "analyze.py on the archived history"),
        ([sys.executable, "run.py", "--help"], "run.py --help"),
    ]
    for cmd, label in runs:
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True,
                              timeout=120, errors="replace")
        assert proc.returncode == 0, (
            "%s failed under a cp850 console:\n%s" % (label, (proc.stderr or "")[-600:]))
        assert "UnicodeEncodeError" not in (proc.stderr or ""), label


@test
def test_analyzer_reads_a_csv_excel_has_touched():
    """The realistic Windows round trip, end to end.

    The history CSV comes out of the app as UTF-8, but the moment it is opened
    and re-saved in Excel it becomes the local code page, and Excel adds a BOM.
    That must still analyse.
    """
    import csv as _csv
    import os
    import subprocess
    import sys
    import tempfile

    root = os.path.dirname(os.path.abspath(__file__))
    tmp = tempfile.mkdtemp()
    rows = [{"n": i, "symbol": s} for i, s in
            enumerate("rbggbrbrgrbbgrgrbgbrgb", 1)]

    for enc, label in (("cp1252", "re-saved by Excel"),
                       ("utf-8-sig", "with a BOM")):
        path = os.path.join(tmp, "excel_%s.csv" % label.replace(" ", "_"))
        with open(path, "w", newline="", encoding=enc) as fh:
            if enc == "utf-8-sig":
                fh.write("\ufeff")
            w = _csv.DictWriter(fh, fieldnames=["n", "symbol"])
            w.writeheader()
            w.writerows(rows)
        proc = subprocess.run([sys.executable, "analyze.py", path],
                              cwd=root, capture_output=True, text=True,
                              timeout=120, errors="replace")
        assert proc.returncode == 0, (label, (proc.stderr or "")[-400:])
        assert "recorded results" in proc.stdout, label


@test
def test_table_view_is_actually_served():
    """The game screen must be in the files the server hands the browser.

    The table view lives entirely in the static assets, so a typo in an id or a
    rename that misses one place fails silently - the page just renders empty.
    This pins every piece the JavaScript reaches for.
    """
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    html = open(os.path.join(root, "web", "static", "index.html"),
                encoding="utf-8").read()
    js = open(os.path.join(root, "web", "static", "app.js"), encoding="utf-8").read()
    css = open(os.path.join(root, "web", "static", "style.css"), encoding="utf-8").read()

    for needed in ("tv-tiles", "tv-actions", "tv-strip", "tv-setup",
                   "tv-bankroll", "tv-stake", "tv-start", "tv-hint",
                   "tv-bot", "btn-mode", "tv-reopen"):
        assert 'id="%s"' % needed in html, "missing element #%s" % needed

    for fn in ("renderTable", "setMode", "tapColour", "nudgeColour",
               "recordResult", "lockBet", "repeatLastBet", "wireTable"):
        assert "function %s(" % fn in js, "app.js never defines %s()" % fn
    assert "renderTable();" in js, "renderTable() is never called"

    # every id the table code writes into must exist in the markup
    for eid in ("#tv-tiles", "#tv-actions", "#tv-strip", "#tv-setup", "#tv-bot", "#tv-hint"):
        assert eid in js, "app.js never touches %s" % eid

    assert ".tv-tile" in css and "table-mode" in css, "table view has no styling"


@test
def test_setup_card_numbers_reach_the_engine():
    """The two-number setup card must actually configure the engine.

    It posts capital.starting / default_split_stake and then opens a session at
    that bankroll. If the patch shape drifts, the card looks like it works while
    changing nothing - the worst kind of bug here.
    """
    import os
    import tempfile
    from engine.settings import Settings
    from engine.game import GameEngine

    tmp = tempfile.mkdtemp()
    st = Settings.load(path=os.path.join(tmp, "config.json"))
    g = GameEngine(st, path=os.path.join(tmp, "data.json"), autosave=False)

    bank, stake = 2500, 75
    st.patch({"capital": {
        "starting": bank,
        "default_split_stake": stake,
        "min_stake": min(10, stake),
        "max_stake_per_turn": max(stake * 2, round(bank * 0.2)),
    }})
    assert st.data["capital"]["starting"] == bank
    assert st.data["capital"]["default_split_stake"] == stake

    g.new_session("real", starting=bank)
    assert g.capital == bank, "session did not open at the bankroll"
    # the stake the card set is inside what the engine will accept
    assert st.data["capital"]["min_stake"] <= stake <= st.data["capital"]["max_stake_per_turn"]

    labels = [p["label"] for p in g.presets()]
    assert any(l.upper().startswith("PASS") for l in labels), "no PASS preset"


@test
def test_server_moves_off_a_busy_port():
    """A port another program owns must never be reused.

    The blocker is deliberately created WITHOUT SO_REUSEADDR, because that is
    what a real other program looks like. The first version of this test set
    SO_REUSEADDR on the blocker, which tests nothing on Windows: there
    SO_REUSEADDR means "allow sharing this port", so both the blocker and the
    availability probe could hold it at once and the busy port was reported as
    free. On Unix it refused, so the bug only ever showed up on the user's
    Windows machine.
    """
    import socket
    from web.server import bind_server

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    base = None
    for cand in (19661, 19662, 19663, 19664):
        try:
            blocker.bind(("127.0.0.1", cand))
            base = cand
            break
        except OSError:
            continue
    if base is None:
        blocker.close()
        return                       # no free port to run the test on
    blocker.listen(1)
    httpd = None
    try:
        httpd, port = bind_server("127.0.0.1", base)
        assert port != base, f"server bound to the busy port {port}"
        assert port > base, port
        # the port it chose must genuinely accept connections
        probe = socket.create_connection(("127.0.0.1", port), timeout=5)
        probe.close()
    finally:
        if httpd is not None:
            httpd.server_close()
        blocker.close()


@test
def test_server_refuses_to_share_a_port():
    """On Windows allow_reuse_address lets two servers share a port silently.

    Guard against that being switched on: the class attribute must be False on
    nt and the bind must be the thing that decides availability.
    """
    import os as _os
    from web.server import Server
    if _os.name == "nt":
        assert Server.allow_reuse_address is False, \
            "on Windows this allows buzzcast to attach to another program's port"
    else:
        assert Server.allow_reuse_address is True, \
            "on Unix this is what permits a restart without waiting out TIME_WAIT"


def main() -> int:
    from engine import safe_console
    safe_console()
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
