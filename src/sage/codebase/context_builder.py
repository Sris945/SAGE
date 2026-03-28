"""
SAGE Codebase Context Builder
------------------------------
Builds a planner-ready context brief for existing repos and writes ``.sage/`` caches.

Integrates:
  - Structural scan (scanner.py)
  - Semantic indexing via Tree-sitter + Qdrant (semantic_reader.py)
  - Health / completion assessment (state_assessor.py)
  - Runtime import/call probing (runtime_analyzer.py)
  - Code conventions detection (conventions.py)
  - Vector-backed code chunk retrieval (code_index.py)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sage.codebase.scanner import scan_repo
from sage.codebase.semantic_reader import build_semantic_map
from sage.codebase.state_assessor import assess_state
from sage.codebase.conventions import detect_conventions
from sage.codebase.code_index import ensure_index_for_brief


def _infer_architecture(codebase_map: dict[str, Any], conventions: dict[str, Any]) -> str:
    """
    Build a human-readable architecture description from scan results.
    """
    frameworks = codebase_map.get("frameworks", [])
    entry_points = codebase_map.get("entry_points", [])
    test_locations = codebase_map.get("test_locations", [])
    file_summaries: dict[str, Any] = codebase_map.get("file_summaries", {})

    total_files = len(file_summaries)
    total_funcs = sum(len(v.get("functions", [])) for v in file_summaries.values())
    total_classes = sum(len(v.get("classes", [])) for v in file_summaries.values())

    parts: list[str] = []

    if frameworks:
        parts.append(f"Web frameworks: {', '.join(frameworks)}.")
    else:
        # Infer from directory structure
        dirs = {Path(p).parts[0] for p in file_summaries if "/" in p or "\\" in p}
        if dirs:
            parts.append(f"Top-level packages: {', '.join(sorted(dirs)[:8])}.")

    if entry_points:
        parts.append(f"Entry points: {', '.join(entry_points[:5])}.")

    parts.append(
        f"Codebase: {total_files} Python files, ~{total_funcs} functions, ~{total_classes} classes."
    )

    if test_locations:
        parts.append(f"Tests: {len(test_locations)} test file(s) found.")
    else:
        parts.append("Tests: none detected.")

    style = conventions.get("style", [])
    test_runner = conventions.get("test_runner", "unknown")
    if style and style != ["unknown"]:
        parts.append(f"Tooling: {', '.join(style)}; test runner: {test_runner}.")

    return " ".join(parts)


def build_codebase_brief(repo_path: str) -> dict[str, Any]:
    """
    Build a comprehensive planner-ready brief for an existing repository.

    Runs structural scan, semantic indexing, health assessment, and runtime
    probing, then writes caches to ``.sage/``.

    Returns a dict suitable for injection into planner/agent prompts.
    """
    repo = Path(repo_path).resolve()
    cache_dir = repo / ".sage"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # --- Structural scan ---
    codebase_map = scan_repo(str(repo))

    # --- Semantic index ---
    semantic_map: dict[str, Any] = {}
    try:
        semantic_map = build_semantic_map(str(repo))
    except Exception:
        semantic_map = {"symbols": {}, "qdrant_built": False, "chunks_indexed": 0}

    # --- State assessment ---
    assessment: dict[str, Any] = {}
    try:
        assessment = assess_state(codebase_map, str(repo))
    except Exception:
        assessment = {
            "completion_status": {},
            "open_threads": codebase_map.get("open_threads", []),
            "broken_imports": [],
            "stub_functions": [],
            "last_active_files": [],
            "missing_tests": [],
        }

    # --- Runtime analysis (best-effort) ---
    runtime_analysis_raw: dict[str, Any] = {}
    try:
        from sage.codebase.runtime_analyzer import analyze_runtime

        runtime_analysis_raw = analyze_runtime(str(repo), max_files=20)
    except Exception:
        runtime_analysis_raw = {}

    # --- Conventions ---
    conventions = detect_conventions(str(repo))

    # Summarise runtime analysis
    import_errors: list[dict[str, Any]] = []
    broken_functions: list[dict[str, Any]] = []
    for rel_path, fdata in runtime_analysis_raw.items():
        if fdata.get("import_status") == "error":
            import_errors.append(
                {
                    "file": rel_path,
                    "error": fdata.get("import_error", ""),
                }
            )
        for fname, finfo in fdata.get("functions", {}).items():
            if finfo.get("status") in ("runtime_error", "timeout"):
                broken_functions.append(
                    {
                        "file": rel_path,
                        "function": fname,
                        "status": finfo["status"],
                        "error": finfo.get("error", ""),
                    }
                )

    runtime_summary: dict[str, Any] = {
        "files_analyzed": len(runtime_analysis_raw),
        "import_errors": import_errors[:50],
        "stub_functions": assessment.get("stub_functions", [])[:50],
        "broken_functions": broken_functions[:50],
    }

    # Scalar counts for quick reference
    stub_count = len(assessment.get("stub_functions", []))
    broken_import_count = len(assessment.get("broken_imports", []))
    missing_test_count = len(assessment.get("missing_tests", []))

    incomplete = list(codebase_map.get("incomplete_files", []))
    open_threads = list(assessment.get("open_threads", codebase_map.get("open_threads", [])))

    frameworks = codebase_map.get("frameworks", [])
    entry_points = codebase_map.get("entry_points", [])
    test_locations = codebase_map.get("test_locations", [])

    architecture = _infer_architecture(codebase_map, conventions)

    # --- Assemble brief ---
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
        "architecture_inferred": architecture,
        # Semantic index info
        "semantic_index_built": semantic_map.get("qdrant_built", False),
        "chunks_indexed": semantic_map.get("chunks_indexed", 0),
        "queryable_codebase": semantic_map.get("chunks_indexed", 0) > 0,
        # Health summary
        "stub_count": stub_count,
        "broken_import_count": broken_import_count,
        "missing_test_count": missing_test_count,
        "completion_status": assessment.get("completion_status", {}),
        "last_active_files": assessment.get("last_active_files", []),
        "missing_tests": assessment.get("missing_tests", [])[:50],
        # Runtime analysis
        "runtime_analysis": runtime_summary,
        # Suggested tasks
        "suggested_next_tasks": (
            ["Add missing tests for incomplete files"] if not test_locations else []
        )
        + (["Fix TODO/FIXME areas"] if incomplete else [])
        + (["Resolve broken imports"] if broken_import_count > 0 else [])
        + (["Implement stub functions"] if stub_count > 0 else []),
    }

    # --- Write caches ---
    try:
        (cache_dir / "project.json").write_text(
            json.dumps(
                {
                    "conventions": conventions,
                    "frameworks": frameworks,
                    "entry_points": entry_points,
                },
                indent=2,
            )
        )
    except Exception:
        pass

    try:
        (cache_dir / "codebase_map.json").write_text(json.dumps(codebase_map, indent=2))
    except Exception:
        pass

    # Write semantic map summary (symbols only, not the full chunk index)
    try:
        (cache_dir / "codebase_map.json").write_text(
            json.dumps(
                {
                    "qdrant_built": semantic_map.get("qdrant_built", False),
                    "chunks_indexed": semantic_map.get("chunks_indexed", 0),
                    "symbols_summary": {
                        rel: {
                            "functions": [f["name"] for f in info.get("functions", [])],
                            "classes": [c["name"] for c in info.get("classes", [])],
                        }
                        for rel, info in semantic_map.get("symbols", {}).items()
                    },
                },
                indent=2,
            )
        )
    except Exception:
        pass

    try:
        (cache_dir / "conventions.md").write_text(
            "## Conventions (heuristic)\n\n"
            f"- Style/tools: {', '.join(conventions.get('style', []))}\n"
            f"- Test runner: {conventions.get('test_runner', 'unknown')}\n"
            f"- Frameworks: {', '.join(conventions.get('frameworks', []))}\n"
        )
    except Exception:
        pass

    try:
        (cache_dir / "open_threads.md").write_text(
            "## Open Threads\n\n" + "\n".join(f"- {t}" for t in open_threads[:50])
        )
    except Exception:
        pass

    # Write runtime analysis
    try:
        (cache_dir / "runtime_analysis.json").write_text(json.dumps(runtime_analysis_raw, indent=2))
    except Exception:
        pass

    # --- Vector index + retrieval (spec §3 Stage 2) ---
    brief = ensure_index_for_brief(str(repo), brief)

    return brief
