@echo off
REM ===================================================================
REM  buzzcast - WATCH MODE
REM
REM  Starts BOTH halves:
REM    1. the buzzcast app, in its own window  (where results are kept)
REM    2. the watcher, in THIS window          (reads your game screen)
REM
REM  Use this instead of START.bat when you want the game recorded
REM  automatically from an emulator instead of tapping each result by hand.
REM ===================================================================
setlocal
cd /d "%~dp0"
title buzzcast - watching your game

REM --- find a Python interpreter -------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
  echo.
  echo   Python is not installed on this computer.
  echo   See QUICKSTART.md Part 1, step 1.
  echo.
  pause
  exit /b 1
)

REM --- 1. the app, in its own window ---------------------------------
echo.
echo   Starting the buzzcast app...
start "buzzcast app" cmd /k "%PY% run.py"

REM give it a moment to bind a port before the watcher looks for it
timeout /t 4 /nobreak >nul

REM --- 2. the watcher, here ------------------------------------------
echo.
echo   ================================================================
echo    Now watching your game.
echo   ================================================================
echo.
echo    Leave the game's TREND popup OPEN in your emulator - that is
echo    the board the watcher reads. New results are recorded as passes,
echo    so your bankroll never moves.
echo.
echo    Press Ctrl+C in THIS window to stop watching.
echo    The app window keeps running; close it when you have finished.
echo.

REM --adb is the emulator path. If adb is not on PATH, add:
REM     --adb-path "C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
%PY% capture.py --adb --watch --interval 15

echo.
echo   Stopped watching. Your results are saved.
echo   The app is still open in the other window - close it when ready.
echo.
pause
endlocal
