"""CI: end-of-run metrics JSON contains required keys (spec §22)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


REQUIRED_KEYS = frozenset(
    {
        "metrics_version",
        "run_id",
        "repo_mode",
        "tasks_total",
        "tasks_completed",
        "tasks_failed",
        "tasks_blocked",
        "debug_loop_iterations",
        "fix_pattern_hits",
        "agent_insights_emitted",
        "orchestrator_interventions",
        "human_checkpoints_reached",
        "models_used",
        "prompt_quality_delta",
        "local_vs_cloud_ratio",
        "plan_only",
        "dry_run",
    }
)


def test_build_run_metrics_has_required_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    os.environ["SAGE_SESSION_ID"] = "test-session-metrics"
    from sage.observability.run_metrics import build_run_metrics

    state = {
        "repo_mode": "greenfield",
        "debug_attempts": 0,
        "task_dag": {"nodes": []},
        "session_memory": {},
        "plan_only": False,
        "dry_run": False,
    }
    m = build_run_metrics(state)
    missing = REQUIRED_KEYS - set(m.keys())
    assert not missing, f"missing keys: {missing}"


def test_write_run_metrics_json_writes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    os.environ["SAGE_SESSION_ID"] = "sess-write-metrics"
    from sage.observability.run_metrics import write_run_metrics_json

    state = {
        "repo_mode": "existing_repo",
        "debug_attempts": 1,
        "task_dag": {
            "nodes": [{"id": "t1", "status": "completed", "model_used": "qwen2.5-coder:1.5b"}]
        },
        "session_memory": {},
    }
    p = write_run_metrics_json(state, base_dir=tmp_path)
    assert p is not None and p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert REQUIRED_KEYS.issubset(data.keys())
