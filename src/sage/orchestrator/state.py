"""LangGraph state shape for SAGE workflows."""

from __future__ import annotations

from typing import Annotated, TypedDict

try:
    from typing import NotRequired  # py311+
except ImportError:  # pragma: no cover
    from typing_extensions import NotRequired


def task_updates_reducer(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """
    Reducer for LangGraph parallel fan-out.

    Workers append deltas. The merge node clears the accumulator by returning
    a list whose first element is {"__reset__": true}.
    """
    new = new or []
    old = old or []
    if new and isinstance(new[0], dict) and new[0].get("__reset__"):
        return []
    return old + new


class SAGEState(TypedDict):
    user_prompt: str
    enhanced_prompt: str  # after middleware
    task_dag: dict
    current_task: dict
    current_task_id: str
    agent_output: dict
    execution_result: dict
    last_error: str
    fix_pattern_hit: bool
    fix_pattern_applied: bool
    max_retries: int
    debug_attempts: int
    session_memory: dict
    insight_feed: object
    pending_patch_request: dict
    pending_patch_source: str
    pending_fix_pattern_context: dict
    artifacts_by_task: dict
    architect_blueprints_by_task: dict
    verification_passed: bool
    verification_needs_tool_apply: bool
    orchestrator_escalation: bool
    human_checkpoint_done: bool
    task_updates: Annotated[list[dict], task_updates_reducer]
    events: list
    mode: str  # research | auto | silent
    resume_from_handoff: bool
    clarify: NotRequired[bool]  # planner Q&A; False with --no-clarify / silent
    token_usage: NotRequired[dict]  # accumulated per-session token counts
    model_override: NotRequired[str]  # fallback model set on overload


# Optional fields used at runtime but not declared on TypedDict (backward compat).
# retrieved_fix_patterns, repo_path, repo_mode, etc. are accessed via .get().
