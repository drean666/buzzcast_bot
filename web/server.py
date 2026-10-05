"""server.py — the local web UI (stdlib only, no CDN, no external assets).

Bind is ``0.0.0.0`` so the app is reachable from the sandbox preview proxy as
well as from your own machine. Everything the browser needs is served from
``web/static``; there are no outbound requests, so the whole app works offline.

Endpoints
    GET  /api/state            full UI payload (plan, capital, curves, trust)
    POST /api/bet              lock in a bet (yours / the bot's / a blend)
    POST /api/pass             sit the turn out (result is still recorded)
    POST /api/resolve          enter the real result, learn, settle
    POST /api/undo             remove the last N turns and re-derive everything
    POST /api/edit             correct a past turn's result
    POST /api/deposit          rebuy / withdraw
    POST /api/session          new / switch / delete / seed-from-archive
    POST /api/sim              one headless simulation
    POST /api/grid             the full source x policy grid
    POST /api/config           patch settings (hot-reloaded into the engine)
    GET  /api/export?what=turns|results   CSV download
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine import simulate                     # noqa: E402
from engine.game import GameEngine              # noqa: E402
from engine.settings import Settings            # noqa: E402

STATIC = os.path.join(_HERE, "static")
MIME = {".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
        ".json": "application/json; charset=utf-8",
        ".ico": "image/x-icon",
        ".png": "image/png"}


class App:
    """Owns the single GameEngine and serialises access to it."""

    def __init__(self, settings: Optional[Settings] = None,
                 path: Optional[str] = None):
        self.lock = threading.RLock()
        self.settings = settings or Settings.load()
        self.engine = GameEngine(self.settings, path=path)

    def rebuild_engine(self) -> None:
        self.engine = GameEngine(self.settings, path=self.engine.path)


APP: Optional[App] = None


# --------------------------------------------------------------------- routes
def api_state(app: App, q: Dict[str, Any]) -> Dict[str, Any]:
    include = q.get("include", ["lab", "patterns", "backtest"])
    if isinstance(include, str):
        include = [x for x in include.split(",") if x]
    with app.lock:
        return app.engine.state(include=include)


def api_bet(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        stakes = body.get("stakes") or {}
        stakes = {k: float(v or 0) for k, v in stakes.items()}
        e = app.engine
        pend = e.place_bet(stakes, follow=body.get("follow", "mine"),
                           note=body.get("note", ""))
        return {"ok": True, "pending": pend, "state": e.state(include=())}


def api_pass(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        e = app.engine
        e.pass_turn(note=body.get("note", "passed"))
        return {"ok": True, "pending": e.session["pending"], "state": e.state(include=())}


def api_cancel(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        out = app.engine.cancel_pending()
        out["ok"] = True
        out["state"] = app.engine.state(include=())
        return out


def api_resolve(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        e = app.engine
        turn = e.resolve(str(body.get("result", "")).lower())
        return {"ok": True, "turn": GameEngine._slim(turn),
                "state": e.state(include=("lab", "patterns", "backtest"))}


def api_undo(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        out = app.engine.undo(int(body.get("n", 1) or 1))
        out["state"] = app.engine.state()
        return out


def api_edit(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        t = app.engine.edit_result(int(body["turn"]), str(body["result"]).lower())
        return {"ok": True, "turn": GameEngine._slim(t), "state": app.engine.state()}


def api_deposit(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        out = app.engine.deposit(float(body["amount"]), body.get("note", "rebuy"))
        out["state"] = app.engine.state(include=())
        return out


def api_session(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    action = body.get("action", "list")
    with app.lock:
        e = app.engine
        if action == "new":
            name = e.new_session(body.get("name") or None,
                                 starting=body.get("starting"),
                                 warm_start=body.get("warm_start"))
            return {"ok": True, "name": name, "state": e.state()}
        if action == "switch":
            e.switch(body["name"])
            return {"ok": True, "state": e.state()}
        if action == "delete":
            e.delete_session(body["name"])
            return {"ok": True, "state": e.state()}
        if action == "seed_archive":
            # Load the 70 recorded results as an OPTIONAL warm start. It seeds
            # the model's priors; the capital ledger still starts at turn 1.
            import archive_old_history
            seq = archive_old_history.load()
            e.session["warm_start"] = list(seq)
            e.rebuild()
            e.save()
            return {"ok": True, "seeded": len(seq), "state": e.state()}
        return {"ok": True, "sessions": e.list_sessions()}


def api_sim(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        s = app.settings
        e = app.engine
        hist = e.results()
        probs = body.get("probs")
        if probs:
            tot = sum(float(v) for v in probs.values()) or 1.0
            probs = {k: float(v) / tot for k, v in probs.items()}
        out = simulate.run(
            source_kind=body.get("source", "fair"),
            policy_name=body.get("policy", "bot"),
            turns=int(body.get("turns", 500)),
            settings=s,
            start_capital=float(body.get("start_capital") or e.capital or 1000),
            seed=int(body.get("seed", 1)),
            opts={"stake": float(body.get("stake") or 120),
                  "split_pair": body.get("split_pair"),
                  "colour": body.get("colour"),
                  "mirror_bets": body.get("mirror_bets")},
            history=hist, probs=probs,
        )
        return {"ok": True, "result": out}


def api_grid(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        s = app.settings
        e = app.engine
        out = simulate.compare(
            sources=body.get("sources") or ["fair", "biased", "markov", "markov_strong"],
            policies=body.get("policies") or ["bot", "bot_loose", "split_two",
                                              "always_top", "fixed_colour", "martingale"],
            turns=int(body.get("turns", 500)),
            settings=s,
            seeds=body.get("seeds") or [1, 2],
            start_capital=float(body.get("start_capital") or 1000),
            opts={"stake": float(body.get("stake") or 120),
                  "split_pair": body.get("split_pair")},
            history=e.results(),
        )
        # the grid is big; the UI only needs the summary + a few curves
        curves = {f"{g['source']}|{g['policy']}|{g['seed']}":
                  g.get("curve", [])[:240] for g in out["grid"]}
        out["curves"] = curves
        out.pop("grid", None)
        return {"ok": True, "result": out}


def api_autoplay(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    """Fast-forward the LIVE ledger using a synthetic result source.

    Same engine, same ledger, same learning — just without you typing each
    result in. Useful for seeing how the bot behaves over a long session.
    """
    with app.lock:
        e = app.engine
        turns = int(body.get("turns", 60))
        src = simulate.make_source(body.get("source", "biased"),
                                   e.symbols, seed=body.get("seed"))
        e.autosave = False
        placed = 0
        try:
            for _ in range(turns):
                pred = e.plan()
                if body.get("follow") == "bot" and pred.get("committed"):
                    e.place_bet(None, follow="bot")
                    placed += 1
                elif body.get("follow") == "bot":
                    e.pass_turn()
                else:
                    stakes = body.get("stakes") or {}
                    if sum(float(v) for v in stakes.values()) > e.capital:
                        e.pass_turn(note="auto: not enough capital")
                    else:
                        e.place_bet(stakes, follow="mine")
                        placed += 1
                e.resolve(src.next())
        finally:
            e.autosave = True
        e.flush()
        return {"ok": True, "played": turns, "staked_turns": placed,
                "state": e.state()}


def api_config(app: App, body: Dict[str, Any]) -> Dict[str, Any]:
    with app.lock:
        if body.get("patch"):
            app.settings.patch(body["patch"])
            app.settings.save()
            app.rebuild_engine()
        return {"ok": True, "config": app.settings.data,
                "state": app.engine.state(include=())}


def api_export(app: App, q: Dict[str, Any]) -> tuple:
    with app.lock:
        what = (q.get("what") or ["turns"])[0]
        if what == "results":
            csv_text = app.engine.export_results_csv()
            fname = "buzzcast_results.csv"
        else:
            csv_text = app.engine.export_csv()
            fname = "buzzcast_turns.csv"
    return csv_text, fname


# --------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    server_version = "buzzcast/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # quieter console
        if os.environ.get("BUZZCAST_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers
    def _send(self, code: int, body: bytes, ctype: str,
              extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400) -> None:
        self._json({"ok": False, "error": msg}, code)

    def _body(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))

    # -- verbs
    def do_GET(self) -> None:                                   # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not u.path.startswith("/api/"):
            return self._static(u.path)
        try:
            if u.path == "/api/state":
                return self._json(api_state(APP, q))
            if u.path == "/api/export":
                text, fname = api_export(APP, q)
                return self._send(200, text.encode("utf-8"), "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{fname}"'})
            if u.path == "/api/config":
                return self._json({"config": APP.settings.data})
            if u.path == "/api/sessions":
                return self._json({"sessions": APP.engine.list_sessions()})
            if u.path == "/api/health":
                return self._json({"ok": True, "version": _version()})
            return self._err(f"no such endpoint {u.path}", 404)
        except Exception as exc:                                # noqa: BLE001
            traceback.print_exc()
            return self._err(f"{type(exc).__name__}: {exc}", 500)

    def do_HEAD(self) -> None:                                  # noqa: N802
        return self.do_GET()

    def do_POST(self) -> None:                                  # noqa: N802
        u = urlparse(self.path)
        body = self._body()
        routes = {
            "/api/bet": api_bet, "/api/pass": api_pass,
            "/api/cancel": api_cancel,
            "/api/resolve": api_resolve, "/api/undo": api_undo,
            "/api/edit": api_edit, "/api/deposit": api_deposit,
            "/api/session": api_session, "/api/sim": api_sim,
            "/api/grid": api_grid, "/api/autoplay": api_autoplay,
            "/api/config": api_config,
        }
        fn = routes.get(u.path)
        if not fn:
            return self._err(f"no such endpoint {u.path}", 404)
        try:
            return self._json(fn(APP, body))
        except (ValueError, KeyError) as exc:
            return self._err(str(exc), 400)
        except Exception as exc:                                # noqa: BLE001
            traceback.print_exc()
            return self._err(f"{type(exc).__name__}: {exc}", 500)


def _version() -> str:
    try:
        from engine import __version__
        return __version__
    except Exception:                                           # noqa: BLE001
        return "?"


def serve(host: Optional[str] = None, port: Optional[int] = None,
          settings: Optional[Settings] = None, path: Optional[str] = None) -> None:
    global APP
    s = settings or Settings.load()
    APP = App(s, path=path)
    host = host or str(s.g("ui", "host", default="0.0.0.0"))
    port = int(port or s.g("ui", "port", default=8077))
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"buzzcast {_version()}  ->  http://{host}:{port}/")
    print(f"data file: {APP.engine.path}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
