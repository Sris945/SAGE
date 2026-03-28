"""Planner wiring for the documentation agent role."""

from __future__ import annotations

from sage.agents import planner as planner_mod
from sage.protocol.schemas import TaskNode


def test_validate_dag_accepts_documentation_alias() -> None:
    dag = {
        "nodes": [
            {
                "id": "t1",
                "description": "Refresh API overview",
                "dependencies": [],
                "assigned_agent": "docs",
                "verification": "python -c \"from pathlib import Path; assert Path('README.md').is_file()\"",
            }
        ]
    }
    nodes = planner_mod._validate_dag(dag)
    assert len(nodes) == 1
    assert nodes[0].assigned_agent == "documentation"


def test_upgrade_readme_task_to_documentation() -> None:
    dag = {
        "nodes": [
            {
                "id": "t1",
                "description": "Expand README with install instructions",
                "dependencies": [],
                "assigned_agent": "coder",
                "verification": "",
            }
        ]
    }
    nodes = planner_mod._validate_dag(dag)
    assert nodes[0].assigned_agent == "documentation"


def test_postprocess_fills_empty_doc_verification() -> None:
    nodes = [
        TaskNode(
            id="t1",
            description="Add CONTRIBUTING guide",
            dependencies=[],
            assigned_agent="documentation",
            verification="",
        )
    ]
    out = planner_mod._postprocess_task_nodes(nodes, user_goal="docs")
    assert "CONTRIBUTING.md" in out[0].verification
    assert "assert" in out[0].verification
