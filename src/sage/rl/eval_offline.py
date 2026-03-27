"""
Offline evaluation of routing policies on the exported dataset (Phase 5).

This avoids running the full agent pipeline (which may depend on local LLMs)
and instead compares policies on logged (s, a, r) rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from sage.rl.export_dataset import load_routing_jsonl
from sage.rl.policy import load_routing_policy


@dataclass(frozen=True)
class OfflineEvalResult:
    rows: int
    static_mean_reward: float
    policy_mean_reward: float
    delta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "static_mean_reward": self.static_mean_reward,
            "policy_mean_reward": self.policy_mean_reward,
            "delta": self.delta,
        }


def offline_eval(
    *, data_path: Path, checkpoint: Path, min_confidence: float = 0.0
) -> OfflineEvalResult:
    rows = load_routing_jsonl(Path(data_path))
    if not rows:
        return OfflineEvalResult(rows=0, static_mean_reward=0.0, policy_mean_reward=0.0, delta=0.0)

    pol = load_routing_policy(Path(checkpoint))
    if pol is None:
        raise ValueError(f"Could not load policy checkpoint: {checkpoint}")

    # Evaluate via a simple IPS-like estimate using only rewards for actions that match
    # the target policy (conservative lower bound). For synthetic data, this still gives
    # a useful directional signal.
    static_rewards: list[float] = []
    policy_rewards: list[float] = []

    for r in rows:
        role = str(r.get("agent_role") or "")
        tcs = float(r.get("task_complexity_score", 0.0) or 0.0)
        fc = int(r.get("primary_failure_count", 0) or 0)
        rew = float(r.get("reward", 0.0) or 0.0)
        action = int(r.get("action_fallback", 0) or 0)

        # Static: interpret action as observed (dataset was generated under some behavior).
        static_rewards.append(rew)

        # Policy: only count reward if action matches policy choice.
        use_fb, conf = pol.should_use_fallback(role, tcs, fc)
        if conf < float(min_confidence):
            continue
        target_action = 1 if use_fb else 0
        if target_action == action:
            policy_rewards.append(rew)

    static_mean = float(mean(static_rewards)) if static_rewards else 0.0
    policy_mean = float(mean(policy_rewards)) if policy_rewards else 0.0
    return OfflineEvalResult(
        rows=len(rows),
        static_mean_reward=static_mean,
        policy_mean_reward=policy_mean,
        delta=policy_mean - static_mean,
    )


def write_offline_eval_report(
    *, data_path: Path, checkpoint: Path, out_path: Path, min_confidence: float = 0.0
) -> dict[str, Any]:
    res = offline_eval(data_path=data_path, checkpoint=checkpoint, min_confidence=min_confidence)
    payload = res.to_dict()
    payload.update(
        {
            "data_path": str(Path(data_path)),
            "checkpoint": str(Path(checkpoint)),
            "min_confidence": float(min_confidence),
        }
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
