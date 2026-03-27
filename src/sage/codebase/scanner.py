"""
SAGE Codebase Scanner
---------------------
MVP structural scan for existing repos.

This intentionally uses lightweight heuristics (file tree + regex/TODO detection)
to produce a planner-ready summary until full AST/embedding ingestion is added.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_TODO_RE = re.compile(r"(TODO|FIXME|HACK|XXX)\b.*", re.IGNORECASE)
_DEF_RE = re.compile(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:(]", re.MULTILINE)


def _read_text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def scan_repo(repo_path: str) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repo path not found: {repo}")

    py_files: list[Path] = []
    for p in repo.rglob("*.py"):
        # Skip caches / venvs
        if any(part in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"} for part in p.parts):
            continue
        py_files.append(p)

    has_req = (repo / "requirements.txt").exists()
    has_pyproject = (repo / "pyproject.toml").exists()
    requirements = []
    if has_req:
        requirements = [
            line.strip()
            for line in (repo / "requirements.txt").read_text(errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    open_threads: list[str] = []
    incomplete_files: list[str] = []
    file_summaries: dict[str, dict[str, Any]] = {}

    for f in py_files:
        rel = str(f.relative_to(repo))
        txt = _read_text(f)

        todos = _TODO_RE.findall(txt)
        # Heuristic for incomplete/skeleton: TODO-ish or very small stubs.
        is_skeleton = ("pass" in txt) or ("..." in txt and "def " in txt)
        if todos or is_skeleton:
            incomplete_files.append(rel)
            # Capture at most a few matching lines to keep brief small.
            for m in _TODO_RE.finditer(txt):
                open_threads.append(f"{rel}: {m.group(0)[:200]}")
                if len(open_threads) >= 30:
                    break

        functions = _DEF_RE.findall(txt)[:30]
        classes = _CLASS_RE.findall(txt)[:20]
        file_summaries[rel] = {
            "functions": functions,
            "classes": classes,
        }

    # Framework detection (very lightweight).
    frameworks: list[str] = []
    for needle, label in [
        ("FastAPI", "FastAPI"),
        ("Django", "Django"),
        ("Flask", "Flask"),
        ("Starlette", "Starlette"),
    ]:
        if any(needle in _read_text(f) for f in py_files[:200]):
            frameworks.append(label)

    # Test detection
    test_locations: list[str] = []
    for f in repo.rglob("test_*.py"):
        if any(part in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"} for part in f.parts):
            continue
        test_locations.append(str(f.relative_to(repo)))
    for f in repo.rglob("*_test.py"):
        if any(part in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"} for part in f.parts):
            continue
        test_locations.append(str(f.relative_to(repo)))

    # Entry points (heuristic: app/main)
    entry_points: list[str] = []
    for name in ["app.py", "main.py", "server.py", "src/app.py", "src/main.py"]:
        p = repo / name
        if p.exists():
            entry_points.append(name)

    # Expose a compact structure.
    return {
        "repo_path": str(repo),
        "languages": ["python"] if py_files else [],
        "frameworks": frameworks,
        "entry_points": entry_points,
        "test_locations": sorted(set(test_locations))[:50],
        "dependencies": requirements[:200],
        "incomplete_files": sorted(set(incomplete_files))[:100],
        "open_threads": open_threads[:50],
        "file_summaries": file_summaries,  # may be large; caller should cache selectively
        "has_pyproject": has_pyproject,
        "has_requirements": has_req,
    }
