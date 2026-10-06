"""buzzcast_bot v2 — colour-outcome predictor + capital simulator.

Package layout
--------------
settings.py   config.json loading, defaults, validation
stats.py      distribution math (binomial tails, Beta posteriors, Wilson)
storage.py    atomic JSON persistence with backup + auto-recovery
brain.py      variable-order interpolated Markov ensemble, adaptive (Hedge)
              weighting, walk-forward honesty measurement
betting.py    bet-shape analysis, Kelly staking, EV / variance / ruin math
trust.py      the meta-learner: you-vs-bot scoreboard, trust weight,
              strategy bandit, tilt detection
game.py       GameEngine — the ledger is the single source of truth
simulate.py   headless auto-play / replay lab
"""

__version__ = "2.7.1"

from .settings import Settings, base_dir  # noqa: F401


def safe_console() -> None:
    """Never let a decorative character kill the output.

    Windows consoles are the problem: an interactive one handles Unicode, but
    a redirected or non-English one (cp850 in France, cp437, or the ascii code
    page) cannot represent an em dash, and ``print`` raises UnicodeEncodeError
    in the middle of a report. Measured: ``python analyze.py`` crashed outright
    with PYTHONIOENCODING=cp850, and ``python run.py --help`` crashed on its own
    description string.

    Only the error handler is changed, never the encoding, so output that was
    already correct is byte-for-byte identical and anything unrepresentable
    becomes a '?' instead of a traceback.
    """
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            pass

