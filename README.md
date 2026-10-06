# buzzcast

A capital simulator for a red / blue / green game, with a bot that predicts,
sizes its own bets, and keeps score of whether you should be listening to it.

You play a turn at a time: the bot tells you what it thinks and what it would
stake; you place a bet (or copy its bet, or pass); you enter the real result
when it lands; everything learns. The bankroll is tracked to the last coin.

Rebuilt from scratch in October 2026 from the original v1 design notes. Pure
standard library — no pip install, no internet, no build step.

**New here? Read [QUICKSTART.md](QUICKSTART.md)** — setup, how to play, and how
long you need to record before results mean anything.

```
START.bat                 Windows: double-click this
./start.sh                macOS / Linux
python3 run.py            any platform: then open http://127.0.0.1:8077
python3 tests.py          40 tests, ~10 seconds
python3 console.py sim biased bot 500
```

---

## The odds you are playing against

All three colours pay **3×**. That means the implied probabilities are
1/3 + 1/3 + 1/3 = **1.000**:

| | |
|---|---|
| house edge | **0.00%** |
| arbitrage available | **none** |
| break-even hit rate, one colour | **33.3%** |
| break-even hit rate, any pair | **66.7%** |

There is no house edge and there is no clever combination that prints money.
Every profit in this game comes from one place only: **predicting better than
chance**. A bet is worth making exactly when the colour you back comes in more
often than its break-even rate — 33.3% for a single colour, 66.7% for a split.

### Why the bot does nothing for a while

Expect a long flat stretch at the start. `python3 console.py sim markov_strong
bot 400` prints this bankroll curve:

```
    0      1,000 |*
   ...
  160        980 |*
  170      2,070 |         *
  190      8,260 |                            *
  210     17,440 |                                      *
  230     25,500 |                                           *
```

It sat on its hands for 160 turns — on a source that is *genuinely, strongly
predictable* — and then compounded to 25× when the evidence arrived. That
plateau is the honesty gate doing its job: the pattern only becomes provable
after enough results have accumulated. A bot that bet from turn 5 would have
been guessing, and on a fair game that guessing is what drains a bankroll.
Turns are seconds in the simulator and minutes at a real table, so plan for
the warm-up and don't read it as the bot being broken.

### Your 120 red + 120 blue split

| result | return | net |
|---|---|---|
| red | 360 on a 240 stake | **+120** |
| blue | 360 on a 240 stake | **+120** |
| green | 0 | **−240** |

So it wins 2 outcomes out of 3 and still loses money if those outcomes don't
actually happen 66.7% of the time. On a fair game the split is exactly
break-even in expectation, and the simulator will show you the variance slowly
grinding a flat-staked bankroll down — that is the honest answer, and
`tests.py::test_sim_split_strategy_busts_on_a_fair_game` asserts it.

The split's real advantage is *feel*: you get the satisfaction of covering two
thirds of the board. Its real cost is that one losing turn costs you twice a
winning turn, so a modest losing streak is expensive. The **Bet types** tab
compares the split against singles, coverage and the bot's own sizing on the
same exposure, and shows the "needs cover" figure next to the live one.

---

## What the bot actually does

**1. It predicts.** A context model over the last 1–5 results, with each depth
scored by its out-of-sample performance and blended by an exponentially
weighted hedge. It is judged walk-forward: every prediction it makes is
recorded *before* the result is revealed, and all the numbers the UI shows you
are computed from those honest predictions. `test_brain_no_lookahead`
re-derives predictions from history prefixes and asserts they match, so a
result can never leak backwards.

**2. It sizes.** Fractional Kelly on its own probabilities: for a single colour
at decimal odds `d`, `f* = (d·p − 1) / (d − 1)`. At 44% on a 3× payout that is
16% of bankroll at full Kelly, quartered to 4%, and then capped by a per-turn
ceiling and a 20% exposure limit. It passes rather than betting when it has no
edge — on a fair game, every bet is a fresh 3× coin flip and the correct
number of them is zero.

**3. It refuses.** This is the feature, not a limitation. The **honesty gate**
will not commit unless three things are true at once:

