#!/usr/bin/env bash
# buzzcast — start script for macOS and Linux.  Usage:  ./start.sh
set -e
cd "$(dirname "$0")"
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo
  echo "  Python 3.8+ is required and was not found."
  echo "  Install it, then run this script again:"
  echo "     macOS:  brew install python3     (or python.org/downloads)"
  echo "     Linux:  sudo apt install python3"
  echo
  exit 1
fi
echo "Starting buzzcast with $PY ..."
exec "$PY" run.py "$@"
