# buzzcast — the short version

Everything you need is on this one page, in order. Ignore everything else until
you're curious.

---

## Part 1 — Put it on this laptop (3 steps)

**1. Download** `buzzcast-2.3-full.zip`

**2. Unzip it into your project folder**, replacing what's already there:

```
C:\Users\besta\Projects\buzzcast_bot
```

**3. Check it worked.** Open PowerShell and run these two lines:

```powershell
cd C:\Users\besta\Projects\buzzcast_bot
python tests.py
```

You want to see **`40/40 passed`**. If the number is smaller, the unzip went to
the wrong place — unzip again into the exact folder above.

---

## Part 2 — Start it (1 step)

**Double-click `START.bat`.**

A black window opens and your browser opens by itself.

> Keep the black window open while you play. Closing it stops buzzcast.

---

## Part 3 — Two numbers (once)

The first time you open it, the screen asks for exactly two things:

| | |
|---|---|
| **Your bankroll** | the money you're actually playing with |
| **Stake per colour** | your real bet — you play two colours, so a round costs 2× this |

Type them, press **Start playing**, and you're done. Every other setting in the
engine is already at a sane default and you never have to look at it.

That's the whole configuration. If you want to change the bankroll or stake
later, press **change bankroll / stake** at the bottom of the table screen.

> Anything deeper — the confidence bar, the Kelly fraction, how much the model
> decays old results — is under **Settings → every rule**, folded away in a
> disclosure. It's there for the curious. Nothing in there is needed to use the
> tool, and the defaults are the values we measured.

## Part 4 — Playing and recording

### The screen

You get one screen with **three big colour tiles**, one per colour. That's it.
What a tap does depends on where the round is:

| the round is… | the tiles say… | a tap… |
|---|---|---|
| **not started** | the stake you have on each colour | **puts your usual stake on that colour** (tap again to take it off) |
| **resolved** | what each colour pays, e.g. `+120` / `−240` | **records the colour that came up** |

The line across the top keeps the bot's opinion in one sentence — it never takes
over the screen, because you don't have to agree with it. The row of coloured
squares underneath is the running ticker of recent results.

Everything the dashboard shows is still there; press **Full dashboard →** in the
top right whenever you want it. Your browser remembers which one you prefer.

### The four stages — what to do right now

There's a strip across the top of the game screen that always tells you where
you are. Here is what it means:

| stage | results recorded | what you do |
|---|---|---|
| **1 · warming up** | 0–14 | **Record only.** The bot isn't allowed an opinion yet. |
| **2 · earning its trust** | 15+ | **Record only.** The bot has opinions, none proven. |
| **3 · close, not proven** | — | Keep recording. The bot has a positive record but hasn't cleared the bar. |
| **4 · proven edge** | — | **This is the signal.** The bot's own record is statistically significant. |

### Why "record only" is free

This is the part that makes the whole thing work. Every turn, the bot does two
things on its own:

1. it **watches the result** and learns from it, and
2. it **records what it would have bet**, and settles that bet on paper.

Neither of those needs a penny from you. So while you press `p` and tap R/B/G,
the bot is quietly building its own fully-settled betting record — the paper
trade. **That record is the evidence the bot uses to decide when it's allowed
to stake.**

The strip shows it: `bot's paper trade +14.2% over 125 turns, p = 0.041 — not proven`.

When that turns into `proven`, the bot has earned the right to be followed, and
you will not have risked anything to find out.

### When do predictions actually appear?

Three different things, at three different times. The screen shows all three.

| when | what happens |
|---|---|
| **turn 15** | the bot starts showing a **read** — a favourite colour and a percentage. Before this it refuses an opinion. |
| **the read climbs** | the strip shows `bot's read, last 40 turns: X% right`. Chance is 33%. This is the number to watch. |
| **~turn 100–300** | on a game with a real edge, the read is clearly above chance and the bot's paper trade becomes significant. |
| **never, on a fair game** | the read sits at 30–35% forever. That is the answer: there is nothing to predict. |

