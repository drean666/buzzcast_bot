"""settings.py — load, validate and persist config.json.

Everything is overridable from the file; anything missing falls back to
DEFAULTS so an old or hand-edited config never crashes the app.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import sys
from typing import Any, Dict, List, Optional


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")

DEFAULTS: Dict[str, Any] = {
    "schema": 2,
    "symbols": ["r", "b", "g"],
    "symbol_names": {"r": "RED", "b": "BLUE", "g": "GREEN"},
    "symbol_colors": {"r": "#e8402a", "b": "#2f6fed", "g": "#1faa59"},
    "payouts": {"r": 3.0, "b": 3.0, "g": 3.0},
    "capital": {
        "starting": 1000,
        "stake_step": 10,
        "min_stake": 10,
        "max_stake_per_turn": 600,
        "max_exposure_fraction": 0.2,
        "bust_fraction": 0.02,
        "default_split_stake": 120,
    },
    "brain": {
        "max_context_order": 5,
        "interpolation_alpha": 2.0,
        "recency_decay": 0.997,
        "hedge_eta": 0.6,
        "weight_decay": 0.995,
        "min_data_before_analysis": 15,
    },
    "honesty": {
        "confidence_threshold_percent": 38.0,
        "min_info_gain_bits": 0.01,
        "max_p_value": 0.05,
        "recent_window": 40,
    },
    "bot_bet": {
        "kelly_fraction": 0.25,
        "min_edge_to_bet": 0.01,
        "allow_multi_colour": True,
    },
    "trust": {
        "decay": 0.99,
        "decide_margin": 0.75,
        "tilt_multiplier": 1.6,
        "tilt_exposure_fraction": 0.25,
        "ucb_c": 1.2,
    },
    "sim": {
        "default_turns": 200,
        "sources": ["fair", "biased_green", "markov", "replay"],
        "policies": ["bot", "always_split_two", "always_top", "flat_stake",
                     "martingale", "random"],
    },
    "ui": {"host": "0.0.0.0", "port": 8077},
}


def base_dir() -> str:
    """Project root, correct whether run as a script or as a frozen .exe."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively overlay ``over`` on ``base`` (returns a new dict)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Settings:
    """Typed, validated view over the config dict."""

    def __init__(self, data: Optional[Dict[str, Any]] = None,
                 path: Optional[str] = None):
        self.data: Dict[str, Any] = deep_merge(DEFAULTS, data or {})
        self.path = path or os.path.join(base_dir(), "config.json")
        self._validate()

    # ---------------------------------------------------------------- load
    @classmethod
    def load(cls, path: Optional[str] = None) -> "Settings":
        path = path or os.path.join(base_dir(), "config.json")
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                # Never die on a broken config: fall back to defaults, but
                # keep the broken file around for the user to inspect.
                try:
                    os.replace(path, path + ".corrupt")
                except OSError:
                    pass
                data = {}
        return cls(data, path)

    def save(self, path: Optional[str] = None) -> str:
        path = path or self.path
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
        return path

    # ------------------------------------------------------------- access
    def patch(self, values: Dict[str, Any]) -> None:
        """Deep-merge a partial config (e.g. {"capital": {"min_stake": 20}})."""
        if not isinstance(values, dict):
            raise ValueError("patch must be an object")
        allowed = set(self.data.keys())
        for group, sub in values.items():
            if group not in allowed:
                raise ValueError(f"unknown config group {group!r}")
            if not isinstance(sub, dict):
                raise ValueError(f"config group {group!r} must be an object")
            for key, val in sub.items():
                if key not in self.data[group]:
                    raise ValueError(f"unknown setting {group}.{key}")
                old = self.data[group][key]
                if isinstance(old, bool):
                    self.data[group][key] = bool(val)
                elif isinstance(old, (int, float)):
                    self.data[group][key] = type(old)(val)
                else:
                    self.data[group][key] = val
        self._validate()
        self.data["_patched"] = _now()

    def g(self, *keys: str, default: Any = None) -> Any:
        cur: Any = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @property
    def symbols(self) -> List[str]:
        return list(self.data["symbols"])

    @property
    def name_of(self) -> Dict[str, str]:
        return dict(self.data["symbol_names"])

    @property
    def hex_of(self) -> Dict[str, str]:
        return dict(self.data["symbol_colors"])

    def payout(self, sym: str) -> float:
        return float(self.data["payouts"].get(sym, 3.0))

    @property
    def payouts(self) -> Dict[str, float]:
        return {s: self.payout(s) for s in self.symbols}

    # ---------------------------------------------------------- validate
    def _validate(self) -> None:
        syms = self.symbols
        if len(syms) < 2:
            raise ValueError("need at least 2 symbols")
        if len(set(syms)) != len(syms):
            raise ValueError("duplicate symbols in config")
        for s in syms:
            p = self.payout(s)
            if p <= 1.0:
                raise ValueError(f"payout for {s!r} must be > 1.0 (got {p})")
        # A book where the implied probabilities sum to < 1 would be an
        # arbitrage; warn by clamping nothing, but record it for the UI.
        self.data["_book"] = {
            "implied_sum": round(sum(1.0 / self.payout(s) for s in syms), 4),
            "house_edge_pct": round(
                100.0 * (sum(1.0 / self.payout(s) for s in syms) - 1.0), 2),
            "arbitrage_possible": sum(1.0 / self.payout(s) for s in syms) < 0.9999,
            "break_even_hit_rate_single_pct": round(
                100.0 / (sum(self.payout(s) for s in syms) / len(syms)), 2),
        }
        cap = self.data["capital"]
        if cap["min_stake"] > cap["starting"]:
            cap["min_stake"] = max(1, cap["starting"] // 10)
        br = self.data["brain"]
        br["max_context_order"] = max(1, min(12, int(br["max_context_order"])))
        if not (0.0 < br["recency_decay"] <= 1.0):
            br["recency_decay"] = 0.997
        ho = self.data["honesty"]
        ho["max_p_value"] = min(0.5, max(1e-6, float(ho["max_p_value"])))

    # ------------------------------------------------------------ helper
    def as_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self.data)
