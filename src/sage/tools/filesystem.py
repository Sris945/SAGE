"""
Spec-parity tools shim: filesystem operations.

This is a thin wrapper over `sage.execution.executor.ToolExecutionEngine` for
filesystem-oriented tool operations used by the pipeline.
"""

from __future__ import annotations

from sage.execution.executor import ToolExecutionEngine
from sage.protocol.schemas import PatchRequest


def apply_patch(req: PatchRequest) -> dict:
    return ToolExecutionEngine().execute(req)