The **read** is the honest early signal, because it needs no money and no proof —
it is just "was the bot's favourite the colour that came up?". Measured over 300
turns of recording-only:

| the game | read at turn 50 | at turn 150 | at turn 300 |
|---|---|---|---|
| no pattern (fair) | 32% | 32% | 34% |
| a mild bias | 44% | 40% | 41% |
| strong momentum | 42% | 49% | 58% |

So: **a big edge shows up in the read by turn 50–100. A thin one needs 200–300
turns**, and sometimes stays invisible until you have 500+. On a fair game the
read never moves, which is exactly what you want to find out cheaply.

The **paper trade** is the stricter test, and it is what the bot uses to decide
whether it is allowed to stake. It needs more data than the read — see the
table below.

### How long does that take?

Measured on 12 independent games per row, record-only:

| the game | first positive-but-unproven | **first proven edge** |
|---|---|---|
| no edge at all (fair) | ~186 turns, or never | **never** |
| a mild bias | ~73 turns | **~170 turns** (90% by 253) |
| real momentum (thin) | ~71 turns | ~160 turns (90% by 564) |
| strong momentum | ~25 turns | **~100 turns** (90% by 205) |

Read the last column as your answer:

- **A real edge shows up around turn 100–170.** Often sooner if the edge is big.
- **If nothing has proven by turn 500, the game is probably fair.** That is a
  result, not a failure — it tells you to keep your money in your pocket.
- **Under 100 turns proves nothing either way.** Don't draw a conclusion yet.

So the honest plan is: **record 100–200 turns first.** If the strip reaches
stage 4, start following the bot. If it's still at stage 2 by turn 500, the
game has no usable pattern and you've lost nothing finding that out.

### Set up your screen once

Put the buzzcast window **beside** your game window so both are visible at the
same time. One hand stays on the keyboard. That's the whole physical setup —
if you have to alt-tab to record, you'll stop recording.

### The rhythm: ONE tap per turn

For your first turns the screen is in **recording only** mode, and a tap on a
colour tile means exactly one thing: *that colour just came up*. Nothing is
staked. The mode is on by default precisely so there is no way to bet by
accident while you are still collecting evidence.

```
the round ends  ->  tap the colour that came up
the round ends  ->  tap the colour that came up
...that is the entire job
```

When you decide you want to start staking for real, press **T** (or click the
"Recording only" button). The tiles then change meaning: before a round they
stake your usual amount, after a round they record. Press T again to go back.

### The keyboard rhythm

| what you want | press |
|---|---|
| put on your usual bet | <code>2</code> (preset) then <code>Enter</code> |
| put on the same bet as last turn | <code>space</code> |
| sit the turn out | <code>p</code> |
| **record the result** | <code>R</code> / <code>B</code> / <code>G</code> |
| cancel a bet you just placed | <code>Esc</code> |

**The important one is R / B / G.** When a round resolves you tap the key for
what came up — or tap the matching colour tile, whichever you prefer. No aiming
at small buttons either way.

So a normal turn is:

```
round resolves  ->  tap B          (recorded, model learns)
next round      ->  space          (same bet again)
round resolves  ->  tap R          (recorded)
...repeat
```

Two keystrokes. The badge at the top of the screen always tells you which phase
you're in, so you always know what a key press will do.

Number keys <code>1</code>–<code>6</code> are the presets in order, including
**PASS** at <code>1</code> and your split bets at <code>2</code>/<code>3</code>/<code>4</code>.

### The recording rules that make your data worth having

Most of the value here is in *what* you record, not how fast.

**1. Record every round — including the ones you sit out.**
This is the big one. Press <code>p</code>, then still press R/B/G when the
result lands. A result you didn't bet on is still information, and it costs you
nothing. If you only record the turns you bet, you've recorded *your mood*
rather than the game, and no amount of analysis can undo that.

**2. Record immediately, in the moment.**
Not at the end of the session from memory. Five minutes later you'll be unsure
whether that run was four reds or five, and a wrong result is worse than a
missing one — it corrupts every number downstream.

