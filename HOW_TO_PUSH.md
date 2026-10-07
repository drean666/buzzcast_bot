# How to commit and push

Everything here is PowerShell, run from your project folder on Windows.
Copy one block at a time.

---

## The whole thing, start to finish

### 0. Close the app if it is running

Press **Ctrl+C** in the window running buzzcast (or just close it). Windows
locks some files while Python is using them.

### 1. Put the new files in place

Download `buzzcast-2.10.0-full.zip` from the workspace, then:

```powershell
cd C:\Users\besta\Projects\buzzcast_bot

Expand-Archive -Path "$env:USERPROFILE\Downloads\buzzcast-2.10.0-full.zip" `
  -DestinationPath . -Force
```

The zip has no wrapper folder, so this drops the files straight into your
project folder and overwrites what is there. Nothing of yours is touched:
`data.json` (your ledger), `capture_config.json` and `capture_log.txt` are not
in the zip and are ignored by git.

### 2. Prove it works before committing anything

```powershell
python tests.py
```

Expect:

```
64/64 passed
all good
```

If it is not 64/64, **stop** and send me the output. Do not commit a red suite.

### 3. Commit

```powershell
git add -A

git commit -m "2.8.1-2.10: fix the dead Table view button, live read accuracy, capture.py" `
  -m "2.8.1: #btn-copy-bot is only rendered when the bot proposes a bet, so on a fresh session the unguarded $('#btn-copy-bot').onclick threw inside wire() and aborted every wiring step after it, including wireTable() - the Table view button had no handler at all. Guarded, and each wiring step is now independently guarded so one bad element costs one section, not the interface." `
  -m "2.9: brain.summary reports read_hit_rate_pct - the share of the last 40 turns where the model's favourite actually came up. The game screen shows it, so 'when should I expect predictions' has an answer while you play: by turn 50-100 on a strong edge, 200-300 on a thin one, never on a fair game." `
  -m "2.10: capture.py reads the game's Trend board (last 50 results, 5x10) from an emulator screenshot and records them as passes. Stdlib-only PNG/BMP/adb-screencap decoders. Reads 50/50 on a photo of the real game, verified against a visual transcription." `
  -m "Also: devtools/windows_check.py runs the suite with Windows' cp1252 default so this class of bug is caught here rather than on your machine. 64 tests."
```

### 4. Push

```powershell
git push
```

### 5. Confirm it landed

```powershell
git log --oneline -3
git status
```

`git status` must say **"nothing to commit, working tree clean"**. The top line
of `git log` should be your new commit.

---

## Short version, once you have done it a few times

```powershell
cd C:\Users\besta\Projects\buzzcast_bot
Expand-Archive -Path "$env:USERPROFILE\Downloads\buzzcast-2.10.0-full.zip" -DestinationPath . -Force
python tests.py
git add -A
git commit -m "2.8.1-2.10: table view fix, live read, capture.py"
git push
git log --oneline -3
```

---

## Things that go wrong, and what they mean

**`Author identity unknown`**
Your git identity is not set on this machine. Once per machine:

```powershell
git config --global user.email "180277474+drean666@users.noreply.github.com"
git config --global user.name "drean666"
```

**It asks for a password when pushing**
GitHub does not accept account passwords. You need a Personal Access Token:

1. github.com → your picture → Settings → Developer settings →
   Personal access tokens → Tokens (classic) → Generate new token
2. Tick **repo**, set an expiry, generate, and copy it.
3. Paste it as the password. Your username is `drean666`.

If it keeps using the wrong account, clear the cached one:

```powershell
cmdkey /delete:git:https://github.com
```

**`nothing to commit, working tree clean` straight after unzipping**
The unzip did not reach the right folder. Check:

```powershell
dir
```

You should see `capture.py`, `tests.py`, `engine`, `web`, `analyze.py`. If you
see another `buzzcast_bot` folder inside this one, the zip had a wrapper - move
the contents up one level, or re-run the Expand-Archive command above (it has
no wrapper, so this should not happen).

**`Everything up-to-date` after committing**
The commit did not happen. Run `git log --oneline -3` - if your message is not
at the top, the commit failed. `git status` will tell you why.

**The tests pass here but something is broken on the screen**
Hard-refresh the browser with **Ctrl+F5**. The app sends `no-store` on every
file, so a normal reload should be enough, but Ctrl+F5 forces it.

**Line-ending warnings on `git add`**
Harmless. `.gitattributes` pins the two that matter (`start.sh` keeps LF so it
works off Windows, `START.bat` keeps CRLF for cmd.exe).

---

## What should be true after a good push

| | |
|---|---|
| `python tests.py` | 64/64 passed |
| `git status` | nothing to commit, working tree clean |
| GitHub top commit | your new message |
| `engine/__init__.py` on GitHub | `__version__ = "2.10.0"` |

If all four hold, GitHub and your laptop are identical, and nothing further is
needed until you have recorded a few hundred turns.
