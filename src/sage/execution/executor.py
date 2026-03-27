"""
SAGE Tool Execution Engine
--------------------------
All agent actions route through this engine.
Nothing touches the host system directly.
Safety config is read from config/pipeline.yaml.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path

from sage.execution.exceptions import SafetyViolation
from sage.execution.tool_policy import DENY_SUBSTRINGS, check_run_command_policy, parse_command_argv
from sage.execution.workspace_policy import default_workspace_roots, path_is_under_workspace
from sage.protocol.schemas import PatchRequest

logger = logging.getLogger(__name__)


# In-process file lock registry (used for parallel DAG scheduling).
_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _lock_key_for_path(path: Path) -> str:
    # strict=False so we can lock paths that don't exist yet (create/edit).
    return str(path.resolve(strict=False))


def _get_lock_for_path(path: Path) -> threading.Lock:
    key = _lock_key_for_path(path)
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock


class ToolExecutionEngine:
    MAX_COMMAND_TIME = 30  # seconds
    MAX_FILE_WRITE_BYTES = 5_242_880  # 5MB
    MAX_PATCH_LINES = 200
    BLOCKED_COMMANDS = list(DENY_SUBSTRINGS)
    LOCK_TIMEOUT_SECONDS = 0.75

    def __init__(self, workspace_roots: Sequence[Path] | None = None) -> None:
        if workspace_roots is not None:
            self._workspace_roots = tuple(Path(p).resolve() for p in workspace_roots)
        else:
            self._workspace_roots = default_workspace_roots()

    def execute(self, req: PatchRequest) -> dict:
        # Normalise — model sometimes emits enum descriptions like "create | edit | delete"
        op: str = req.operation.split("|")[0].strip().lower()
        req.operation = op  # type: ignore[assignment]
        self._safety_check(req)
        if req.operation in ("edit", "create", "delete"):
            return self._filesystem_handler(req)
        elif req.operation == "run_command":
            return self._terminal_handler(req)
        raise ValueError(f"Unknown operation: {req.operation}")

    def _safety_check(self, req: PatchRequest) -> None:
        if req.operation == "run_command":  # already normalised
            check_run_command_policy(req.patch)
        if req.operation in ("edit", "create"):
            if len(req.patch.encode()) > self.MAX_FILE_WRITE_BYTES:
                raise SafetyViolation("Patch exceeds max file write size")
            if len(req.patch.splitlines()) > self.MAX_PATCH_LINES:
                raise SafetyViolation("Patch exceeds max line limit")

    def _filesystem_handler(self, req: PatchRequest) -> dict:
        path = Path(req.file)
        if not path_is_under_workspace(path, self._workspace_roots):
            return {
                "status": "error",
                "operation": req.operation,
                "file": str(path),
                "error": "path outside allowed workspace roots (SAGE_WORKSPACE_ROOT)",
            }
        if req.operation == "create":
            lock = _get_lock_for_path(path)
            acquired = lock.acquire(timeout=self.LOCK_TIMEOUT_SECONDS)
            if not acquired:
                return {
                    "status": "blocked",
                    "operation": "create",
                    "file": str(path),
                    "reason": "file lock busy",
                }
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(req.patch)
                return {"status": "ok", "operation": "create", "file": str(path)}
            finally:
                lock.release()
        elif req.operation == "edit":
            lock = _get_lock_for_path(path)
            acquired = lock.acquire(timeout=self.LOCK_TIMEOUT_SECONDS)
            if not acquired:
                return {
                    "status": "blocked",
                    "operation": "edit",
                    "file": str(path),
                    "reason": "file lock busy",
                }
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(req.patch)
                return {"status": "ok", "operation": "edit", "file": str(path)}
            finally:
                lock.release()
        elif req.operation == "delete":
            lock = _get_lock_for_path(path)
            acquired = lock.acquire(timeout=self.LOCK_TIMEOUT_SECONDS)
            if not acquired:
                return {
                    "status": "blocked",
                    "operation": "delete",
                    "file": str(path),
                    "reason": "file lock busy",
                }
            try:
                path.unlink(missing_ok=True)
                return {"status": "ok", "operation": "delete", "file": str(path)}
            finally:
                lock.release()
        # Should never reach here — execute() validates operation first
        raise ValueError(f"Unhandled filesystem operation: {req.operation}")

    def _terminal_handler(self, req: PatchRequest) -> dict:
        """Run command in subprocess with timeout. Never shell=True."""
        argv = parse_command_argv(req.patch)
        if not argv:
            return {
                "status": "error",
                "returncode": -1,
                "stdout": "",
                "stderr": "empty command after parse",
            }
        if os.environ.get("SAGE_DOCKER_TOOLS") == "1":
            try:
                from sage.sim.docker_runner import run_command_in_container

                r = run_command_in_container(argv, cwd=Path.cwd(), timeout=self.MAX_COMMAND_TIME)
                return {
                    "status": "ok" if r.get("returncode") == 0 else "error",
                    "returncode": int(r.get("returncode", -1)),
                    "stdout": str(r.get("stdout") or ""),
                    "stderr": str(r.get("stderr") or ""),
                }
            except Exception as e:
                logger.warning("Docker tool runner failed, falling back to host: %s", e)

        result = subprocess.run(
            argv,
            timeout=self.MAX_COMMAND_TIME,
            capture_output=True,
            text=True,
            shell=False,  # NEVER shell=True
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
