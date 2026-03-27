"""Contract smoke: load_memory returns expected keys (no LLM)."""

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
