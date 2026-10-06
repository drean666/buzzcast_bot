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

## Part 3 — Tell it how much money you have (4 steps, once)

The simulator starts at 1,000 coins. That is a placeholder. Until you change it,
every number on screen is advice about money you don't have.

**1.** Click the **Settings** tab
**2.** Change `capital → starting` to your real bankroll (e.g. `3000`)
**3.** Click **Save & reload**
**4.** Click **+ session** in the top right corner, name it `real`

Then, still on the Settings tab: set `default split stake` to what you actually
put on a colour (e.g. `150`). That makes the preset button match how you play.

---

## Part 4 — Play. Four clicks, forever.

| step | what to do |
|---|---|
| **1** | Look at the bot's read — optional, you can ignore it |
| **2** | Type stakes in the R / B / G boxes, or click the **150 R + 150 B** preset |
| **3** | Click **Lock in the bet** |
| **4** | When the real result happens, click **R**, **B** or **G** |

Then repeat.

- Clicked the wrong thing? **cancel this bet** — nothing was staked yet.
- Already entered a result? **History** tab → **Undo**, or **fix** on any row.
- **Follow the bot** stakes what the bot would, which is **nothing** when it says
  pass. Safe to press and find out.

---

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
