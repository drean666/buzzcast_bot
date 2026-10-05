# buzzcast_bot — Color Outcome Tracker & Predictor

You type the results of a game (`r` = red, `b` = blue, `g` = green). It saves
everything, looks for patterns, and tells you the most likely next result
**with a confidence percentage** — but only commits when it finds a *real*,
*statistically significant* edge.

Three ways to use it:
- **Click buttons** → run `gui.py` (or double-click `RUN_GUI.bat`)
- **Type in a terminal** → run `app.py` (or double-click `RUN_ME.bat`)
- **Standalone .exe** → build once, then double-click (no Python needed). See
  "Building a Windows .exe" below.

Now with a genuinely **advanced prediction engine** (`brain.py`): a
variable-order Markov ensemble with online adaptive weighting — the same
class of math behind state-of-the-art data compression, which is provably
equivalent to optimal next-symbol prediction. Plus **multiple sessions** and
**per-pattern accuracy**.

### How smart is it, really?
It reads trends of *any* length (e.g. `r,b,g,b,b,r,g,r,b`) by blending many
context lengths and trusting whichever ones actually predict well. But it is
**honest**: it measures, out-of-sample, how many *bits of real structure* it
found. On truly random data that number is ~0 and it will tell you flat-out
that no prediction is possible. It only commits when it has earned the
confidence on data it hadn't seen. No fake patterns, ever.

### It constantly learns AND adapts
- **Never forgets:** every result you enter is saved permanently in
  `data.json`, and the brain is rebuilt from your full history on every
  launch — so knowledge survives restarts and can never silently corrupt.
- **Adapts to change:** results are **recency-weighted** (`recency_decay` in
  config). If the game's behavior shifts, the brain follows the new trend
  instead of clinging to stale data.
- **Two brains:** each **session** has its own learning, AND a **master
  brain** accumulates lifetime knowledge across *all* your sessions.
- **Watch it learn:** the dashboard plots a live **learning curve** (accuracy
  + engine-edge over time) for both the current session and the master brain,
  so you can literally see the moment it discovers — or adapts to — a pattern.

Two key numbers it shows:
- **Engine edge (bits/symbol):** > 0 = real structure found; ~0 = random.
- **Out-of-sample accuracy:** how often it's right on data it didn't train on
  (compare to the 33.3% chance baseline).

---

## ⚠️ Read this first (the honest truth)

If the game's results come from a **fair, truly random** source (a real
roulette wheel, a licensed RNG), then **nothing can predict the next result.**
Each spin is independent. This tool is built to be honest:

- If your data looks **random**, it says so and **refuses** to predict.
- It only commits when the edge passes a **statistical significance test**
  (p-value < 0.05), not just a high percentage.
- The **Backtest** replays your whole history to show whether following its
  committed predictions would actually beat the 33.3% chance baseline.

Use it to *study* a game and *track your own results*. Don't bet money you
can't afford to lose.

---

## ✅ What you need

- **Python 3** (3.8+). Check with `python --version`.
  Get it at https://www.python.org/downloads/ — tick **"Add Python to PATH"**.
- Nothing else. No `pip install` needed. (The graphical version uses
  `tkinter`, which ships with Python on Windows/macOS. On some Linux: 
  `sudo apt-get install python3-tk`.)

---

## ▶️ How to run

**Graphical (clickable buttons) — easiest:**
- Double-click **`RUN_GUI.bat`**, or run `python gui.py`.
- Click R / B / G (or press those keys). Backspace = undo.

**Console (type letters):**
- Double-click **`RUN_ME.bat`**, or:
  ```
  cd C:\Users\besta\Desktop\buzzcast_bot
  python app.py
  ```

> The old `pip install -r requirements.txt` error is gone: the file exists and
> needs nothing. You can skip pip entirely.

---

## ⌨️ Console commands

| Type | Meaning |
|------|---------|
| `r` `b` `g` | Record RED / BLUE / GREEN |
| `u` | Undo last entry (repeat to undo several) |
| `i` | **Import** many results at once (paste text or a file path) |
| `e` | **Edit/delete** a past entry by its number |
| `s` | Show full stats |
| `t` | **Backtest** the active session (honest accuracy proof) |
| `p` | **Per-pattern accuracy** (best & worst patterns) |
| `c` | Export the active session to **CSV** (opens in Excel) |
| `d` | Build the **HTML dashboard** and open it in your browser |
| `n` | **New** session |
| `w` | **Switch** session |
| `l` | **List** sessions |
| `h` | Help |
| `q` | Quit |

The GUI has a **session dropdown + "New"** button at the top, plus buttons for
**Undo**, **Import**, **Edit**, **Patterns**, **Export CSV**, and **Dashboard**.

