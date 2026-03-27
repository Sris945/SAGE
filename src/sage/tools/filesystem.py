"""
Spec-parity tools shim: filesystem operations.

This is a thin wrapper over `sage.execution.executor.ToolExecutionEngine` so the
codebase can match `SAGE_v1_FINAL.md`'s repo-structure expectations.
"""

from __future__ import annotations

from sage.execution.executor import ToolExecutionEngine
from sage.protocol.schemas import PatchRequest


def apply_patch(req: PatchRequest) -> dict:
    return ToolExecutionEngine().execute(req)
