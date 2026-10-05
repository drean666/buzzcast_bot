"""run.py — start the web app (this is the normal entry point).

    python3 run.py                 # http://0.0.0.0:8077
    python3 run.py --port 9000
    python3 run.py --data my.json
    python3 run.py --no-browser
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from engine.settings import Settings          # noqa: E402
from web.server import serve                  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="buzzcast — capital simulator")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--data", default=None, help="path to the session ledger")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    s = Settings.load()
    host = args.host or str(s.g("ui", "host", default="0.0.0.0"))
    port = args.port or int(s.g("ui", "port", default=8077))

    if not args.no_browser:
        url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    serve(host=host, port=port, settings=s, path=args.data)


if __name__ == "__main__":
    main()
