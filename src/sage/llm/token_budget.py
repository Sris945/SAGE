"""
Optional character budgets for LLM prompts (approximate token control).

Env:
  SAGE_MAX_PROMPT_CHARS_TOTAL — if > 0, trim message ``content`` fields so the
  sum of lengths stays under this cap (last messages trimmed first).
"""

from __future__ import annotations

import copy
import os
from typing import Any


def max_prompt_chars_total() -> int:
    raw = (os.environ.get("SAGE_MAX_PROMPT_CHARS_TOTAL") or "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def clamp_messages_chars(messages: list[dict[str, Any]], max_total: int) -> list[dict[str, Any]]:
    if max_total <= 0:
        return messages

    out = copy.deepcopy(messages)

    def total_len() -> int:
        return sum(len(str(m.get("content") or "")) for m in out)

    while total_len() > max_total:
        lengths = [len(str(m.get("content") or "")) for m in out]
        if not lengths or max(lengths) <= 1:
            break
        idx = max(range(len(out)), key=lambda i: lengths[i])
        c = str(out[idx].get("content") or "")
        # Shrink longest message by ~10% until under cap (no suffix growth loops).
        new_len = max(1, (len(c) * 9) // 10)
        out[idx]["content"] = c[:new_len]
    return out
