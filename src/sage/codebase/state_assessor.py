"""
SAGE State Assessor (MVP)
---------------------------
Heuristic completion/brokenness assessment for existing repos.
"""

from __future__ import annotations

from typing import Any


def assess_state(codebase_map: dict[str, Any]) -> dict[str, Any]:
    incomplete_files = set(codebase_map.get("incomplete_files", []))

    completion_status: dict[str, str] = {}
    for f in incomplete_files:
        completion_status[f] = "partial"

    # Broken imports are complex; MVP leaves this empty.
    return {
        "completion_status": completion_status,
        "open_threads": codebase_map.get("open_threads", []),
        "broken_imports": [],
        "last_active_files": [],
    }
