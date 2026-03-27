"""Tests for shared LLM JSON extraction."""

from __future__ import annotations

import json

import pytest

from sage.agents.llm_parse import parse_json_object, parse_json_value, parse_patch_json


def test_parse_json_value_prose_prefix_and_suffix():
    raw = 'Here you go:\n{"a": 1, "b": {"c": "}"}}\nThanks.'
    val = parse_json_value(raw)
    assert val == {"a": 1, "b": {"c": "}"}}


def test_parse_json_object_nested():
    raw = "```json\n{\"x\": true}\n```\n"
    assert parse_json_object(raw) == {"x": True}


def test_parse_patch_json_prefers_first_object_when_both_present():
    raw = '[{"op":"add","path":"/x","value":1}]\n{"file":"a.py","patch":"x"}'
    # raw_decode scans for first { or [ — '[' comes first, so array wins
    val = parse_patch_json(raw)
    assert isinstance(val, list)


def test_parse_json_value_invalid_raises():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_json_value("no braces here")