- confidence clears the gate, **and**
- a **walk-forward paper trade** — 1 unit on its favourite every turn since
  warm-up, settled at real odds — is positive and statistically significant,
  tested with a one-sample t-test at a **Bonferroni-corrected** alpha, **and**
- its out-of-sample compression edge over the whole post-warm-up history is
  positive (proof it generalises, not just fits).

If only part of that holds it does not pretend: it says
**`provisional`**, slashes the stake to a third of normal, and tells you why.
Otherwise it says `pass` and lists exactly which test failed. There is no state
in which it is quietly confident.

That gate is what `test_brain_rejects_fair_game` protects: across 4,500 turns
of genuinely random results it must commit **zero** times, and on the weaker
Markov source it must hedge rather than bet hard. `test_no_stake_without_
corrected_evidence` pins the specific dataset that motivated the rule — the
old 70 results — and asserts it cannot buy a live position.

**4. It keeps score on you.** A meta-learner tracks your hit rate against the
bot's with confidence intervals, and answers "who should I be following?" with
`TRUST THE BOT`, `TRUST YOURSELF`, `TOO CLOSE TO CALL` or `NOT ENOUGH DATA`.
It also measures your tilt — your P/L on turns after a loss compared to your
baseline — so the answer to "am I playing worse when I'm annoyed?" is a number.

---

## The Simulation lab

The tracker can tell you what happened. Only a simulator can tell you whether
it happened *because* of something. The lab runs the real brain and the real
betting math against synthetic results with known ground truth:

| source | what it stands for | what the bot must do |
|---|---|---|
| `fair` | true 1/3 each — the null hypothesis | **bet nothing** |
| `biased` | one colour over-represented (44% green) | find it and stake up |
| `markov` | subtle streaks — real but thin | **hedge, don't bet the farm** |
| `markov_strong` | +74% edge after a repeat | back up the truck |
| `replay` | your own recorded results, looped | learn from what you have |
| `custom` | probabilities you type in | — |

Strategies include `bot` (the follow-the-button policy, hedges included),
`bot_strict` (full-size commitments only), a fixed split, always-on-the-
favourite, covering all three, Martingale, random, and `mirror_you` — which
replays your own recorded stake vectors so you can ask "what if I had kept
playing like that?"

Run the whole grid and read the **ruin rate** column first. On `fair`, every
strategy that keeps betting eventually dies, and Martingale dies fastest.
That is the entire lesson of the game in one table. The bot is the only line
that survives it — by declining to play.

You can also **fast-forward the live ledger**: same engine, same learning,
results auto-generated, so your actual bankroll and the bot's own record move.
Bulk-undo afterwards if you want to rewind.

---

## A worked example of why the gate matters

`biased` generates green 44% of the time. Over 239 live turns of that source,
the *observed* frequency came out green 36.0% / blue 37.2% / red 26.8% —
sampling noise hiding a real bias — and the bot's out-of-sample edge measured
**negative**, so it went `pass` and listed all three failed tests by name.

A tracker would have shown you "green is hot!" a week ago. This one will not
hand you a stake until the evidence is actually there. If you want to watch it
be *right* rather than cautious, give it 1,500+ results (the simulator does
this in about two seconds) — or point it at `markov_strong`, where it commits
almost immediately and compounds hard.

---

## The honesty of the numbers

- **Flat 3× on three outcomes is a zero-edge book.** Any "system" you read
  about that claims otherwise is measuring luck. The bot is built so that
  luck cannot flatter it.
- **Everything is walk-forward.** The commit decision recorded for turn *i*
  uses only results 0…*i*−1, including the info-gain figure and the paper
  trade. The backtest replays those recorded decisions rather than
  recalculating them with hindsight.
- **Multiple comparisons are corrected, and correction is the price of entry.**
  The gate runs every turn and watches every colour, so it uses α/k — and no
  stake of any size is offered on evidence that fails that corrected bar.
  Without it, a fair game manufactures a "pattern" every twenty turns and the
  hedges on those false positives produce 74–82% drawdowns.
- **A negative paper trade is disqualifying, not merely unsignificant.** If
  backing your own favourite has lost money, your favourite is not a bet,
  whatever a frequency test says.
