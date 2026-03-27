"""
Greenfield end-to-end: no --repo → skips codebase_intel; full DAG worker path.

**Not the OSS shipping gate** — agents are mocked. For real Ollama + real agents,
see `docs/LIVE_TESTING.md` and `scripts/live_verify.sh`.

Mocks planner/coder/reviewer/test_engineer so no Ollama. Exercises:
load_memory → detect_mode → prompt_middleware → route_model → planner →
human_checkpoint (auto) → scheduler → task_worker → tool_executor →
verification_gate (reviewer + test file) → save_memory → memory optimizer.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sage.protocol.schemas import PatchRequest, TaskNode
from sage.agents.reviewer import ReviewResult

pytestmark = pytest.mark.e2e


def _planner_nodes():
    return [
        TaskNode(
            id="task_001",
            description="Create hello.py with a small function (greenfield smoke).",
            dependencies=[],
            assigned_agent="coder",
            verification="",
            status="pending",
        )
    ]


def _coder_patch():
    pr = PatchRequest(
        file="hello.py",
        operation="create",
        patch=(
            "# line1\n# line2\n# line3\n# line4\n"
            "def msg():\n"
            "    return 'hello'\n"
        ),
        reason="e2e greenfield",
    )
    return {
        "status": "patch_ready",
        "patch_request": vars(pr),
        "file": pr.file,
        "operation": pr.operation,
        "reason": pr.reason,
        "error": None,
        "model_used": "mock",
        "strategy_key": "mock",
        "epistemic_flags": [],
    }


def _test_patch():
    pr = PatchRequest(
        file="tests/test_hello.py",
        operation="create",
        patch=(
            "def test_msg():\n"
            "    import hello\n"
            "    assert hello.msg() == 'hello'\n"
        ),
        reason="e2e test file",
    )
    return {
        "status": "patch_ready",
        "patch_request": vars(pr),
        "test_file": pr.file,
    }


def _review_ok():
    return ReviewResult(
        passed=True,
        score=1.0,
        verdict="PASS",
        issues=[],
        suggestion="ok",
        model_used="mock",
    )


@patch("sage.agents.test_engineer.TestEngineerAgent.run")
@patch("sage.agents.reviewer.ReviewerAgent.run")
@patch("sage.agents.coder.CoderAgent.run")
@patch("sage.agents.planner.PlannerAgent.run")
def test_greenfield_invoke_completes_task(
    mock_planner,
    mock_coder,
    mock_reviewer,
    mock_te,
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAGE_WORKSPACE_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv("SAGE_SESSION_ID", "e2e-greenfield-session")
    # Greenfield defaults
    os.environ.pop("SAGE_MODEL_PROFILE", None)

    mock_planner.side_effect = lambda **kwargs: _planner_nodes()
    mock_coder.side_effect = lambda **kwargs: _coder_patch()
    mock_reviewer.side_effect = lambda **kwargs: _review_ok()
    mock_te.side_effect = lambda **kwargs: _test_patch()

    # .sage for rules (optional)
    (tmp_path / ".sage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)

    from sage.orchestrator.workflow import app

    initial_state = {
        "user_prompt": "Greenfield: add hello.py.",
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
        "mode": "auto",
        "resume_from_handoff": False,
    }

    app.invoke(initial_state)

    assert (tmp_path / "hello.py").is_file()
    assert (tmp_path / "tests" / "test_hello.py").is_file()
    mock_planner.assert_called()
    mock_coder.assert_called()
    mock_reviewer.assert_called()
    mock_te.assert_called()
