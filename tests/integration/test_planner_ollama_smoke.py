"""Planner smoke against local Ollama (optional)."""

import subprocess

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.ollama]


def _ollama_ok() -> bool:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, timeout=8, text=True)
        return r.returncode == 0
    except Exception:
        return False


def test_planner_produces_task_list(monkeypatch, tmp_path):
    if not _ollama_ok():
        pytest.skip("ollama not available")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAGE_MODEL_PROFILE", "test")

    from sage.agents.planner import PlannerAgent

    planner = PlannerAgent()
    nodes = planner.run(
        "Add a hello.py that prints hello.",
        memory={},
        mode="auto",
        universal_prefix="",
    )
    assert isinstance(nodes, list)
    assert len(nodes) >= 1
    assert nodes[0].id
