"""game.py — GameEngine: the capital simulator's turn loop and state.

**The ledger is the single source of truth.** Capital, the brain, the
meta-learner, every curve and every scoreboard number are *derived* from the
list of turns. That buys three things for free:

* ``undo`` and ``edit_result`` are trivially safe — delete/amend rows, re-derive
* a crash mid-turn cannot leave inconsistent money behind
* the model is rebuilt from your full history, so it can never silently rot

Turn lifecycle::

    phase=await_bet --place_bet()/pass_turn()--> phase=await_result
                    --resolve(symbol)----------> turn appended, phase=await_bet
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import betting, stats, storage
from .brain import Brain
from .settings import Settings
from .trust import MetaLearner


def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class GameEngine:
    def __init__(self, settings: Optional[Settings] = None,
                 path: Optional[str] = None, autosave: bool = True):
        self.settings = settings or Settings.load()
        self.path = path or storage.default_path()
        self.autosave = autosave
        self._dirty = False
        self.store = storage.load_store(self.path)
        self.brain = Brain(self.settings)
        self.meta = MetaLearner(self.settings)
        self.symbols = self.settings.symbols
        self.payouts = self.settings.payouts
        if not self.store.get("sessions"):
            self.new_session("session-1", save=False)
        elif not self.store.get("active"):
            self.store["active"] = next(iter(self.store["sessions"]))
        self.rebuild()

    # ------------------------------------------------------------ sessions
    @property
    def session(self) -> Dict[str, Any]:
        return self.store["sessions"][self.store["active"]]

    @property
    def name(self) -> str:
        return self.store["active"]

    def new_session(self, name: Optional[str] = None, save: bool = True,
                    starting: Optional[float] = None,
                    warm_start: Optional[Sequence[str]] = None) -> str:
        base = name or f"session-{len(self.store['sessions']) + 1}"
        name = base
        i = 2
        while name in self.store["sessions"]:
            name = f"{base}-{i}"
            i += 1
        self.store["sessions"][name] = {
            "name": name,
            "created": now_iso(),
            "starting_capital": float(starting if starting is not None
                                      else self.settings.g("capital", "starting", default=1000)),
            "warm_start": [s for s in (warm_start or []) if s in self.symbols],
            "turns": [],
            "deposits": [],
            "pending": None,
            "meta": {},
        }
        self.store["active"] = name
        self.rebuild()
        if save:
            self.save()
        return name

    def switch(self, name: str) -> None:
        if name not in self.store["sessions"]:
            raise KeyError(f"no session called {name!r}")
        self.store["active"] = name
        self.rebuild()
        self.save()

    def delete_session(self, name: str) -> None:
        if name not in self.store["sessions"]:
            return
        if len(self.store["sessions"]) == 1:
            raise ValueError("cannot delete the only session")
        del self.store["sessions"][name]
        if self.store["active"] == name:
            self.store["active"] = next(iter(self.store["sessions"]))
        self.rebuild()
        self.save()

    def list_sessions(self) -> List[Dict[str, Any]]:
        out = []
        for n, s in self.store["sessions"].items():
            turns = s.get("turns", [])
            cap = self._capital_of(s)
            out.append({"name": n, "turns": len(turns), "capital": round(cap, 2),
                        "results": len(s.get("warm_start", [])) + len(turns),
                        "active": n == self.store["active"],
                        "created": s.get("created", "")})
        return out

    # -------------------------------------------------------------- derive
    def _capital_of(self, s: Dict[str, Any]) -> float:
        c = float(s.get("starting_capital", 0))
        c += sum(float(d.get("amount", 0)) for d in s.get("deposits", []))
        c += sum(float(t.get("pnl", 0) or 0) for t in s.get("turns", []))
        return c

    def results(self) -> List[str]:
        s = self.session
        return list(s.get("warm_start", [])) + [t["result"] for t in s.get("turns", [])
                                               if t.get("result")]

    def rebuild(self) -> None:
        """Re-derive the brain, the meta-learner and capital from the ledger."""
        self.brain.fit(self.results())
        self.meta.rebuild(self.session.get("turns", []))
        self.capital = self._capital_of(self.session)
        w = len(self.session.get("warm_start", []))
        self.curve = [float(self.session.get("starting_capital", 0))] + \
            [float(t.get("capital_after", 0)) for t in self.session.get("turns", [])]
        self.warm_len = w

    def save(self, force: bool = False) -> None:
        """Persist the ledger. ``autosave=False`` defers to an explicit flush()."""
        if not self.autosave and not force:
            self._dirty = True
            return
        storage.atomic_write_json(self.path, self.store)
        self._dirty = False

    def flush(self) -> None:
        if getattr(self, "_dirty", False):
            self.save(force=True)

    # ------------------------------------------------------------- planning
    def plan(self) -> Dict[str, Any]:
        """The bot's proposal for the turn that is about to be played."""
        pred = self.brain.predict()
        cfg = self._bet_cfg()
        bot_bet = betting.kelly_stakes(pred.probs, self.payouts, self.symbols,
                                       self.capital, cfg)
        pd = pred.as_dict(self.payouts)
        pd["bet"] = bot_bet
        pd["advice"] = self._advice(pred, bot_bet)
        return pd

    def _bet_cfg(self) -> Dict[str, Any]:
        c = self.settings.data["capital"]
        b = self.settings.data["bot_bet"]
        return {"stake_step": c["stake_step"], "min_stake": c["min_stake"],
                "max_stake_per_turn": c["max_stake_per_turn"],
                "max_exposure_fraction": c["max_exposure_fraction"],
                "kelly_fraction": b["kelly_fraction"],
                "min_edge_to_bet": b["min_edge_to_bet"],
                "allow_multi_colour": b["allow_multi_colour"],
                "provisional_kelly_scale":
                    self.settings.g("honesty", "provisional_kelly_scale", default=0.3)}

    def _advice(self, pred, bot_bet: Dict[str, Any]) -> str:
        t = self.meta.trust()
        v = t["verdict"]
        if pred.committed and bot_bet.get("total"):
            core = (f"BOT BETS {int(bot_bet['total'])}: " +
                    " + ".join(f"{int(v2)} {s.upper()}"
                               for s, v2 in bot_bet["stakes"].items() if v2 > 0))
        else:
            core = "BOT PASSES — " + (pred.blockers[0] if pred.blockers
                                      else "no positive edge at these prices")
        return f"{core}  |  meta-learner: {v} ({t['why']})"

    # ------------------------------------------------------------- betting
    def validate_bet(self, stakes: Dict[str, float]) -> Tuple[Dict[str, float], List[str]]:
        """Round and clamp a requested bet; return (stakes, warnings)."""
        c = self.settings.data["capital"]
        step, mn = float(c["stake_step"]), float(c["min_stake"])
        max_turn, max_exp = float(c["max_stake_per_turn"]), float(c["max_exposure_fraction"])
        warn: List[str] = []
        st = betting.clean_stakes(stakes, self.symbols)
        st = {s: betting.round_to_step(v, step) for s, v in st.items()}
        st = {s: v for s, v in st.items() if v >= mn}
        total = sum(st.values())
        if total > max_turn > 0:
            k = max_turn / total
            st = {s: betting.round_to_step(v * k, step) for s, v in st.items()}
            st = {s: v for s, v in st.items() if v >= mn}
            warn.append(f"capped to the per-turn limit of {max_turn:.0f}")
            total = sum(st.values())
        if total > self.capital + 1e-9:
            # Covers the busted case too: capital 0 collapses the bet to a
            # pass rather than raising, so a dead bankroll never dead-ends.
            k = self.capital / total if total > 0 else 0.0
            st = {s: betting.round_to_step(v * k, step) for s, v in st.items()}
            st = {s: v for s, v in st.items() if v >= mn}
            warn.append(f"capped to your capital of {self.capital:.0f}")
            total = sum(st.values())
        if self.capital > 0 and total / self.capital > max_exp:
            warn.append(f"exposure {100*total/self.capital:.0f}% of bankroll is above the "
                        f"{100*max_exp:.0f}% guideline — the bot would stake "
                        f"{max_exp*self.capital:.0f}")
        out = {s: st.get(s, 0) for s in self.symbols}
        return out, warn

    def place_bet(self, stakes: Optional[Dict[str, float]] = None,
                  follow: str = "mine", note: str = "") -> Dict[str, Any]:
        if self.session.get("pending"):
            raise ValueError("a bet is already locked in — enter the result first")
        if follow not in ("mine", "bot", "blend"):
            raise ValueError("follow must be 'mine', 'bot' or 'blend'")
        pred = self.brain.predict()
        bot_bet = betting.kelly_stakes(pred.probs, self.payouts, self.symbols,
                                       self.capital, self._bet_cfg())
        my = self.validate_bet(stakes or {})[0]
        if follow == "bot":
            raw = {s: float(v) for s, v in bot_bet["stakes"].items()}
            if pred.tier == "provisional":
                raw = {s: v * pred.kelly_scale for s, v in raw.items()}
            played, w = self.validate_bet(raw)
        elif follow == "blend":
            mix = {s: 0.5 * (my.get(s, 0) + float(bot_bet["stakes"].get(s, 0)))
                   for s in self.symbols}
            played, w = self.validate_bet(mix)
        else:
            played, w = self.validate_bet(my)
        total = sum(played.values())
        if total > self.capital + 1e-9:
            raise ValueError(f"stake {total:.0f} exceeds capital {self.capital:.0f}")
        self.session["pending"] = {
            "time": now_iso(),
            "followed": follow,
            "my_bet": {s: my.get(s, 0) for s in self.symbols},
            "played_bet": {s: played.get(s, 0) for s in self.symbols},
            "stake_total": round(total, 2),
            "shape": betting.bet_shape(played),
            "my_pick": betting.top_pick(my),
            "note": note,
            "warnings": w,
            "bot": pred.as_dict(self.payouts) | {"bet": bot_bet},
            "capital_before": round(self.capital, 2),
            "context": self.results()[-max(self.brain.max_order, 1):],
        }
        self.save()
        return self.session["pending"]

    def cancel_pending(self) -> Dict[str, Any]:
        """Abandon a locked-in bet before the result is known. No money moved."""
        had = bool(self.session.get("pending"))
        self.session["pending"] = None
        self.save()
        return {"cancelled": had, "capital": round(self.capital, 2)}

    def pass_turn(self, note: str = "") -> Dict[str, Any]:
        """Sit this turn out. The result is still recorded, so the brain learns."""
        return self.place_bet({s: 0 for s in self.symbols}, follow="mine",
                              note=note or "passed")

    # ------------------------------------------------------------ resolving
    def resolve(self, symbol: str) -> Dict[str, Any]:
        pend = self.session.get("pending")
        if not pend:
            raise ValueError("no bet is locked in")
        if symbol not in self.symbols:
            raise ValueError(f"result must be one of {self.symbols}")
        played = pend["played_bet"]
        total = float(pend["stake_total"])
        ret = float(self.payouts[symbol]) * float(played.get(symbol, 0))
        pnl = ret - total
        cap_before = float(pend["capital_before"])
        cap_after = cap_before + pnl
        bot = pend.get("bot") or {}
        my_pick, bot_pick = pend.get("my_pick"), bot.get("top")
        turn = {
            "n": len(self.session["turns"]) + 1,
            "time": pend["time"],
            "resolved_at": now_iso(),
            "context": pend.get("context", []),
            "bot": bot,
            "my_bet": pend["my_bet"],
            "my_pick": my_pick,
            "followed": pend["followed"],
            "played_bet": {s: played.get(s, 0) for s in self.symbols},
            "stake_total": round(total, 2),
            "shape": pend["shape"],
            "result": symbol,
            "return": round(ret, 2),
            "pnl": round(pnl, 2),
            "capital_before": round(cap_before, 2),
            "capital_after": round(cap_after, 2),
            "hit": ret > total,
            "push": abs(pnl) < 1e-9,
            "bot_pick_hit": (bot_pick == symbol) if bot_pick else None,
            "bot_committed": bool(bot.get("committed")),
            "my_pick_hit": (my_pick == symbol) if my_pick else None,
            "note": pend.get("note", ""),
            "warnings": pend.get("warnings", []),
        }
        self.session["turns"].append(turn)
        self.session["pending"] = None
        # Advance incrementally rather than refitting: brain.fit() is by
        # construction reset() + a loop of brain.observe(), so this reaches
        # exactly the same state at O(1) amortised cost per turn instead of
        # O(n) — which matters for long sessions. rebuild() stays available
        # (and is used by undo/edit_result) as the ground-truth path.
        self.brain.observe(symbol)
        self.meta.add(turn)
        self.capital = self._capital_of(self.session)
        self.curve.append(float(turn.get("capital_after", self.capital)))
        self.save()
        return turn

    # ---------------------------------------------------------- corrections
    def undo(self, n: int = 1) -> Dict[str, Any]:
        turns = self.session["turns"]
        n = max(1, min(n, len(turns)))
        removed = [turns.pop() for _ in range(n)]
        self.session["pending"] = None
        self.rebuild()
        self.save()
        return {"removed": len(removed), "capital": round(self.capital, 2),
                "last_removed": removed[0] if removed else None}

    def edit_result(self, turn_no: int, symbol: str) -> Dict[str, Any]:
        if symbol not in self.symbols:
            raise ValueError(f"result must be one of {self.symbols}")
        for t in self.session["turns"]:
            if t.get("n") == turn_no:
                old = t["result"]
                t["result"] = symbol
                played, total = t["played_bet"], float(t["stake_total"])
                ret = float(self.payouts[symbol]) * float(played.get(symbol, 0))
                t["return"] = round(ret, 2)
                t["pnl"] = round(ret - total, 2)
                t["hit"] = ret > total
                t["push"] = abs(t["pnl"]) < 1e-9
                t["bot_pick_hit"] = (t["bot"].get("top") == symbol) if t["bot"].get("top") else None
                t["my_pick_hit"] = (t.get("my_pick") == symbol) if t.get("my_pick") else None
                t["edited"] = {"from": old, "at": now_iso()}
                self._recompute_capital()
                self.rebuild()
                self.save()
                return t
        raise KeyError(f"no turn #{turn_no}")

    def _recompute_capital(self) -> None:
        cap = float(self.session.get("starting_capital", 0))
        cap += sum(float(d.get("amount", 0)) for d in self.session.get("deposits", []))
        for t in self.session["turns"]:
            t["capital_before"] = round(cap, 2)
            cap += float(t.get("pnl", 0) or 0)
            t["capital_after"] = round(cap, 2)

    def deposit(self, amount: float, note: str = "rebuy") -> Dict[str, Any]:
        amount = float(amount)
        if amount == 0:
            raise ValueError("amount must be non-zero")
        rec = {"amount": round(amount, 2), "time": now_iso(), "note": note}
        self.session.setdefault("deposits", []).append(rec)
        self.rebuild()
        self.save()
        return {"deposit": rec, "capital": round(self.capital, 2)}

    # ------------------------------------------------------------ analysis
    def shape_lab(self) -> List[Dict[str, Any]]:
        pred = self.brain.predict()
        return betting.shape_lab(pred.probs, self.payouts, self.symbols,
                                 self.capital, self._bet_cfg())

    def backtest(self, stake_mode: str = "kelly") -> Dict[str, Any]:
        """Replay the recorded results: your real ledger vs the bot's advice.

        Uses the brain's walk-forward out-of-sample predictions, so the bot in
        this backtest never sees a result before it bets on it — the same
        honesty rule as live play.
        """
        res = self.results()
        n = len(res)
        start = float(self.session.get("starting_capital", 0))
        cap = start
        bot_curve = [start]
        bets = wins = 0
        pnl_bot = 0.0
        committed_hits = committed_n = 0
        pred_curve = []
        for i in range(n):
            probs = self.brain.oos_probs[i] if i < len(self.brain.oos_probs) else None
            if probs is None:
                bot_curve.append(cap)
                continue
            top = max(probs, key=lambda s: probs[s])
            # Use the commit flag recorded walk-forward at that step, i.e. the
            # decision the brain would have made before seeing this result.
            committed = bool(self.brain.oos_committed[i]) \
                if i < len(self.brain.oos_committed) else False
            if committed:
                committed_n += 1
                committed_hits += 1 if top == res[i] else 0
            stake = 0.0
            if committed and stake_mode == "kelly":
                k = betting.kelly_stakes(probs, self.payouts, self.symbols, cap,
                                         self._bet_cfg())
                stake = float(k.get("total") or 0)
                alloc = {s: float(v) for s, v in k["stakes"].items()}
            elif committed:
                stake = min(cap * 0.05, cap)
                alloc = {top: stake}
            else:
                alloc = {s: 0.0 for s in self.symbols}
            if stake > 0 and cap > 0:
                stake = min(stake, cap)
                scale = stake / max(sum(alloc.values()), 1e-9)
                alloc = {s: v * scale for s, v in alloc.items()}
                ret = self.payouts[res[i]] * alloc.get(res[i], 0.0)
                pnl = ret - stake
                cap += pnl
                pnl_bot += pnl
                bets += 1
                wins += 1 if pnl > 0 else 0
            bot_curve.append(cap)
            pred_curve.append({"i": i, "top": top, "p": round(probs[top], 4),
                               "committed": committed})

        dd_abs, dd_frac = stats.max_drawdown(bot_curve)
        actual_curve = [start] + [float(t.get("capital_after", start))
                                  for t in self.session.get("turns", [])]
        ad_abs, ad_frac = stats.max_drawdown(actual_curve)
        turns = self.session.get("turns", [])
        staked = sum(float(t.get("stake_total", 0)) for t in turns)
        your_pnl = sum(float(t.get("pnl", 0)) for t in turns)
        your_bets = sum(1 for t in turns if float(t.get("stake_total", 0)) > 0)
        your_wins = sum(1 for t in turns if t.get("hit"))
        return {
            "n_results": n,
            "stake_mode": stake_mode,
            "bot": {
                "bets": bets, "wins": wins,
                "win_rate_pct": round(100 * wins / bets, 2) if bets else 0.0,
                "final_capital": round(cap, 2),
                "pnl": round(pnl_bot, 2),
                "roi_pct": round(100 * (cap - start) / start, 2) if start else 0.0,
                "max_drawdown": round(dd_abs, 2),
                "max_drawdown_pct": round(100 * dd_frac, 2),
                "committed_turns": committed_n,
                "committed_hit_rate_pct": round(100 * committed_hits / committed_n, 2)
                if committed_n else 0.0,
                "curve": [round(v, 2) for v in bot_curve[-600:]],
            },
            "you": {
                "bets": your_bets, "wins": your_wins,
                "win_rate_pct": round(100 * your_wins / your_bets, 2) if your_bets else 0.0,
                "final_capital": round(actual_curve[-1], 2) if actual_curve else start,
                "pnl": round(your_pnl, 2),
                "staked": round(staked, 2),
                "roi_pct": round(100 * your_pnl / staked, 2) if staked else 0.0,
                "max_drawdown": round(ad_abs, 2),
                "max_drawdown_pct": round(100 * ad_frac, 2),
                "curve": [round(v, 2) for v in actual_curve[-600:]],
            },
        }

    # ---------------------------------------------------------------- state
    def presets(self) -> List[Dict[str, Any]]:
        d = float(self.settings.g("capital", "default_split_stake", default=120))
        pred = self.brain.predict()
        top = pred.top
        others = [s for s in self.symbols if s != top]
        out = [
            {"id": "pass", "label": "PASS (stake 0)", "stakes": {s: 0 for s in self.symbols}},
            {"id": f"split_{int(d)}_{others[0]}{others[1]}",
             "label": f"YOUR SPLIT: {int(d)} {others[0].upper()} + {int(d)} {others[1].upper()}",
             "stakes": {**{s: 0 for s in self.symbols}, others[0]: d, others[1]: d}},
        ]
        for a_i, a in enumerate(self.symbols):
            for b in self.symbols[a_i + 1:]:
                out.append({"id": f"split_{int(d)}_{a}{b}",
                            "label": f"{int(d)} {a.upper()} + {int(d)} {b.upper()}",
                            "stakes": {**{s: 0 for s in self.symbols}, a: d, b: d}})
        out.append({"id": "top", "label": f"All on bot's top ({top.upper()})",
                    "stakes": {**{s: 0 for s in self.symbols},
                               top: min(float(self.settings.g("capital", "max_stake_per_turn",
                                                              default=600)),
                                        round(self.capital * 0.1 / 10) * 10 or 10)}})
        return out

    def state(self, include: Sequence[str] = ("lab", "patterns", "backtest")) -> Dict[str, Any]:
        pend = self.session.get("pending")
        plan = self.plan()
        turns = self.session.get("turns", [])
        busted = self.capital < float(self.settings.g("capital", "min_stake", default=10))
        res = self.results()
        payload: Dict[str, Any] = {
            "phase": "await_result" if pend else "await_bet",
            "session": {"name": self.name, "all": self.list_sessions(),
                        "starting_capital": self.session.get("starting_capital"),
                        "warm_start": len(self.session.get("warm_start", []))},
            "capital": {
                "value": round(self.capital, 2),
                "start": float(self.session.get("starting_capital", 0)),
                "net": round(self.capital - float(self.session.get("starting_capital", 0))
                             - sum(float(d.get("amount", 0))
                                   for d in self.session.get("deposits", [])), 2),
                "deposits": round(sum(float(d.get("amount", 0))
                                      for d in self.session.get("deposits", [])), 2),
                "busted": busted,
                "turns": len(turns),
                "at_risk": round(float(pend["stake_total"]), 2) if pend else 0.0,
                "min_stake": self.settings.g("capital", "min_stake"),
                "max_stake_per_turn": self.settings.g("capital", "max_stake_per_turn"),
                "stake_step": self.settings.g("capital", "stake_step"),
            },
            "prediction": plan,
            "pending": pend,
            "meta": self.meta.snapshot(self.capital,
                                       float(self.session.get("starting_capital", 0))),
            "brain": self.brain.stats_snapshot(),
            "curves": self.brain.curves(),
            "results_tail": res[-60:],
            "recent_turns": [self._slim(t) for t in turns[-25:]][::-1],
            "presets": self.presets(),
            "book": self.settings.data.get("_book", {}),
            "payouts": self.payouts,
            "names": self.settings.name_of,
            "colors": self.settings.hex_of,
            "symbols": self.symbols,
        }
        if "lab" in include:
            payload["shape_lab"] = self.shape_lab()
        if "patterns" in include:
            payload["patterns"] = self.brain.pattern_report(order=2, min_n=6)[:14]
            payload["patterns3"] = self.brain.pattern_report(order=3, min_n=8)[:10]
        if "backtest" in include and turns:
            payload["backtest"] = self.backtest()
        return payload

    @staticmethod
    def _slim(t: Dict[str, Any]) -> Dict[str, Any]:
        return {"n": t.get("n"), "time": t.get("time"), "result": t.get("result"),
                "followed": t.get("followed"), "shape": t.get("shape"),
                "stake": t.get("stake_total"), "pnl": t.get("pnl"),
                "capital_after": t.get("capital_after"),
                "played_bet": t.get("played_bet"),
                "bot_top": (t.get("bot") or {}).get("top"),
                "bot_conf": (t.get("bot") or {}).get("confidence"),
                "bot_committed": (t.get("bot") or {}).get("committed"),
                "bot_pick_hit": t.get("bot_pick_hit"),
                "my_pick": t.get("my_pick"), "my_pick_hit": t.get("my_pick_hit"),
                "hit": t.get("hit"), "note": t.get("note", ""),
                "edited": t.get("edited")}

    # --------------------------------------------------------------- export
    def export_csv(self) -> str:
        return storage.turns_to_csv(self.session.get("turns", []), self.symbols,
                                    self.settings.name_of)

    def export_results_csv(self) -> str:
        turns = self.session.get("turns", [])
        rows = [{"symbol": s, "time": ""} for s in self.session.get("warm_start", [])]
        rows += [{"symbol": t["result"], "time": t.get("time", "")} for t in turns]
        return storage.results_to_csv(self.symbols, self.settings.name_of, rows)
