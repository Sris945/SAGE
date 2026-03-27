"""
Reward analysis and tuning helpers (Phase 5).

This produces a small JSON report summarizing reward distributions and
basic correlations to support iterative tuning of `reward_v1`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from sage.rl.export_dataset import load_routing_jsonl


@dataclass(frozen=True)
class RewardReport:
    rows: int
    mean_reward: float
    median_reward: float
    p10_reward: float
    p90_reward: float
    fallback_rate: float
    mean_reward_primary: float
    mean_reward_fallback: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "mean_reward": self.mean_reward,
            "median_reward": self.median_reward,
            "p10_reward": self.p10_reward,
            "p90_reward": self.p90_reward,
            "fallback_rate": self.fallback_rate,
            "mean_reward_primary": self.mean_reward_primary,
            "mean_reward_fallback": self.mean_reward_fallback,
        }


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return float(sorted_vals[0])
    if p >= 100:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(len(sorted_vals) - 1, lo + 1)
    frac = k - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def analyze_rewards(data_path: Path) -> RewardReport:
    rows = load_routing_jsonl(Path(data_path))
    rewards = [float(r.get("reward", 0.0)) for r in rows]
    rewards_sorted = sorted(rewards)

    acts = [int(r.get("action_fallback", 0) or 0) for r in rows]
    fallback_count = sum(1 for a in acts if a == 1)
    fallback_rate = (fallback_count / len(rows)) if rows else 0.0

    r_primary = [
        float(r.get("reward", 0.0)) for r in rows if int(r.get("action_fallback", 0) or 0) == 0
    ]
    r_fallback = [
        float(r.get("reward", 0.0)) for r in rows if int(r.get("action_fallback", 0) or 0) == 1
    ]

    return RewardReport(
        rows=len(rows),
        mean_reward=float(mean(rewards)) if rewards else 0.0,
        median_reward=float(median(rewards)) if rewards else 0.0,
        p10_reward=_percentile(rewards_sorted, 10),
        p90_reward=_percentile(rewards_sorted, 90),
        fallback_rate=float(fallback_rate),
        mean_reward_primary=float(mean(r_primary)) if r_primary else 0.0,
        mean_reward_fallback=float(mean(r_fallback)) if r_fallback else 0.0,
    )


def write_reward_report(data_path: Path, out_path: Path) -> dict[str, Any]:
    rep = analyze_rewards(data_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = rep.to_dict()
    payload["data_path"] = str(Path(data_path))
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
