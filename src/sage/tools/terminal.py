"""
Spec-parity tools shim: terminal command execution.
"""

from __future__ import annotations

from sage.execution.executor import ToolExecutionEngine
from sage.protocol.schemas import PatchRequest


def run_command(command: str) -> dict:
    req = PatchRequest(operation="run_command", file="", patch=command)
    return ToolExecutionEngine().execute(req)
