"""archive_old_history.py — optional access to the 70 results from the lost v1 run.

Kept deliberately separate from the engine and **never auto-loaded**. The old
run has no capital ledger, no stake record and no timestamps on the bets, so
it cannot be merged into a money simulation — but it *can* seed the model's
priors, which is a legitimate head start as long as it is clearly labelled.

Nothing else in the program imports this unless you press "Seed from archive"
in the UI or run ``python3 console.py seed``.
"""
from __future__ import annotations

import json
import os
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "archive", "old_history.json")


def load() -> List[str]:
    """Return the archived results as a flat symbol sequence (may be empty)."""
    if not os.path.isfile(ARCHIVE):
        return []
    with open(ARCHIVE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    sessions = data.get("sessions") or {}
    out: List[str] = []
    for sess in sessions.values():
        for entry in sess.get("entries") or []:
            if isinstance(entry, dict):
                sym = entry.get("result") or entry.get("symbol") or entry.get("value")
                if sym:
                    out.append(str(sym).lower())
            elif isinstance(entry, str):
                out.append(entry.lower())
        # some v1 exports stored the run as one string
        run = sess.get("results")
        if isinstance(run, str):
            out.extend(list(run.lower()))
    return [s for s in out if s.isalpha()]


if __name__ == "__main__":
    seq = load()
    print(f"{len(seq)} archived results")
    print("".join(seq))
