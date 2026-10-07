# Recording and playing — the simple version

One page. Read it once.

---

## What the three pieces are

```
   ┌─────────────────┐         ┌──────────────────┐        ┌─────────────────┐
   │  THE GAME       │  read   │  THE WATCHER     │  tell  │  BUZZCAST       │
   │  in an emulator │ ──────► │  capture.py      │ ─────► │  the app in     │
   │  (BlueStacks)   │         │  looks at the    │        │  your browser   │
   │                 │         │  Trend popup     │        │                 │
   └─────────────────┘         └──────────────────┘        └─────────────────┘
        you play                  runs by itself              remembers
                                                                  everything
```

- **The game** runs in the emulator on your laptop.
- **The watcher** takes a picture of the emulator every 15 seconds, finds the
  Trend popup, reads the coloured faces across the 5 rows, and works out which
  results are new since last time.
- **Buzzcast** is where the results end up, and where the bot learns from them.

That is the whole mechanism. There is no screen recording and no timing to get
right, because the Trend popup already shows the **last 50 results** — so any
picture of it contains the whole recent history.

---

## What records what, and when

| situation | how results get in |
|---|---|
| **No emulator yet** | By hand: one tap per round on the colour that came up. Works fine, just slower. |
| **Emulator + watcher** | Automatically. You do nothing except play. |

Both go to the same place, so you can start by hand today and switch to the
watcher later without losing anything.

**Every result the watcher records is a PASS.** It never places a bet, so your
bankroll does not move while it works. Its whole job is to gather evidence.

---

## The one thing you must do

**Leave the game's Trend popup open in the emulator.**

That popup is the board the watcher reads. If it is closed, the watcher says
`no board visible yet` and waits — it will not guess.

Test it once: open the Trend popup, leave it open for three or four rounds, and
watch whether the newest cell (marked NEW, bottom right) keeps updating. If it
does, you are set. If the popup closes itself, reopen it every so often, or fall
back to recording by hand — either works.

---

## Getting set up (once)

**1. Install BlueStacks** (or LDPlayer, or MuMu) and install the game in it.

**2. Turn on ADB in the emulator.** BlueStacks: Settings → Advanced → Android
Debug Bridge → on.

**3. Check Python can see it.** In the project folder:

```powershell
python capture.py --adb --once --report
```

It should print the board as letters. **Compare them with your screen**, left to
right, top to bottom. If they match, you are ready. (`--once --report` is a
look-only check: it records nothing at all, so you can run it any time.)

If it says it cannot find adb, tell it where it is:

```powershell
python capture.py --adb --once --report --adb-path "C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
```

If that works, put the same path into `WATCH.bat` (there is a note at the bottom
of the file showing exactly where).

---

## Every session afterwards (three steps)

**1. Start the emulator and open the game.** Open the Trend popup.

**2. Double-click `WATCH.bat`.**

That starts buzzcast and the watcher together. The app opens in your browser;
the watcher runs in the black window.

**3. Play.**

The watcher records everything as you go. Leave it running. When you want to
stop, press **Ctrl+C** in the watcher window, then close the app window.

> The first time you run it, the watcher records **the 50 results already on the
> board** — real results you had not recorded, so you start with fifty turns of
> evidence instead of zero. (If you had already entered them by hand, add
> `--no-initial` to `WATCH.bat` so they do not land twice.)

---

## How long to record, and when to play

The strip across the top of the game screen tells you. Four stages:

| the strip says | what it means | what you do |
|---|---|---|
| **1 · warming up** | fewer than 15 results seen | record only |
| **2 · earning its trust** | the bot has opinions, none proven | record only |
| **3 · close, not proven** | its paper trade is positive but not proven | keep recording |
| **4 · the bot has a proven edge** | its record is statistically significant | **now you may play** |

**Target: 200–300 turns.** At 30–60 seconds a round that is a few hours of
playing, spread over as many sessions as you like. The ledger adds up.

**When stage 4 appears:** press **T** on the game screen to switch from
recording-only to staking, and follow the bot's read. Before that, keep your
money in your pocket.

**If you reach 500 turns and the strip is still at stage 2, the game is probably
fair** — there is no pattern to find. That is a useful answer, and it cost you
nothing to learn.

---

## Reading the strip while you record

```
stage 2 of 4 · earning its trust          bot's read, last 40 turns   bot's paper trade
Record only. Every round is evidence.     38% right                   +4.2% over 120 turns
                                          chance is 33%                p = 0.31 — not proven
```

- **The read** is how often the bot's favourite actually came up. Chance is 33%.
  On a game with a real edge this climbs past 40%. On a fair game it sits at
  32–35% forever.
- **The paper trade** is the stricter test, and it is what decides whether the
  bot is allowed to stake. It needs more data than the read.

Watch the read first. It answers "is there anything here?" long before the
formal test can.

---

## If something goes wrong

| what you see | what it means |
|---|---|
| `cannot find adb` | The emulator is not running, or ADB is off, or adb is not on PATH. See step 3 above. |
| `no board visible yet` | The Trend popup is closed. Open it. |
| `the board does not line up` | The popup was closed and reopened, or the game restarted. The watcher refuses to guess and waits for two looks that agree. |
| `the buzzcast app is NOT running` | The app window got closed. Reopen `START.bat`; the watcher holds the results and records them as soon as it is back. |
| A `?` where a colour should be | One cell it could not read. It will resolve on the next look; if it does not, send me a PNG screenshot. |
| The letters do not match your screen | Stop and tell me. Do not leave it recording wrong results. |

The watcher keeps a log in `capture_log.txt` and remembers where it got to in
`capture_config.json`. You can stop and restart it as often as you like — it
picks up where it left off.

---

## The short version, printed and stuck to the wall

```
1.  Emulator + game open.  TREND POPUP OPEN.
2.  Double-click WATCH.bat
3.  Play.
4.  Watch the strip say "stage 4 - proven edge".
5.  Then press T and let the bot bet.
    If 500 turns go by and it never says stage 4, there is nothing there.
```
