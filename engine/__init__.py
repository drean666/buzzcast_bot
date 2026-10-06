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

__version__ = "2.5.0"

from .settings import Settings, base_dir  # noqa: F401
