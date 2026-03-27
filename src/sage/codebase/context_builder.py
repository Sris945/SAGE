"""
SAGE Codebase Context Builder
------------------------------
Builds a planner-ready context brief for existing repos and writes `.sage/` caches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sage.codebase.scanner import scan_repo
from sage.codebase.semantic_reader import build_semantic_map
from sage.codebase.state_assessor import assess_state
from sage.codebase.conventions import detect_conventions


def build_codebase_brief(repo_path: str) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    cache_dir = repo / ".sage"
    cache_dir.mkdir(parents=True, exist_ok=True)

    codebase_map = scan_repo(str(repo))
    semantic_map = build_semantic_map(str(repo))
    assessment = assess_state(codebase_map)
    conventions = detect_conventions(str(repo))

    incomplete = list(codebase_map.get("incomplete_files", []))
    open_threads = list(codebase_map.get("open_threads", []))

    frameworks = codebase_map.get("frameworks", [])
    entry_points = codebase_map.get("entry_points", [])
    test_locations = codebase_map.get("test_locations", [])

    # Planner-ready brief.
    brief: dict[str, Any] = {
        "mode": "existing_repo",
        "codebase_summary": (
            f"Repo has Python code with frameworks={frameworks or ['unknown']}. "
            f"Entry points={entry_points[:5]}. "
            f"Found {len(incomplete)} potentially incomplete file(s) and {len(test_locations)} test file(s)."
        ),
        "what_exists": {
            "frameworks": frameworks,
            "entry_points": entry_points,
            "test_locations": test_locations,
            "dependencies_sample": (codebase_map.get("dependencies") or [])[:30],
        },
        "what_is_incomplete": incomplete[:100],
        "what_is_broken": assessment.get("broken_imports", [])[:50],
        "open_threads": open_threads[:50],
        "conventions": conventions,
        "architecture_inferred": (
            "Inferred from repository heuristics; upgrade to Tree-sitter + embeddings in Phase 4."
        ),
        "suggested_next_tasks": (
            ["Add missing tests for incomplete files"] if not test_locations else []
        )
        + (["Fix TODO/FIXME areas"] if incomplete else []),
    }

    # Write caches.
    (cache_dir / "project.json").write_text(
        json.dumps(
            {"conventions": conventions, "frameworks": frameworks, "entry_points": entry_points},
            indent=2,
        )
    )
    (cache_dir / "codebase_map.json").write_text(json.dumps(codebase_map, indent=2))
    (cache_dir / "semantic_map.json").write_text(json.dumps(semantic_map, indent=2))
    (cache_dir / "conventions.md").write_text(
        "## Conventions (heuristic)\n\n"
        f"- Style/tools: {', '.join(conventions.get('style', []))}\n"
        f"- Test runner: {conventions.get('test_runner', 'unknown')}\n"
        f"- Frameworks: {', '.join(conventions.get('frameworks', []))}\n"
    )
    (cache_dir / "open_threads.md").write_text(
        "## Open Threads\n\n" + "\n".join(f"- {t}" for t in open_threads[:50])
    )

    # Return the brief for prompt injection.
    return brief