**3. Record what happened, not what you expected.**
The model is only as good as the honesty of the record.

**4. Keep the stake the same.**
Turn-to-turn comparison needs a constant. If you change your stake, start a new
session so the old numbers stay comparable.

**5. One table per session.**
If you switch games, sites or machines, start a new session (**+ session**).
Different game, different memory — mixing them hides both.

> **Want to answer "does this game have memory?" before risking anything?**
> Just record. Press <code>p</code> then R/B/G, over and over. You get the full
> trend verdict with none of your money at risk. That is a perfectly sensible
> way to spend your first 300 rounds.

### How long does this actually take?

One round is one keystroke. The clock that matters is your game's round timer:

| round length | 300 rounds is about |
|---|---|
| 30 seconds | 2.5 hours |
| 1 minute | 5 hours |
| 2 minutes | 10 hours |

Split across sessions — the ledger accumulates, so nothing is lost between
sittings.

### Reading the top of the screen

- **capital figure** — your bankroll, updating live
- **phase badge** — `place your bet` or `result pending`; this tells you what
  your keys will do
- **tier badge** on the bot's read — `commit` / `provisional` / `pass`

You do not have to look at the bot's prediction at all. It records its own view
every single turn whether or not you follow it, so the comparison is waiting for
you later.

## Part 4b — After a few hundred turns, analyse it

Once you've recorded a decent number of results, run this in the project folder:

```powershell
python analyze.py
```

It reads your own data and answers three things, in plain words:

1. **Are any colours coming up too often?**
2. **Does your trend bet actually work here?** (do two-colour runs continue
   more than the 66.7% it needs to break even)
3. **How much more data until that answer is trustworthy?**

It also tells you what your **actual betting** did — staked, profit, turnover,
deepest dip — and how many of your bets covered two colours.

To analyse an exported file instead (or send it to someone):

```powershell
python analyze.py results.csv
python analyze.py turns.csv
```

> If it ever looks significant, remember a 5% test misfires about **one game in
> twenty** by design. That's why the report shows you how many rows were
> examined and what the corrected bar is.

---

## Part 6 — Let it record for you (optional)

If you can run the game in an **Android emulator on your laptop** (BlueStacks,
LDPlayer, MuMu, or Android Studio's own emulator), the tool can watch the game's
Trend screen and record every result by itself. There is no video recording and
no timing to get right: the board shows the **last 50 results** and fills from
the bottom right, so a screenshot every few seconds already contains everything.

### Check the reader works, with no game at all

```
python capture.py --demo
```

It draws a pretend board, reads it back and reports. If that says
`read 50 of 50 correctly`, the reader is fine.

### Check it against your actual game

1. Win + Shift + S to screenshot the Trend popup, save it as a **PNG**.
2. ```
   python capture.py --file shot.png --report
   ```
3. It prints the board as letters. **Compare them with your screen**, left to
   right, top to bottom. If they match, everything else is configuration.

   It should look like this (this is a real read of a real board):

   ```
   G R R G R R B B R B
   B G R R B R G G G R
   G G B G B G B G R R
   R G G G R G B R R B
   G B G G B R B G R G
   ```

### Set up the emulator feed

**Preferred — straight from the emulator:**

1. Turn on **ADB** in your emulator's settings (BlueStacks: Settings →
   Advanced → Android Debug Bridge; LDPlayer and MuMu have the same switch).
2. Run:
   ```
   python capture.py --adb --once --report
   ```
   If it shows the board, you are done. If it says it cannot find `adb`, pass
   `--adb-path "C:\Program Files\BlueStacks_nxt\HD-Adb.exe"`.

**Fallback — capture a rectangle of the desktop:**

```
python capture.py --screens                                  (tells you the size)
python capture.py --screen 300,200,1100,800 --once --report   (X,Y,W,H of the popup)
```

### Then let it run

```
python capture.py --adb --watch --interval 15
```