### Bulk import & editing
- **Import** lets you paste a whole run of results at once — e.g. `rbgbbrgr`,
  `r,b,g,b`, or even full names like `RED BLUE GREEN`. It also loads `.txt`/
  `.csv` files (including CSVs this tool exported). Junk characters are
  skipped and reported, so you always know exactly what was added.
- **Edit** lets you fix or delete *any* past entry by its number, not just the
  last one.

---

## 🗂️ Sessions

Each session is an independent set of results — use one per game table or
sitting, so old data never mixes with new. Switch any time; everything is
saved per session. (Your very first old single-session file, if any, is
safely archived as `history.archived.json` — never deleted.)

## 🧩 Per-pattern accuracy

The tool measures how reliable each short pattern (e.g. "after RED,RED") has
been in *your* data. Patterns that predict well are **trusted more**; weak ones
are **trusted less** — so it gets smarter the more you feed it. Press `p`
(console) or click **Patterns** (GUI) to see the best/worst lists.

---

## 🪟 Building a Windows .exe (no Python needed to run it)

**Option A — build on your own Windows PC (easiest):**
1. Double-click **`build_exe.bat`**.
2. Wait ~1 minute. Your program appears at **`dist\buzzcast_bot.exe`**.
3. Copy that single file anywhere and double-click it. No Python required.

**Option B — let GitHub build it for free (no setup on your PC):**
1. Put this folder in a GitHub repository (push it to `main`).
2. The included workflow `.github/workflows/build-exe.yml` runs automatically
   (or click **Actions → Build Windows EXE → Run workflow**).
3. When it finishes, open the run and download the
   **`buzzcast_bot-windows`** artifact — it contains `buzzcast_bot.exe`
   (the GUI) and `buzzcast_bot_console.exe` (the typing version).

Note: the .exe keeps its data (`data.json`) in the same folder as the .exe,
so keep them together.

---

## 📊 The dashboard

Pressing `d` (console) or clicking **Dashboard** (GUI) creates
`dashboard.html` — a visual page with the color distribution chart, backtest
results, live track record, per-pattern accuracy, a timeline strip, and **two
live learning-curve charts** (this session + the lifetime master brain) so you
can watch the engine learn and adapt over time. It's fully offline, just opens
in your browser.

---

## 💾 Your data & safety

- Saved automatically to `history.json`.
- A backup (`history.backup.json`) is kept before every save — if the main
  file ever gets corrupted, it auto-recovers from the backup.
- To start fresh, delete `history.json` (and the backup).

---

## ⚙️ Tuning (no coding needed)

Edit **`config.json`**:
- `min_data_before_analysis` — results needed before analysis (default 15).
- `confidence_threshold_percent` — how sure before committing (default 55).
- `recent_window` — how many recent results count as "hot" (default 20).
- `max_context_order` — how long a trend the smart engine can model (default 5).
  Higher = can catch longer patterns, but needs more data to be reliable.
- `min_info_gain_bits` — how much real structure is required before it will
  predict (default 0.03). Raise it to be even more skeptical.
- `recency_decay` — how fast it ADAPTS to change (default 0.997).
  `1.0` = never forget (all history equal); lower = adapts faster to recent
  results (e.g. `0.98` reacts quickly, `0.999` reacts slowly). This is the
  "learn and adapt" dial.
- `symbols` / `symbol_names` — rename colors or change the set entirely.

Changes apply next time you start the program.

---

## 🧪 Testing

Run `python tests.py` — it checks the math, storage, backups, and backtest.
You should see `ALL TESTS PASSED`.

---

## 📁 Files

| File | Purpose |
|------|---------|
| `gui.py` | Clickable graphical app (with sessions) |
| `app.py` | Console app (with sessions) |
| `brain.py` | Advanced engine: variable-order Markov + adaptive ensemble |
| `predictor.py` | Orchestrates the brain, honesty gate, significance test, backtest |
| `patterns.py` | Per-pattern accuracy tracking |
| `storage.py` | Save/load, sessions, auto-backup, CSV export |
| `dashboard.py` | Builds the HTML dashboard |
| `settings.py` | Reads config.json |
| `paths.py` | Finds files correctly whether run as script or .exe |
| `config.json` | Your tunable settings |
| `importer.py` | Parses pasted text / files into clean results (bulk import) |
| `tests.py` | Automated tests (59 checks) |
| `RUN_GUI.bat` / `RUN_ME.bat` | Windows launchers |
| `build_exe.bat` | Builds the standalone .exe locally |
| `.github/workflows/build-exe.yml` | Cloud .exe builder |
| `requirements.txt` | Empty (no installs needed to run) |
| `data.json` | Auto-created: all your sessions' data |

Stay honest with yourself about randomness. 🎲
