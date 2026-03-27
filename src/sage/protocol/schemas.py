"""
SAGE Protocol Schemas
---------------------
All inter-agent communication uses these dataclasses strictly.
No free-form text between agents.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TaskNode:
    id: str
    description: str
    dependencies: list[str]
    # MD spec: TaskNode assigned_agent is the worker role responsible for that node.
    assigned_agent: Literal["coder", "architect", "reviewer", "test_engineer"]
    status: Literal["pending", "running", "blocked", "failed", "completed"] = "pending"
    retry_count: int = 0
    model_used: str = ""
    strategy_key: str = ""  # Tier 1 RL discrete strategy identifier
    verification: str = ""  # shell command to verify the task output
    # MD spec: used by ModelRouter fallback triggers.
    # Deterministically computed heuristic in PlannerAgent during DAG creation.
    task_complexity_score: float = 0.0
    epistemic_flags: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    status: Literal["completed", "failed"]
    summary: str
    artifacts: list[str] = field(default_factory=list)
    epistemic_flags: list[str] = field(default_factory=list)
    model_used: str = ""
    tokens_used: int = 0
    logs: str = ""


@dataclass
class PatchRequest:
    file: str
    operation: Literal["edit", "create", "delete", "run_command"]
    patch: str  # unified diff or full content or command string
    reason: str
    epistemic_flags: list[str] = field(default_factory=list)


@dataclass
class ErrorReport:
    task_id: str
    error_type: Literal["runtime", "test", "dependency", "logic"]
    logs: str
    suspected_cause: str
    suggested_fix: str = ""
    pattern_match: str = ""


@dataclass
class AgentInsight:
    agent: str
    task_id: str
    insight_type: Literal["uncertainty", "risk", "decision", "observation"]
    content: str
    severity: Literal["low", "medium", "high"]
    epistemic_flag: str = ""
    timestamp: str = ""
    requires_orchestrator_action: bool = False


@dataclass
class Event:
    type: str
    task_id: str
    payload: dict
    timestamp: str
