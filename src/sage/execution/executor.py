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

from sage.debug_mode_log import agent_debug_log
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

    _GIT_OPS = frozenset(("git_commit", "git_diff", "git_log", "git_branch", "git_status"))

    def execute(self, req: PatchRequest, mode: str = "auto") -> dict:
        # Normalise — model sometimes emits enum descriptions like "create | edit | delete"
        op: str = req.operation.split("|")[0].strip().lower()
        req.operation = op  # type: ignore[assignment]
        # Feature 4: pre-execution destructive-op guard.
        if self._is_destructive(req) and mode == "research":
            return {
                "status": "needs_confirmation",
                "reason": f"Destructive operation pending: {req.operation} on {req.file}",
                "req_summary": {"op": req.operation, "file": req.file},
            }
        self._safety_check(req)
        if req.operation in ("edit", "create", "delete"):
            out = self._filesystem_handler(req)
        elif req.operation == "run_command":
            out = self._terminal_handler(req)
        elif req.operation in self._GIT_OPS:
            out = self._git_op(req)
        else:
            raise ValueError(f"Unknown operation: {req.operation}")
        agent_debug_log(
            hypothesis_id="H_exec",
            location="executor.py:execute",
            message="patch_executed",
            data={
                "operation": req.operation,
                "file": str(req.file),
                "status": out.get("status"),
                "returncode": out.get("returncode"),
                "patch_len": len(req.patch or ""),
            },
        )
        return out

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

    def _is_destructive(self, req: PatchRequest) -> bool:
        """Returns True if this operation is destructive and needs pre-confirmation."""
        if req.operation == "delete":
            return True
        if req.operation == "run_command":
            cmd = (req.patch or "").lower()
            return any(
                k in cmd
                for k in (
                    "rm -rf",
                    "rm -f",
                    "drop table",
                    "truncate ",
                    "git push --force",
                    "> /dev/null",
                    "| sudo",
                )
            )
        return False

    def _git_op(self, req: PatchRequest) -> dict:
        """Route git operations from PatchRequest to git_tools functions."""
        from sage.execution.git_tools import (
            git_branch,
            git_commit,
            git_diff,
            git_log,
            git_status,
        )

        # Determine repo_path: use req.file as the repo root if it looks like a dir,
        # otherwise fall back to current working directory.
        import os

        repo_path = str(req.file or "") or os.getcwd()
        if not os.path.isdir(repo_path):
            repo_path = os.getcwd()

        op = req.operation
        patch = req.patch or ""

        if op == "git_status":
            return git_status(repo_path)

        if op == "git_diff":
            staged = "staged" in patch.lower()
            file_arg = str(req.file) if req.file and os.path.isfile(str(req.file)) else None
            return git_diff(repo_path, file=file_arg, staged=staged)

        if op == "git_log":
            n = 10
            for part in patch.split():
                if part.startswith("n="):
                    try:
                        n = int(part[2:])
                    except ValueError:
                        pass
            return git_log(repo_path, n=n)

        if op == "git_branch":
            branch_name = str(req.file).strip() if req.file else None
            create = patch.strip().lower() == "create"
            return git_branch(repo_path, name=branch_name or None, create=create)

        if op == "git_commit":
            message = patch or "SAGE auto-commit"
            files_raw = str(req.file) if req.file else ""
            files = [f.strip() for f in files_raw.split(",") if f.strip()] if files_raw else None
            return git_commit(repo_path, message=message, files=files)

        return {"status": "error", "stderr": f"Unknown git operation: {op}"}

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
