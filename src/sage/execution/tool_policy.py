"""
Unified tool execution policy: workspace roots (re-exported), deny rules,
and optional strict allowlist for ``run_command``.

Env:
  SAGE_TOOL_POLICY — ``standard`` (default) or ``strict``
  SAGE_WORKSPACE_ROOT — see workspace_policy
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from sage.execution.workspace_policy import format_workspace_policy_summary

# Substring deny list (always applied).
DENY_SUBSTRINGS: tuple[str, ...] = (
    "rm -rf /",
    "sudo",
    "curl | bash",
    "wget | sh",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",  # fork bomb
)

# In ``strict`` mode, argv[0] basename must match one of these prefixes (no shell).
_STRICT_ALLOW_BASENAMES: frozenset[str] = frozenset(
    {
        "git",
        "pytest",
        "python",
        "python3",
        "ruff",
        "mypy",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "cargo",
        "go",
        "make",
        "cmake",
        "echo",
        "which",
        "ls",
        "cat",
        "head",
        "tail",
        "ollama",
        "pytest-asyncio",
        "black",
        "sh",
        "bash",
        "deno",
        "node",
    }
)


def tool_policy_mode() -> str:
    m = (os.environ.get("SAGE_TOOL_POLICY") or "standard").strip().lower()
    return m if m in ("standard", "strict") else "standard"


def parse_command_argv(patch: str) -> list[str]:
    raw = (patch or "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


def check_run_command_policy(patch: str) -> None:
    """
    Raise SafetyViolation if the command string is not allowed.
    """
    from sage.execution.exceptions import SafetyViolation

    for blocked in DENY_SUBSTRINGS:
        if blocked in patch:
            raise SafetyViolation(f"Blocked command pattern: {blocked!r}")

    if tool_policy_mode() != "strict":
        return

    argv = parse_command_argv(patch)
    if not argv:
        raise SafetyViolation("strict policy: empty command")
    base = Path(argv[0]).name
    if base not in _STRICT_ALLOW_BASENAMES:
        raise SafetyViolation(
            f"strict policy: executable {base!r} not in allowlist "
            f"(set SAGE_TOOL_POLICY=standard to disable)"
        )


def format_tool_policy_summary() -> str:
    ws = format_workspace_policy_summary()
    mode = tool_policy_mode()
    deny_preview = ", ".join(repr(x[:16]) for x in DENY_SUBSTRINGS[:4])
    extra = f"Tool policy mode: {mode}\nDenied substrings include: {deny_preview}…\n"
    if mode == "strict":
        extra += (
            f"Strict mode: argv[0] basename must be one of "
            f"{len(_STRICT_ALLOW_BASENAMES)} known dev tools (git, pytest, …).\n"
        )
    return ws + "\n" + extra
