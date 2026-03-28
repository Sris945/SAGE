"""verification_gate must pass workspace root to VerificationEngine (not rely on process cwd)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sage.agents.reviewer import ReviewResult


@pytest.fixture
def _patch_trajectory():
    with (
        patch(
            "sage.observability.trajectory_logger.record_quality_delta",
            lambda **kwargs: None,
        ),
        patch(
            "sage.observability.trajectory_logger.record_trajectory_step",
            lambda **kwargs: None,
        ),
        patch(
            "sage.orchestrator.workflow.EVENT_BUS.emit_sync",
            lambda *a, **k: None,
        ),
    ):
        yield


@patch("sage.execution.verifier.VerificationEngine.run")
@patch("sage.agents.reviewer.ReviewerAgent.run")
def test_verification_gate_passes_resolved_repo_path_as_cwd(
    mock_review,
    mock_verify_run,
    tmp_path,
    monkeypatch,
    _patch_trajectory,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_x():\n    assert 1\n", encoding="utf-8"
    )

    mock_review.return_value = ReviewResult(
        passed=True,
        score=1.0,
        verdict="PASS",
        issues=[],
        suggestion="ok",
        model_used="mock",
    )
    mock_verify_run.return_value = {
        "passed": True,
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "command": "echo ok",
    }

    from sage.orchestrator.workflow import verification_gate

    ws = str(tmp_path.resolve())
    state = {
        "task_dag": {
            "nodes": [
                {
                    "id": "task_001",
                    "description": "implement app",
                    "dependencies": [],
                    "assigned_agent": "coder",
                    "verification": "echo ok",
                    "status": "pending",
                }
            ]
        },
        "current_task_id": "task_001",
        "artifacts_by_task": {"task_001": "src/app.py"},
        "session_memory": {},
        "execution_result": {},
        "repo_path": ws,
        "insight_feed": None,
        "_test_emit_guard": {},
    }

    out = verification_gate(state)
    assert out.get("verification_passed") is True
    mock_verify_run.assert_called_once()
    assert mock_verify_run.call_args[0][0] == "echo ok"
    assert mock_verify_run.call_args[1].get("cwd") == ws
