"""
Compare ordered event types in JSON-lines session logs (golden trace regression).

Used by tests and optionally by CLI to diff expected vs actual traces.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_event_types(path: Path | str) -> list[str]:
    """Return ``type`` field values in file order (skips malformed lines)."""
    p = Path(path)
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if isinstance(t, str):
            out.append(t)
    return out


def ordered_prefix_matches(actual: list[str], expected_prefix: list[str]) -> bool:
    """
    True if ``expected_prefix`` appears as a contiguous subsequence at the start
    of ``actual`` (same length prefix).
    """
    if len(actual) < len(expected_prefix):
        return False
    return actual[: len(expected_prefix)] == expected_prefix


def find_subsequence(actual: list[str], pattern: list[str]) -> int | None:
    """Return start index of first occurrence of ``pattern`` in ``actual``, or None."""
    if not pattern:
        return 0 if not actual else None
    n, m = len(actual), len(pattern)
    for i in range(n - m + 1):
        if actual[i : i + m] == pattern:
            return i
    return None
