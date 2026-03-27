"""
Workspace roots for tool execution and prompt disclosure.

Paths must stay under allowed roots (resolved). Symlinks are resolved via
Path.resolve(); a symlink pointing outside an allowed root may still escape —
see docs/path_threat_model.md.
"""

from __future__ import annotations

import os
from pathlib import Path


def default_workspace_roots() -> tuple[Path, ...]:
    raw = (os.environ.get("SAGE_WORKSPACE_ROOT") or "").strip()
    if raw:
        parts = [p.strip() for p in raw.replace(",", os.pathsep).split(os.pathsep) if p.strip()]
        return tuple(Path(p).expanduser().resolve() for p in parts)
    return (Path.cwd().resolve(),)


def path_is_under_workspace(file_path: Path, roots: tuple[Path, ...]) -> bool:
    try:
        path = file_path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def format_workspace_policy_summary() -> str:
    roots = default_workspace_roots()
    root_lines = "\n".join(f"  - {r}" for r in roots)
    return (
        f"Allowed workspace roots ({len(roots)}):\n{root_lines}\n"
        "Filesystem create/edit/delete only for paths under these roots (after resolve).\n"
        "Commands: subprocess without shell; policy in executor SafetyViolation rules."
    )
