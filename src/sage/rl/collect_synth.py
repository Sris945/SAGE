"""
Synthetic trajectory collection for Phase 5.

This provides a deterministic, non-LLM way to generate diverse routing rows by
logging `TRAJECTORY_STEP` entries into the session journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import random
from typing import Any

from sage.memory.manager import MemoryManager
from sage.orchestrator.model_router import ModelRouter


@dataclass(frozen=True)
class SynthCollectConfig:
    rows: int = 600
    seed: int = 42
    p_use_fallback_bias: float = 0.15
    reward_noise: float = 0.05


ROUTER_ROLES: tuple[str, ...] = (
    "planner",
    "architect",
    "coder",
    "debugger",
    "reviewer",
    "test_engineer",
    "memory_optimizer",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def collect_synthetic_trajectories(*, cfg: SynthCollectConfig) -> dict[str, Any]:
    """
    Append `cfg.rows` synthetic `TRAJECTORY_STEP` events into today's session log.
    Returns a summary dict with counts.
    """
    rng = random.Random(cfg.seed)
    mm = MemoryManager()
    router = ModelRouter()

    counts_by_role: dict[str, int] = {r: 0 for r in ROUTER_ROLES}
    fallback_count = 0

    for i in range(int(cfg.rows)):
        role = rng.choice(ROUTER_ROLES)
        primary, fallback = router.get_primary_fallback(role)

        task_complexity_score = _clip(rng.random(), 0.0, 1.0)
        primary_failure_count = int(rng.random() * 5)  # 0..4

        # Simulate a routing decision with a mild bias toward fallback as
        # complexity and failures rise.
        p_fb = (
            cfg.p_use_fallback_bias
            + (0.55 * task_complexity_score)
            + (0.08 * primary_failure_count)
        )
        p_fb = _clip(p_fb, 0.0, 1.0)
        use_fallback = rng.random() < p_fb
        model_chosen = fallback if use_fallback else primary
        fallback_count += 1 if use_fallback else 0

        # Reward: primary tends to do better on easy tasks; fallback helps on hard tasks.
        base = 0.85 - (0.45 * task_complexity_score) - (0.08 * primary_failure_count)
        if use_fallback:
            base += 0.35 * task_complexity_score + 0.05 * primary_failure_count
        reward = _clip(base + rng.uniform(-cfg.reward_noise, cfg.reward_noise), -1.0, 1.0)

        task_id = f"synth_{role}_{i:06d}"

        entry = {
            "type": "TRAJECTORY_STEP",
            "timestamp": _now_iso(),
            "task_id": task_id,
            "agent": role,
            "action": {"model_chosen": model_chosen, "prompt_strategy_key": ""},
            "reward": float(reward),
            "terminal": True,
            "state": {
                "task_complexity_score": float(task_complexity_score),
                "primary_failure_count": int(primary_failure_count),
                "verification_passed": bool(reward >= 0.5),
            },
            "extra": {"synthetic": True},
        }
        mm.append_session_log(json.dumps(entry))
        counts_by_role[role] += 1

    return {
        "status": "ok",
        "rows_appended": int(cfg.rows),
        "fallback_rate": (fallback_count / int(cfg.rows)) if cfg.rows else 0.0,
        "counts_by_role": counts_by_role,
    }
