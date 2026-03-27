"""
Spec-parity tools shim: git operations.

SAGE's execution engine blocks dangerous commands; this wrapper keeps the shape
expected by the spec while delegating to the existing executor.
"""

from __future__ import annotations

from sage.tools.terminal import run_command


def git_status() -> dict:
    return run_command("git status")


def git_diff() -> dict:
    return run_command("git diff")
