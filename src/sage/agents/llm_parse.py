"""
Robust JSON extraction from LLM chat completions.

Greedy ``re.search(r"\\{[\\s\\S]+\\}")`` fails when models emit multiple JSON
values or prose after the JSON. We use :class:`json.JSONDecoder.raw_decode` from
the first ``{`` or ``[`` so strings and nesting are handled correctly.
"""

from __future__ import annotations

import json
import re
from typing import Any


def strip_think_blocks(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()


def strip_markdown_fences(text: str) -> str:
    t = re.sub(r"```(?:json)?\s*", "", text or "")
    return re.sub(r"```", "", t).strip()


def strip_llm_noise(text: str) -> str:
    return strip_markdown_fences(strip_think_blocks(text))


def parse_json_value(text: str) -> Any:
    """
    Parse the first JSON object or array in *text*.

    Raises:
        ValueError: if no valid JSON value is found.
        json.JSONDecodeError: if the substring is not valid JSON.
    """
    s = strip_llm_noise(text)
    decoder = json.JSONDecoder()
    last_err: json.JSONDecodeError | None = None
    for i, ch in enumerate(s):
        if ch not in "{[":
            continue
        try:
            return decoder.raw_decode(s, i)[0]
        except json.JSONDecodeError as e:
            last_err = e
            continue
    if last_err is not None:
        raise last_err
    raise ValueError(f"No JSON object or array found in model response:\n{(text or '')[:500]}")


def parse_json_object(text: str) -> dict:
    """Parse the first JSON **object** (dict) in *text*."""
    val = parse_json_value(text)
    if isinstance(val, dict):
        return val
    raise ValueError(f"Expected JSON object, got {type(val).__name__}")


def parse_patch_json(text: str) -> dict | list:
    """
    Parse JSON for coder/debugger: either a flat PatchRequest object or
    RFC-6902-style array; same contract as legacy ``_extract_json`` in coder.
    """
    return parse_json_value(text)
