"""
Tier 1 RL: UCB bandit (MVP).

We treat each "strategy" as a discrete action key, and update using the
reviewer outcome as a reward signal.

Thread-safe for parallel workers.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path
import json


class UCBStrategyBandit:
    def __init__(self, storage_path: str | Path | None = None):
        self._lock = threading.Lock()
        # strategy_key -> {count: int, value_mean: float}
        self._stats: dict[str, dict[str, float]] = {}
        self._storage_path = Path(storage_path) if storage_path is not None else None
        if self._storage_path is not None:
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self._storage_path is None:
            return
        try:
            if not self._storage_path.exists() or self._storage_path.stat().st_size == 0:
                return
            payload = json.loads(self._storage_path.read_text())
            stats = payload.get("stats", payload) or {}
            if isinstance(stats, dict):
                self._stats = {k: dict(v) for k, v in stats.items() if isinstance(v, dict)}
        except Exception:
            # Corrupt/invalid cache should never break orchestration.
            return

    def _save_to_disk(self) -> None:
        if self._storage_path is None:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._storage_path.with_suffix(self._storage_path.suffix + ".tmp")
            payload = {"stats": self._stats}
            tmp_path.write_text(json.dumps(payload, indent=2))
            tmp_path.replace(self._storage_path)
        except Exception:
            return

    def _ensure(self, strategy_key: str) -> None:
        if strategy_key not in self._stats:
            self._stats[strategy_key] = {"count": 0.0, "value_mean": 0.0}

    def select(self, *, strategy_keys: list[str]) -> str:
        if not strategy_keys:
            raise ValueError("strategy_keys cannot be empty")

        with self._lock:
            for k in strategy_keys:
                self._ensure(k)

            # Ensure exploration: pick any untried strategy first.
            untried = [k for k in strategy_keys if self._stats[k]["count"] == 0.0]
            if untried:
                return untried[0]

            total = sum(self._stats[k]["count"] for k in strategy_keys)
            if total <= 0:
                return strategy_keys[0]

            best_key = strategy_keys[0]
            best_ucb = -1e9
            for k in strategy_keys:
                count = self._stats[k]["count"]
                mean = self._stats[k]["value_mean"]
                # UCB1: mean + sqrt(2 * ln(total) / count)
                ucb = mean + math.sqrt(2.0 * math.log(total) / max(count, 1e-9))
                if ucb > best_ucb:
                    best_ucb = ucb
                    best_key = k
            return best_key

    def update(self, *, strategy_key: str, reward: float) -> None:
        with self._lock:
            self._ensure(strategy_key)
            count = self._stats[strategy_key]["count"]
            mean = self._stats[strategy_key]["value_mean"]

            count += 1.0
            # Incremental mean update
            mean = mean + (reward - mean) / max(count, 1.0)
            self._stats[strategy_key]["count"] = count
            self._stats[strategy_key]["value_mean"] = mean
            self._save_to_disk()


_GLOBAL_BANDIT = UCBStrategyBandit(storage_path=Path("memory") / "rl" / "ucb_bandit.json")


def get_global_bandit() -> UCBStrategyBandit:
    return _GLOBAL_BANDIT