Leave it going. Every new result is recorded into buzzcast **as a pass** — the
bankroll never moves, because this tool exists to gather evidence, not to bet.
It keeps a log in `capture_log.txt` and remembers where it was in
`capture_config.json`, so you can stop and restart it freely.

Press **Ctrl+C** to stop, then look at the app: the turns are all there.

### What it will and will not do

| it does | it does not |
|---|---|
| read the board and record results | place any bet, ever |
| survive one result, or fifteen, arriving between looks | guess when the board does not line up |
| keep going for hours unattended | invent a result it cannot read |

If the popup closes, or the game restarts, the board stops lining up with the
last look and the script **refuses to record anything** until it does. That is
deliberate: a wrong result is worse than a missing one.

### What to do the first time

Run it with **`--once`** and read the printed board against your screen *before*
you leave it alone. The script is honest about failure — it prints `?` for a
cell it could not read — but your eyes are the check that matters.

> **A note on screen-sharing.** The script only reads the screenshot for the
> three symbol colours; it stores nothing else and sends nothing anywhere. It
> also refuses to read a JPEG, because a phone photo is not a reliable source,
> whatever it looks like.

## Part 5 — Your other laptop (3 steps)

**1. Install Python** from <https://www.python.org/downloads/>
   On the **first** screen of the installer, tick **"Add python.exe to PATH"**.
   This is the one step people miss and everything depends on it.

**2. Copy `buzzcast-2.3-full.zip`** to the other laptop and unzip it anywhere,
   e.g. `C:\Projects\buzzcast_bot`

**3. Double-click `START.bat`**

Nothing else to install. No pip, no packages, no internet needed.

---

## The only number you need to remember

### Record about 300 turns before you trust any verdict. About 1,200 for a final answer.

| turns recorded | what you can conclude |
|---|---|
| 0 – 100 | **Nothing.** The app says "not enough" and it means it. |
| ~300 | A strong pattern is provable. A subtle one is not yet. |
| ~500 | Subtle patterns show up about 70% of the time. |
| ~1,200 | Trust the verdict either way — yes or no. |

**Expect the bot to say "pass" for the first 100–200 turns.** That is it working
correctly. It has no evidence yet, and guessing is what loses money.

**While recording, go small.** 150 + 150 is 300 per turn. On a 1,000 bankroll
that is 30% at risk on every turn, and in testing that has a median outcome of
about **9 coins** — even on games where the pattern is real. Keep a turn's total
in single digits as a percent of your bankroll until the Trends tab tells you the
game has memory.

---

## If something goes wrong

**A button does nothing, or the page shows a banner saying something did not start?**
Reload with **Ctrl+F5**. That forces the browser to refetch the page and its
files rather than reusing anything it held on to.

**Seeing `?` where a dash should be in the console?**
That's your Windows console's code page, not a bug. It only affects decorative
characters, never your data. To see them properly, type `chcp 65001` in the
window before running the command.

| message | fix |
|---|---|
| "Python is not installed" | You missed the PATH checkbox. Re-run the Python installer → **Modify** → tick **Add python.exe to PATH**. |
| Browser doesn't open | Type the address shown in the black window, usually `http://127.0.0.1:8077/` |
| `python` not recognised | Use `py` instead of `python`. |
| "Everything up-to-date" on push | Nothing was committed. Run `git status` to see. |

---

## What the tabs are for

| tab | one line |
|---|---|
| **Trends** | The one built for how you play — does this game have memory? |
| **Bet types** | What your split does versus the alternatives, at equal risk |
| **Overview** | How the bot is learning, and its recent results |
| **Backtest** | Bot versus you, replayed on your own recorded results |
| **Simulation lab** | Try anything against games where the truth is known |
| **History** | Undo, correct a result, export CSV |
| **Settings** | Bankroll, sessions, and the rules the bot follows |

---

## Where your data lives

`data.json` in the project folder holds everything — every turn, every bet.
It is **never** uploaded anywhere and never committed to git.

To move your sessions to another laptop, copy that one file.
