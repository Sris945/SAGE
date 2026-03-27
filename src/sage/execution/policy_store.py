"""
Persisted tool/workspace/skills policy in ``.sage/policy.json`` (per project cwd).

Precedence for *effective* values: **environment variables win**, then file, then defaults.
``sage permissions set`` updates both the file and ``os.environ`` so the current process
and subprocesses see changes immediately; the file survives new sage invocations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


POLICY_FILENAME = "policy.json"


def policy_file_path() -> Path:
    return Path.cwd() / ".sage" / POLICY_FILENAME


def load_policy_file() -> dict[str, Any]:
    path = policy_file_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def save_policy_file(data: dict[str, Any]) -> None:
    path = policy_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def delete_policy_file() -> bool:
    path = policy_file_path()
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def effective_tool_policy() -> str:
    env = (os.environ.get("SAGE_TOOL_POLICY") or "").strip().lower()
    if env in ("standard", "strict"):
        return env
    if env:
        return "standard"
    data = load_policy_file()
    m = (str(data.get("tool_policy") or "standard")).strip().lower()
    return m if m in ("standard", "strict") else "standard"


def effective_workspace_root_str() -> str:
    env = (os.environ.get("SAGE_WORKSPACE_ROOT") or "").strip()
    if env:
        return env
    return (str(load_policy_file().get("workspace_root") or "")).strip()


def effective_skills_root_str() -> str:
    env = (os.environ.get("SAGE_SKILLS_ROOT") or "").strip()
    if env:
        return env
    return (str(load_policy_file().get("skills_root") or "")).strip()


def tool_policy_source() -> str:
    if (os.environ.get("SAGE_TOOL_POLICY") or "").strip():
        return "env"
    data = load_policy_file()
    if (str(data.get("tool_policy") or "")).strip().lower() in ("standard", "strict"):
        return "file"
    return "default"


def workspace_root_source() -> str:
    if (os.environ.get("SAGE_WORKSPACE_ROOT") or "").strip():
        return "env"
    if (str(load_policy_file().get("workspace_root") or "")).strip():
        return "file"
    return "default"


def skills_root_source() -> str:
    if (os.environ.get("SAGE_SKILLS_ROOT") or "").strip():
        return "env"
    if (str(load_policy_file().get("skills_root") or "")).strip():
        return "file"
    return "default"
