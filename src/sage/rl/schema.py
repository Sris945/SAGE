"""
Versioned schema for offline routing datasets (Phase 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ROUTING_SCHEMA_VERSION = "1"


@dataclass
class RoutingTrainingRow:
    """One row for primary-vs-fallback routing offline RL."""

    schema_version: str
    session_id: str
    task_id: str
    agent_role: str
    timestamp: str
    task_complexity_score: float
    primary_failure_count: int
    action_fallback: int  # 0 = primary, 1 = fallback
    primary_model: str
    fallback_model: str
    model_chosen: str
    reward: float
    terminal: bool
    reward_version: str
    data_source: str = "unknown"  # "real" | "synthetic" | "unknown"
    state: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "agent_role": self.agent_role,
            "timestamp": self.timestamp,
            "task_complexity_score": self.task_complexity_score,
            "primary_failure_count": self.primary_failure_count,
            "action_fallback": self.action_fallback,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "model_chosen": self.model_chosen,
            "reward": self.reward,
            "terminal": self.terminal,
            "reward_version": self.reward_version,
            "data_source": self.data_source,
            "state": self.state,
        }
