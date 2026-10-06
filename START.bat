@echo off
REM ===================================================================
REM  buzzcast - double-click this file to start.
REM  Nothing to install except Python itself.
REM ===================================================================
setlocal
cd /d "%~dp0"
title buzzcast

REM --- find a Python interpreter -------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
  echo.
  echo   ================================================================
  echo    Python is not installed on this computer.
  echo   ================================================================
  echo.
  echo    buzzcast needs Python 3.8 or newer, and nothing else.
  echo.
  echo    1. Go to  https://www.python.org/downloads/
  echo    2. Download the latest Python for Windows and run the installer.
  echo    3. IMPORTANT: tick the box "Add python.exe to PATH" on the
  echo       first screen of the installer, before clicking Install.
  echo    4. Close this window, then double-click START.bat again.
  echo.
  pause
  exit /b 1
)

REM --- check the version is new enough -------------------------------
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>nul
if errorlevel 1 (
  echo.
  echo   Your Python is too old. buzzcast needs 3.8 or newer.
  echo   Please install a current version from python.org and try again.
  echo.
  %PY% --version
  pause
  exit /b 1
)

REM run.py finds a free port itself and opens the browser.
echo.
echo   ================================================================
echo    buzzcast is starting...
echo   ================================================================
echo.
echo    Your browser should open by itself in a second or two.
echo    If it does not, open this address yourself:
echo.
echo        http://127.0.0.1:8077/     (or the address it prints below)
echo.
echo    Keep THIS window open while you play. Closing it stops buzzcast.
echo    Press Ctrl+C in this window when you are finished.
echo.

%PY% run.py
echo.
echo   buzzcast has stopped.
pause
endlocal
