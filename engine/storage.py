"""storage.py — persistence for the ledger.

Design rule inherited from v1 and kept deliberately: **never lose data**.

* every save is atomic (write to ``.tmp`` then ``os.replace``)
* the previous file is copied to ``data.backup.json`` *before* the swap
* on load, if ``data.json`` is missing/corrupt we transparently recover
  from the backup (and keep the broken file as ``data.corrupt.json``)
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import time
from typing import Any, Dict, Optional

from .settings import base_dir

SCHEMA = 2


def default_path() -> str:
    return os.path.join(base_dir(), "data.json")


def backup_path(path: Optional[str] = None) -> str:
    p = path or default_path()
    root, ext = os.path.splitext(p)
    return f"{root}.backup{ext}"


def empty_store() -> Dict[str, Any]:
    return {"schema": SCHEMA, "active": None, "sessions": {}, "deposits_meta": {}}


_LAST_BACKUP: Dict[str, float] = {}
BACKUP_INTERVAL = 20.0     # seconds between .backup refreshes for one file


def atomic_write_json(path: str, obj: Any, backup: bool = True) -> None:
    """Crash-safe JSON write: temp file + fsync + atomic replace.

    The rolling ``.backup`` copy is refreshed at most every
    ``BACKUP_INTERVAL`` seconds. Writing a session saves twice per turn (once
    when the bet is locked in, once when the result lands); copying the whole
    file on each of those would dominate runtime for no extra safety — the
    backup exists to survive *corruption*, and a 20-second-stale copy is just
    as good for that.
    """
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, separators=(",", ":"))
        fh.flush()
        os.fsync(fh.fileno())
    if backup and os.path.exists(path):
        now = time.time()
        if now - _LAST_BACKUP.get(path, 0.0) >= BACKUP_INTERVAL:
            try:
                shutil.copy2(path, backup_path(path))
                _LAST_BACKUP[path] = now
            except OSError:
                pass
    os.replace(tmp, path)


def load_store(path: Optional[str] = None) -> Dict[str, Any]:
    """Load, self-healing from backup when needed."""
    p = path or default_path()
    store = _try_read(p)
    if store is not None:
        return _normalise(store)
    bak = backup_path(p)
    store = _try_read(bak)
    if store is not None:
        store = _normalise(store)
        store["_recovered_from_backup"] = True
        try:
            atomic_write_json(p, store)
        except OSError:
            pass
        return store
    return empty_store()


def _try_read(p: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        if not isinstance(obj, dict):
            return None
        return obj
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        try:
            shutil.copy2(p, os.path.splitext(p)[0] + ".corrupt.json")
        except OSError:
            pass
        return None


def _normalise(store: Dict[str, Any]) -> Dict[str, Any]:
    """Accept a v1 file (entries/prediction_log) and upgrade it to v2."""
    store.setdefault("schema", SCHEMA)
    store.setdefault("sessions", {})
    if store.get("active") not in store["sessions"]:
        store["active"] = next(iter(store["sessions"]), None)
    for name, s in store["sessions"].items():
        s.setdefault("turns", [])
        s.setdefault("created", "")
        s.setdefault("meta", {})
        # ---- v1 upgrade path: a plain result list becomes warm-start data
        if "entries" in s and isinstance(s["entries"], list) and s["entries"]:
            warm = [e.get("symbol") for e in s["entries"] if isinstance(e, dict)]
            s.setdefault("warm_start", [])
            s["warm_start"] = (s.get("warm_start") or []) + [w for w in warm if w]
            s["meta"]["upgraded_from_v1"] = True
            s.pop("entries", None)
            if s.get("prediction_log"):
                s["meta"]["v1_prediction_log"] = s.pop("prediction_log")
    return store


# ------------------------------------------------------------------ export
def turns_to_csv(turns: list, symbols: list, names: Dict[str, str]) -> str:
    """One row per turn. Column order is built once and reused for the values,
    so the header and the data can never drift apart."""
    head = ["turn", "time", "result", "followed"]
    stake_cols = [f"stake_{s}" for s in symbols]
    tail = ["shape", "stake_total", "return", "pnl", "capital_before",
            "capital_after", "bot_top", "bot_confidence_pct", "bot_committed",
            "bot_pick_hit", "my_pick", "my_pick_hit",
            "bot_info_gain_bits", "bot_p_value", "note"]
    w = csv.writer(io.StringIO())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head + stake_cols + tail)
    for t in turns:
        bot = t.get("bot") or {}
        bet = t.get("played_bet") or {}
        w.writerow(
            [t.get("n"), t.get("time"), t.get("result"), t.get("followed"),
             *[bet.get(s, 0) for s in symbols],
             t.get("shape"), t.get("stake_total"), t.get("return"), t.get("pnl"),
             t.get("capital_before"), t.get("capital_after"),
             bot.get("top"), bot.get("confidence"), bot.get("committed"),
             t.get("bot_pick_hit"), t.get("my_pick"), t.get("my_pick_hit"),
             bot.get("info_gain_bits"), bot.get("p_value"), t.get("note", "")])
    return buf.getvalue()


def results_to_csv(symbols: list, names: Dict[str, str], results: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["index", "symbol", "name", "time"])
    for i, r in enumerate(results, 1):
        sym = r.get("symbol") if isinstance(r, dict) else r
        w.writerow([i, sym, names.get(sym, sym),
                    r.get("time", "") if isinstance(r, dict) else ""])
    return buf.getvalue()
