"""Unit tests for orchestrator.handoff_payload."""

from __future__ import annotations

from sage.orchestrator.handoff_payload import (
    apply_handoff_to_state,
    persist_interrupt_handoff,
    snapshot_handoff_state,
)
from sage.orchestrator.session_manager import SessionManager


def test_snapshot_roundtrip_task_dag(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()
    state = {
        "user_prompt": "goal",
        "current_task_id": "t1",
        "task_dag": {"nodes": [{"id": "t1", "status": "running"}]},
        "current_task": {"id": "t1"},
        "last_error": "e",
        "mode": "research",
        "repo_path": "",
        "repo_mode": "greenfield",
        "orchestrator_escalation": False,
        "human_checkpoint_done": False,
        "session_memory": {"codebase_brief": {"k": 1}},
        "insight_feed": None,
    }
    snap = snapshot_handoff_state(state)
    assert snap["user_prompt"] == "goal"
    handoff = {"schema_version": 1, "state_snapshot": snap, "insight_snapshot": []}
    fresh = {
        "user_prompt": "",
        "current_task_id": "",
        "task_dag": {},
        "session_memory": {},
        "insight_feed": None,
    }
    merged = apply_handoff_to_state(fresh, handoff)
    assert merged["current_task_id"] == "t1"
    assert merged["task_dag"]["nodes"][0]["id"] == "t1"


def test_persist_interrupt_handoff_writes_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()
    state = {
        "user_prompt": "x",
        "task_dag": {"nodes": []},
        "current_task_id": "",
        "current_task": {},
        "last_error": "",
        "mode": "auto",
        "repo_path": "",
        "repo_mode": "greenfield",
        "orchestrator_escalation": False,
        "human_checkpoint_done": False,
        "session_memory": {},
        "insight_feed": None,
    }
    persist_interrupt_handoff(state, reason="test_interrupt")
    data = SessionManager().check_handoff()
    assert data is not None
    assert data.get("schema_version") == 1
    assert data.get("reason") == "test_interrupt"
    assert "state_snapshot" in data
