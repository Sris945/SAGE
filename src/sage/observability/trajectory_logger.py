"""
Trajectory & prompt-quality delta logging (MVP for Tier 1 RL scaffolding).

This module keeps an in-process last-score cache per task and computes:
  quality_delta = current_score - last_score_for_task

Thread-safe by design so it works with parallel task workers.
"""

from __future__ import annotations

import threading
from typing import Any

from sage.observability.structured_logger import log_event


_lock = threading.Lock()
_last_score_by_task: dict[str, float] = {}


def record_quality_delta(
    *,
    task_id: str,
    agent: str,
    current_score: float,
    passed: bool,
    model_used: str = "",
    issues: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues = issues or []
    extra = extra or {}
    with _lock:
        prev = _last_score_by_task.get(task_id)
        delta = (current_score - prev) if prev is not None else 0.0
        _last_score_by_task[task_id] = current_score

    payload = {
        "task_id": task_id,
        "agent": agent,
        "passed": passed,
        "reviewer_score": current_score,
        "quality_delta": delta,
        "model_used": model_used,
        "issues": issues,
        **extra,
    }
    log_event("PROMPT_QUALITY_DELTA", payload=payload)
    return payload


def record_trajectory_step(
    *,
    task_id: str,
    agent: str,
    action_model: str,
    action_strategy_key: str,
    reward: float,
    terminal: bool,
    state: dict | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Instrument Phase 4+ trajectory logging for later Tier 2 RL.

    MVP: we log whatever "state/action/reward/terminal" signals are currently
    available from the orchestrator and gate outcomes.
    """
    state = state or {}
    extra = extra or {}

    payload: dict[str, Any] = {
        "task_id": task_id,
        "agent": agent,
        "action": {
            "model_chosen": action_model,
            "prompt_strategy_key": action_strategy_key,
        },
        "reward": reward,
        "terminal": terminal,
        "state": state,
        **extra,
    }
    log_event("TRAJECTORY_STEP", payload=payload)
    return payload
