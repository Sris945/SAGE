"""Tests for ``.sage/policy.json`` resolution."""

from __future__ import annotations

import json

from sage.execution.policy_store import (
    delete_policy_file,
    effective_tool_policy,
    load_policy_file,
    policy_file_path,
    save_policy_file,
    skills_root_source,
    tool_policy_source,
    workspace_root_source,
)


def test_effective_tool_policy_env_wins_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sage").mkdir()
    save_policy_file({"tool_policy": "strict"})
    monkeypatch.setenv("SAGE_TOOL_POLICY", "standard")
    assert effective_tool_policy() == "standard"
    assert tool_policy_source() == "env"


def test_effective_tool_policy_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sage").mkdir()
    monkeypatch.delenv("SAGE_TOOL_POLICY", raising=False)
    save_policy_file({"tool_policy": "strict"})
    assert effective_tool_policy() == "strict"
    assert tool_policy_source() == "file"


def test_workspace_source_default(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SAGE_WORKSPACE_ROOT", raising=False)
    assert workspace_root_source() == "default"


def test_delete_policy_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sage").mkdir()
    p = policy_file_path()
    p.write_text(json.dumps({"tool_policy": "standard"}) + "\n", encoding="utf-8")
    assert delete_policy_file() is True
    assert not p.is_file()
    assert load_policy_file() == {}


def test_skills_source_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sage").mkdir()
    monkeypatch.delenv("SAGE_SKILLS_ROOT", raising=False)
    save_policy_file({"skills_root": str(tmp_path / "skills")})
    assert skills_root_source() == "file"
