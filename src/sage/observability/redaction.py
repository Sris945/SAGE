"""
Redact sensitive substrings from payloads before logging to disk or mirrors.

Not a full DLP engine — best-effort patterns for API keys and auth headers.
"""

from __future__ import annotations

import copy
import re
from typing import Any

_REDACT = "[REDACTED]"

# sk-… OpenAI-style, gh_/github_pat, Bearer tokens (short capture)
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE), _REDACT),
    (re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{20,}\b"), _REDACT),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}", re.IGNORECASE), _REDACT),
    (re.compile(r"\bxox[baprs]-[a-zA-Z0-9-]{10,}\b"), _REDACT),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9._\-/+=]{8,}"), "Bearer " + _REDACT),
    (
        re.compile(r"(?i)(api[_-]?key|apikey|secret|password|token)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
        r"\1: " + _REDACT,
    ),
)


def redact_text(s: str) -> str:
    if not s:
        return s
    out = s
    for rx, repl in _PATTERNS:
        out = rx.sub(repl, out)
    return out


def redact_obj(obj: Any) -> Any:
    """Deep-copy and redact strings inside dicts/lists (JSON-log safe)."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(x) for x in obj)
    return copy.deepcopy(obj)
