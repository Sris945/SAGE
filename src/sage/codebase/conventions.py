"""
SAGE Codebase Conventions
-------------------------
Heuristic conventions extraction for existing repos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def detect_conventions(repo_path: str) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    pyproject = repo / "pyproject.toml"
    readme = repo / "README.md"

    py = _read(pyproject)

    style: list[str] = []
    if "[tool.black]" in py or "black" in py:
        style.append("black")
    if "isort" in py:
        style.append("isort")
    if "ruff" in py:
        style.append("ruff")

    naming = {
        "python": "snake_case_functions / PascalCase_classes (heuristic)",
    }

    # Minimal: infer likely test runner
    deps_text = _read(repo / "requirements.txt")
    test_runner = "pytest" if "pytest" in deps_text or (repo / "tests").exists() else "unknown"

    # Capture stack hint
    frameworks: list[str] = []
    if "fastapi" in py.lower() or "FastAPI" in _read(readme):
        frameworks.append("FastAPI")

    return {
        "style": style or ["unknown"],
        "naming": naming,
        "test_runner": test_runner,
        "frameworks": frameworks,
    }
