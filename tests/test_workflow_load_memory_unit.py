"""Contract smoke: load_memory returns expected keys (no LLM)."""

import json

from sage.orchestrator.workflow import load_memory


def test_load_memory_returns_core_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = {
        "user_prompt": "test",
        "enhanced_prompt": "",
        "task_dag": {},
        "current_task": {},
        "current_task_id": "",
        "agent_output": {},
        "execution_result": {},
        "debug_attempts": 0,
        "session_memory": {},
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "artifacts_by_task": {},
        "architect_blueprints_by_task": {},
        "verification_passed": False,
        "verification_needs_tool_apply": False,
        "orchestrator_escalation": False,
        "task_updates": [],
        "repo_path": "",
        "repo_mode": "greenfield",
        "last_error": "",
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "max_retries": 5,
        "events": [],
        "mode": "research",
        "resume_from_handoff": False,
    }
    out = load_memory(base)
    assert "session_memory" in out
    assert "insight_feed" in out
    assert out.get("task_updates") == []


def test_load_memory_skip_handoff_ignores_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mem = tmp_path / "memory"
    mem.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "reason": "test",
        "state_snapshot": {
            "task_dag": {"nodes": [{"id": "ghost", "status": "running"}]},
            "current_task_id": "ghost",
        },
    }
    (mem / "handoff.json").write_text(json.dumps(payload), encoding="utf-8")

    base = {
        "user_prompt": "test",
        "enhanced_prompt": "",
        "task_dag": {},
        "current_task": {},
        "current_task_id": "",
        "agent_output": {},
        "execution_result": {},
        "debug_attempts": 0,
        "session_memory": {},
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "artifacts_by_task": {},
        "architect_blueprints_by_task": {},
        "verification_passed": False,
        "verification_needs_tool_apply": False,
        "orchestrator_escalation": False,
        "task_updates": [],
        "repo_path": "",
        "repo_mode": "greenfield",
        "last_error": "",
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "max_retries": 5,
        "events": [],
        "mode": "research",
        "resume_from_handoff": False,
        "skip_handoff": True,
    }
    out = load_memory(base)
    assert out.get("resume_from_handoff") is False
    assert out.get("task_dag") == {}