- **Two independent ways to be right.** Requiring both a base-rate edge *and*
  a sharp probability distribution would block real bets — a model can be
  badly calibrated and still have a profitable favourite. So either line of
  evidence can license a hedge on its own; the strict commit bar still needs
  the full package.
- **Zero-variance samples are handled.** A record with no variance and a
  positive mean is the strongest evidence there is; a naive t-test reports it
  as p = 0.50. `_p_from` special-cases it.
- **The lab and the live game agree.** The simulator uses a fast normal
  approximation for thousands of turns; the live game uses exact arithmetic.
  On identical data the two agree on 99.8–100% of tier decisions.

---

## Layout

```
run.py               start the web app            console.py   no-browser CLI
tests.py             the regression suite         config.json  all settings
archive_old_history.py   optional seed from the lost v1 run
engine/
  brain.py           context model, walk-forward evidence, the honesty gate
  betting.py         Kelly sizing, bet shapes, break-even and cover analysis
  trust.py           meta-learner: bot vs you, tilt, streaks, risk
  game.py            the turn loop and the ledger (single source of truth)
  simulate.py        sources x strategies lab
  stats.py           distributions, tests, drawdown — stdlib only
  storage.py         atomic writes, backup recovery, CSV export
  settings.py        config load/merge/validate
web/
  server.py          stdlib HTTP + JSON API
  static/            index.html, app.js, style.css — no CDN, no dependencies
```

The **ledger is the single source of truth**: capital, the model, the trust
score and every curve are all derived from the list of turns. That is why
`undo` and `edit` are safe — delete or amend a row, then re-derive. A turn
records both bets (yours and the bot's) whether or not you followed it, so the
meta-learner can score alternatives you didn't take. Passing still records the
result, because a result you didn't bet on is still information.

---

## Configuration

Everything lives in `config.json` and is editable live in the **Settings** tab.

| key | default | meaning |
|---|---|---|
| `payouts` | 3.0 each | the book |
| `capital.starting` | 1000 | opening bankroll |
| `capital.stake_step` / `min_stake` | 10 / 10 | rounding and floor |
| `capital.max_stake_per_turn` | 600 | hard ceiling per turn |
| `capital.max_exposure_fraction` | 0.20 | most of the bankroll in play |
| `capital.default_split_stake` | 120 | your split preset |
| `honesty.confidence_threshold_percent` | 38.0 | confidence gate |
| `honesty.min_info_gain_bits` | 0.01 | required out-of-sample edge |
| `honesty.max_p_value` | 0.05 | significance, Bonferroni-corrected |
| `honesty.provisional_kelly_scale` | 0.3 | stake multiplier when hedging |
| `bot_bet.kelly_fraction` | 0.25 | fractional Kelly |
| `brain.max_context_order` | 5 | deepest context considered |
| `brain.recency_decay` | 0.997 | forgetting rate |

The confidence gate is 38%, not the 55% the v1 notes assumed. At flat 3× no
probability can exceed 45% for a favourite under any believable model, so a
55% gate could never be satisfied — the bot would have been silent forever.
The real gate is the paper trade; confidence just filters the obvious cases.

---

## The old data

The 70 results from the lost v1 run are in `archive/old_history.json` and are
**never loaded automatically**. They are kept as an optional seed only: the
**Settings** tab has *Seed model from the old 70 results*, which uses them to
warm the model's priors while leaving your capital ledger at turn 1. For the
record, they were green 44.3% (χ² = 3.8 on 2 df, p ≈ 0.15) — a mild lean,
not a proven bias, and far too little data to bet on.

## Notes

- Requires Python 3.8+. Nothing else. `START.bat` (Windows) or `start.sh` launches it.
- Being stdlib-only keeps the original PyInstaller `.exe` route open if you
  ever want a double-clickable Windows build.
- `data.json` and `data.backup.json` are gitignored — your real session stays
  on your machine. If the file is ever corrupted, the loader self-heals from
  the backup, and the model rebuilds from your turns.
- `python3 tests.py` runs in about ten seconds and is worth running after any
  change to `brain.py`: most of the suite exists to prove the bot *cannot*
  cheat, and if a change makes the fair-game test fail you have built a liar
  rather than a predictor.
