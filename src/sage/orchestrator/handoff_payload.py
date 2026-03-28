"""Build compact handoff snapshots for session resume (spec §17).

Handoff JSON is written on interrupt paths and consumed in ``load_memory`` when
``state_snapshot`` is present. Older handoff files without ``state_snapshot`` still
set ``resume_from_handoff`` for observability only.
"""

from __future__ import annotations

import copy
from typing import Any

# Keys safe to copy without pulling LangGraph-internal or non-serializable objects.
_HANDOFF_STATE_KEYS = (
    "user_prompt",
    "enhanced_prompt",
    "current_task_id",
    "current_task",
    "task_dag",
    "last_error",
    "mode",
    "repo_path",
    "repo_mode",
    "orchestrator_escalation",
    "human_checkpoint_done",
    "pending_patch_request",
    "pending_patch_source",
    "artifacts_by_task",
    "architect_blueprints_by_task",
)


def snapshot_handoff_state(state: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy structured fields; shallow-copy short scalars."""
    out: dict[str, Any] = {}
    for key in _HANDOFF_STATE_KEYS:
        if key not in state:
            continue
        val = state[key]
        if key in (
            "task_dag",
            "current_task",
            "pending_patch_request",
            "artifacts_by_task",
            "architect_blueprints_by_task",
        ):
            out[key] = copy.deepcopy(val)
        elif key == "session_memory":
            # Optional: keep small slice (session_memory is merged separately in load_memory)
            continue
        else:
            out[key] = val
    sm = state.get("session_memory")
    if isinstance(sm, dict):
        out["session_memory_subset"] = {
            k: copy.deepcopy(sm[k])
            for k in ("codebase_brief", "sage_memory_summary", "active_project")
            if k in sm
        }
    return out


def serialize_insight_feed(feed: Any, *, max_items: int = 80) -> list[dict[str, Any]]:
    """Best-effort serialization of OrchestratorIntelligenceFeed.insights."""
    if feed is None:
        return []
    rows = getattr(feed, "insights", None)
    if not isinstance(rows, list):
        return []
    tail = rows[-max_items:] if len(rows) > max_items else rows
    out: list[dict[str, Any]] = []
    for ins in tail:
        out.append(
            {
                "agent": getattr(ins, "agent", "") or "",
                "task_id": getattr(ins, "task_id", "") or "",
                "insight_type": getattr(ins, "insight_type", "") or "",
                "content": (getattr(ins, "content", "") or "")[:2000],
                "severity": getattr(ins, "severity", "") or "",
                "epistemic_flag": getattr(ins, "epistemic_flag", "") or "",
                "timestamp": getattr(ins, "timestamp", "") or "",
                "requires_orchestrator_action": bool(
                    getattr(ins, "requires_orchestrator_action", False)
                ),
            }
        )
    return out


def apply_handoff_to_state(base: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    """Merge ``state_snapshot`` from disk onto state produced after MemoryManager.load_state."""
    snap = handoff.get("state_snapshot")
    if not isinstance(snap, dict):
        return base
    merged = dict(base)
    for key in _HANDOFF_STATE_KEYS:
        if key not in snap or key == "session_memory":
            continue
        if key in (
            "task_dag",
            "current_task",
            "pending_patch_request",
            "artifacts_by_task",
            "architect_blueprints_by_task",
        ):
            merged[key] = copy.deepcopy(snap[key])
        else:
            merged[key] = snap[key]
    subset = snap.get("session_memory_subset")
    if isinstance(subset, dict):
        sm = dict(merged.get("session_memory") or {})
        for k, v in subset.items():
            sm[k] = copy.deepcopy(v)
        merged["session_memory"] = sm
    return merged


def persist_interrupt_handoff(state: dict[str, Any], *, reason: str) -> None:
    """Write ``memory/handoff.json`` with a structured snapshot + insight tail."""
    from sage.orchestrator.session_manager import SessionManager

    SessionManager().write_interrupt_handoff(
        reason=reason,
        state_snapshot=snapshot_handoff_state(state),
        insight_snapshot=serialize_insight_feed(state.get("insight_feed")),
    )


def rehydrate_insights_into_feed(feed: Any, rows: list[dict[str, Any]]) -> None:
    """Append serialized insights without re-firing bus hooks (resume path)."""
    if feed is None or not rows:
        return
    lock = getattr(feed, "_lock", None)
    if lock is None:
        return
    from sage.protocol.schemas import AgentInsight

    restored: list[Any] = []
    for row in rows:
        try:
            itype = row.get("insight_type") or "observation"
            if itype not in ("uncertainty", "risk", "decision", "observation"):
                itype = "observation"
            sev = row.get("severity") or "low"
            if sev not in ("low", "medium", "high"):
                sev = "low"
            restored.append(
                AgentInsight(
                    agent=str(row.get("agent") or "unknown"),
                    task_id=str(row.get("task_id") or ""),
                    insight_type=itype,
                    content=str(row.get("content") or ""),
                    severity=sev,
                    epistemic_flag=str(row.get("epistemic_flag") or ""),
                    timestamp=str(row.get("timestamp") or ""),
                    requires_orchestrator_action=bool(row.get("requires_orchestrator_action")),
                )
            )
        except Exception:
            continue
    with lock:
        feed.insights.extend(restored)
