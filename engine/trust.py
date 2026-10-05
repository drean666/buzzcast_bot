"""trust.py — the meta-learner.

The outcome brain answers "what comes next?". This module answers the second,
separate question the simulator exists for: **"who should be betting, and how?"**

It learns four things from the ledger, all recency-weighted so it adapts as
you (or the game) change:

1. **You vs the bot** — Beta posteriors over each side's hit rate, giving
   P(bot is better than you) and an explicit verdict.
2. **Decision value** — cumulative PnL of turns where you followed the bot
   versus turns where you followed yourself. Beliefs are cheap; coins aren't.
3. **Strategy bandit** — one arm per (bet shape, who you followed), scored on
   ROI with a UCB exploration bonus, so it can recommend "stop splitting,
   go single" or the reverse, based on evidence rather than vibes.
4. **Your own tells** — tilt detection (chasing losses, stake jumps) and
   per-context accuracy, e.g. "you pick well after GREEN but badly after a loss".

Everything is derived from the turn ledger, so an undo or an edited result
simply triggers ``rebuild()`` and the learner can never drift out of sync.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from . import stats


class _Arm:
    """One strategy arm: recency-weighted ROI + UCB score."""

    __slots__ = ("n", "w_n", "w_pnl", "w_stake", "pnl", "stake", "wins", "losses")

    def __init__(self) -> None:
        self.n = 0
        self.w_n = 0.0
        self.w_pnl = 0.0
        self.w_stake = 0.0
        self.pnl = 0.0
        self.stake = 0.0
        self.wins = 0
        self.losses = 0

    def add(self, pnl: float, stake: float, decay: float) -> None:
        self.w_n = self.w_n * decay + 1.0
        self.w_pnl = self.w_pnl * decay + pnl
        self.w_stake = self.w_stake * decay + stake
        self.n += 1
        self.pnl += pnl
        self.stake += stake
        if pnl > 0:
            self.wins += 1
        elif pnl < 0:
            self.losses += 1

    @property
    def roi(self) -> float:
        return self.w_pnl / self.w_stake if self.w_stake > 1e-9 else 0.0

    @property
    def roi_all(self) -> float:
        return self.pnl / self.stake if self.stake > 1e-9 else 0.0

    def ucb(self, total_plays: int, c: float) -> float:
        if self.n == 0:
            return float("inf")
        explore = c * math.sqrt(2.0 * math.log(max(total_plays, 2)) / self.n)
        return self.roi + explore * 0.1        # ROI is ~O(1), so scale the bonus


class MetaLearner:
    def __init__(self, settings):
        self.decay = float(settings.g("trust", "decay", default=0.99))
        self.margin = float(settings.g("trust", "decide_margin", default=0.75))
        self.tilt_mult = float(settings.g("trust", "tilt_multiplier", default=1.6))
        self.tilt_exp = float(settings.g("trust", "tilt_exposure_fraction", default=0.25))
        self.ucb_c = float(settings.g("trust", "ucb_c", default=1.2))
        self.symbols = settings.symbols
        self.reset()

    # ------------------------------------------------------------------ init
    def reset(self) -> None:
        # Beta posteriors (weighted hits/misses + unit prior)
        self.bot_hits = self.bot_miss = 0.0
        self.bot_c_hits = self.bot_c_miss = 0.0
        self.me_hits = self.me_miss = 0.0
        self.bot_n = self.me_n = self.bot_cn = 0
        # decision value
        self.follow_pnl: Dict[str, float] = {"bot": 0.0, "mine": 0.0, "blend": 0.0}
        self.follow_n: Dict[str, int] = {"bot": 0, "mine": 0, "blend": 0}
        self.follow_stake: Dict[str, float] = {"bot": 0.0, "mine": 0.0, "blend": 0.0}
        self.arms: Dict[str, _Arm] = {}
        self.plays = 0
        # tilt
        self.tilt_turns = 0
        self.tilt_pnl = 0.0
        self.calm_pnl = 0.0
        self.prev_stake: Optional[float] = None
        self.prev_pnl: Optional[float] = None
        # streaks
        self.streak = 0
        self.best_streak = 0
        self.worst_streak = 0
        # per-context user accuracy
        self.ctx_me: Dict[str, List[int]] = {}
        self.ctx_bot: Dict[str, List[int]] = {}
        # bankroll curve + peaks
        self.curve: List[float] = []
        self.peak = -math.inf
        self.max_dd = 0.0
        self.max_dd_frac = 0.0

    # ------------------------------------------------------------------- add
    def add(self, turn: Dict[str, Any]) -> None:
        d = self.decay
        bot = turn.get("bot") or {}
        stake = float(turn.get("stake_total") or 0.0)
        pnl = float(turn.get("pnl") or 0.0)
        result = turn.get("result")
        followed = turn.get("followed") or "mine"
        shape = turn.get("shape") or "pass"

        # ---- 1. pick accuracy: bot vs you
        bp = bot.get("top")
        if bp and result:
            hit = 1.0 if bp == result else 0.0
            self.bot_hits = self.bot_hits * d + hit
            self.bot_miss = self.bot_miss * d + (1.0 - hit)
            self.bot_n += 1
            if bot.get("committed"):
                self.bot_c_hits = self.bot_c_hits * d + hit
                self.bot_c_miss = self.bot_c_miss * d + (1.0 - hit)
                self.bot_cn += 1
        mp = turn.get("my_pick")
        if mp and result:
            hit = 1.0 if mp == result else 0.0
            self.me_hits = self.me_hits * d + hit
            self.me_miss = self.me_miss * d + (1.0 - hit)
            self.me_n += 1

        # ---- 2. decision value (coins, not beliefs)
        if followed in self.follow_pnl:
            self.follow_pnl[followed] += pnl
            self.follow_n[followed] += 1
            self.follow_stake[followed] += stake

        # ---- 3. strategy bandit
        if stake > 0:
            key = f"{shape}|{followed}"
            arm = self.arms.setdefault(key, _Arm())
            arm.add(pnl, stake, d)
            self.plays += 1

        # ---- 4. tilt
        tilted = False
        if stake > 0 and self.prev_stake and self.prev_stake > 0:
            if (self.prev_pnl or 0) < 0 and stake >= self.tilt_mult * self.prev_stake:
                tilted = True
        cap_before = float(turn.get("capital_before") or 0.0)
        if stake > 0 and cap_before > 0 and (self.prev_pnl or 0) < 0 \
                and stake / cap_before >= self.tilt_exp:
            tilted = True
        if tilted:
            self.tilt_turns += 1
            self.tilt_pnl += pnl
        elif stake > 0:
            self.calm_pnl += pnl

        if stake > 0:
            self.prev_stake, self.prev_pnl = stake, pnl

        # ---- streaks
        if stake > 0:
            if pnl > 0:
                self.streak = self.streak + 1 if self.streak > 0 else 1
                self.best_streak = max(self.best_streak, self.streak)
            elif pnl < 0:
                self.streak = self.streak - 1 if self.streak < 0 else -1
                self.worst_streak = min(self.worst_streak, self.streak)

        # ---- per-context accuracy (conditioned on the previous result)
        ctx = (turn.get("context") or [None])[-1] or "start"
        if mp and result:
            rec = self.ctx_me.setdefault(ctx, [0, 0])
            rec[0] += 1 if mp == result else 0
            rec[1] += 1
        if bp and result:
            rec = self.ctx_bot.setdefault(ctx, [0, 0])
            rec[0] += 1 if bp == result else 0
            rec[1] += 1

        # ---- bankroll curve
        cap = float(turn.get("capital_after") or 0.0)
        self.curve.append(cap)
        self.peak = max(self.peak, cap)
        dd = self.peak - cap
        if dd > self.max_dd:
            self.max_dd = dd
            self.max_dd_frac = dd / self.peak if self.peak > 0 else 0.0

    def rebuild(self, turns: Sequence[Dict[str, Any]]) -> "MetaLearner":
        self.reset()
        for t in turns:
            self.add(t)
        return self

    # --------------------------------------------------------------- report
    def trust(self) -> Dict[str, Any]:
        """P(bot's hit rate > your hit rate), with a plain-English verdict."""
        a_bot = 1.0 + self.bot_hits
        b_bot = 1.0 + self.bot_miss
        a_me = 1.0 + self.me_hits
        b_me = 1.0 + self.me_miss
        p_bot_better = stats.prob_greater_normal(a_bot, b_bot, a_me, b_me)
        bot_rate = stats.beta_mean(a_bot, b_bot)
        me_rate = stats.beta_mean(a_me, b_me)
        if self.bot_n < 5 or self.me_n < 5:
            verdict, why = "NOT ENOUGH DATA", "fewer than 5 turns with both a bot pick and your pick"
        elif p_bot_better >= self.margin:
            verdict = "TRUST THE BOT"
            why = f"bot hits {100*bot_rate:.1f}% vs your {100*me_rate:.1f}% (P={p_bot_better:.2f})"
        elif p_bot_better <= 1.0 - self.margin:
            verdict = "TRUST YOURSELF"
            why = f"you hit {100*me_rate:.1f}% vs the bot's {100*bot_rate:.1f}% (P={1-p_bot_better:.2f})"
        else:
            verdict = "TOO CLOSE TO CALL"
            why = f"bot {100*bot_rate:.1f}% vs you {100*me_rate:.1f}% — inside the noise"
        return {
            "p_bot_better": round(p_bot_better, 4),
            "trust_weight": round(p_bot_better, 4),
            "bot_hit_rate_pct": round(100 * bot_rate, 2),
            "me_hit_rate_pct": round(100 * me_rate, 2),
            "bot_turns": self.bot_n,
            "me_turns": self.me_n,
            "verdict": verdict,
            "why": why,
            "bot_ci": [round(100 * x, 1) for x in
                       stats.wilson_interval(int(round(self.bot_hits)), max(self.bot_n, 1))],
            "me_ci": [round(100 * x, 1) for x in
                      stats.wilson_interval(int(round(self.me_hits)), max(self.me_n, 1))],
            "recommendation": ("follow the bot's bet" if verdict == "TRUST THE BOT"
                               else "bet your own read" if verdict == "TRUST YOURSELF"
                               else "split the difference or stay small"),
        }

    def snapshot(self, capital: float, starting: float) -> Dict[str, Any]:
        total_plays = max(self.plays, 1)
        arms = []
        for key, arm in self.arms.items():
            shape, followed = key.split("|", 1)
            arms.append({
                "key": key, "shape": shape, "followed": followed,
                "plays": arm.n, "pnl": round(arm.pnl, 2),
                "stake": round(arm.stake, 2),
                "roi_pct": round(100 * arm.roi_all, 2),
                "roi_weighted_pct": round(100 * arm.roi, 2),
                "win_rate_pct": round(100 * arm.wins / arm.n, 2) if arm.n else 0.0,
                "ucb": round(arm.ucb(total_plays, self.ucb_c), 5),
            })
        arms.sort(key=lambda a: -a["ucb"])
        best = arms[0] if arms else None

        peak = self.peak if self.peak > -math.inf else starting
        curve = self.curve
        dd_abs, dd_frac = stats.max_drawdown([starting] + curve) if curve else (0.0, 0.0)

        ctx_rows = []
        for ctx, (h, n) in sorted(self.ctx_me.items(), key=lambda kv: -kv[1][1]):
            if n < 4:
                continue
            bh, bn = self.ctx_bot.get(ctx, (0, 0))
            ctx_rows.append({
                "after": ctx, "me_n": n, "me_hit_pct": round(100 * h / n, 1),
                "bot_n": bn, "bot_hit_pct": round(100 * bh / bn, 1) if bn else None,
                "me_p_value": round(stats.binom_test_greater(h, n, 1.0 / 3.0), 4),
            })

        invested = sum(self.follow_stake.values())
        pnl_total = sum(self.follow_pnl.values())
        return {
            "trust": self.trust(),
            "follow": {
                k: {"turns": self.follow_n[k], "pnl": round(self.follow_pnl[k], 2),
                    "stake": round(self.follow_stake[k], 2),
                    "roi_pct": round(100 * self.follow_pnl[k] / self.follow_stake[k], 2)
                    if self.follow_stake[k] > 0 else 0.0}
                for k in self.follow_pnl
            },
            "arms": arms,
            "best_arm": best,
            "tilt": {
                "turns": self.tilt_turns,
                "pnl": round(self.tilt_pnl, 2),
                "calm_pnl": round(self.calm_pnl, 2),
                "cost_of_tilt": round(self.tilt_pnl - (self.calm_pnl * self.tilt_turns /
                                                       max(self.plays - self.tilt_turns, 1)), 2)
                if self.plays > self.tilt_turns else 0.0,
            },
            "streaks": {"current": self.streak, "best": self.best_streak,
                        "worst": self.worst_streak},
            "by_context": ctx_rows,
            "risk": {
                "capital": round(capital, 2),
                "net_pnl": round(pnl_total, 2),
                "roi_pct": round(100 * pnl_total / invested, 2) if invested > 0 else 0.0,
                "return_on_start_pct": round(100 * (capital - starting) / starting, 2)
                if starting else 0.0,
                "peak": round(max(peak, starting), 2),
                "max_drawdown": round(dd_abs, 2),
                "max_drawdown_pct": round(100 * dd_frac, 2),
                "turns": len(curve),
            },
            "curve": [round(v, 2) for v in curve[-400:]],
        }
