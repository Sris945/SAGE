"""
SAGE Tool Registry
------------------
Defines every tool the coder/debugger agents can call inside the agentic loop.

Each tool has:
  - name: the JSON key the model emits
  - description: injected into the system prompt so the model understands it
  - schema: argument spec (for prompt injection + validation)
  - handler: Python callable that executes it and returns a string result

Usage:
    from sage.tools.tool_registry import ToolRegistry
    registry = ToolRegistry(workspace_root=Path.cwd())
    result = registry.dispatch({"tool": "read_file", "args": {"path": "src/main.py"}})
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sage.execution.workspace_policy import path_is_under_workspace


# ── Tool result ───────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    tool: str
    success: bool
    output: str          # shown to model verbatim (keep it concise)
    error: str = ""

    def to_message(self) -> str:
        if self.success:
            return f"[{self.tool}] OK\n{self.output}"
        return f"[{self.tool}] ERROR: {self.error}\n{self.output}"


# ── Tool descriptor ───────────────────────────────────────────────────────────

@dataclass
class ToolDescriptor:
    name: str
    description: str
    args_schema: dict[str, str]          # arg_name → short description
    handler: Callable[..., ToolResult]
    dangerous: bool = False              # requires extra safety check


# ── Registry ─────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Central tool registry.  Agents call dispatch() with a raw dict from the LLM.
    The registry validates args, enforces workspace policy, and runs the handler.
    """

    MAX_READ_BYTES = 128_000   # ~32K tokens — enough for any file
    MAX_GREP_RESULTS = 80
    MAX_FIND_RESULTS = 200
    MAX_CMD_TIME = 30          # seconds

    def __init__(self, workspace_roots: list[Path] | None = None) -> None:
        self._roots: tuple[Path, ...] = (
            tuple(Path(r).resolve() for r in workspace_roots)
            if workspace_roots
            else (Path.cwd().resolve(),)
        )
        self._tools: dict[str, ToolDescriptor] = {}
        self._todos: list[dict] = []
        self._register_all()

    # ── Public ────────────────────────────────────────────────────────────────

    def schema_prompt(self) -> str:
        """Return a compact tool-catalogue string to inject into system prompts."""
        lines: list[str] = ["AVAILABLE TOOLS (emit as JSON tool-call objects):\n"]
        for t in self._tools.values():
            args_desc = ", ".join(
                f'"{k}": {v}' for k, v in t.args_schema.items()
            )
            lines.append(f'  {{"tool": "{t.name}", "args": {{{args_desc}}}}}\n  → {t.description}\n')
        return "\n".join(lines)

    def dispatch(self, call: dict[str, Any]) -> ToolResult:
        """Execute one tool call dict emitted by the LLM."""
        name = (call.get("tool") or "").strip()
        args: dict = call.get("args") or {}

        if name == "done":
            return ToolResult(tool="done", success=True, output="Loop complete.")

        if name not in self._tools:
            known = ", ".join(self._tools)
            return ToolResult(
                tool=name, success=False, output="",
                error=f"Unknown tool {name!r}. Available: {known}",
            )

        descriptor = self._tools[name]
        try:
            return descriptor.handler(**args)
        except TypeError as exc:
            return ToolResult(
                tool=name, success=False, output="",
                error=f"Wrong arguments for {name}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool=name, success=False, output="",
                error=f"{type(exc).__name__}: {exc}",
            )

    def names(self) -> list[str]:
        return list(self._tools) + ["done"]

    # ── Registration ──────────────────────────────────────────────────────────

    def _register(self, descriptor: ToolDescriptor) -> None:
        self._tools[descriptor.name] = descriptor

    def _register_all(self) -> None:
        self._register(ToolDescriptor(
            name="read_file",
            description="Read the full content of a file (truncated at 128 KB).",
            args_schema={"path": "relative or absolute file path (string)"},
            handler=self._read_file,
        ))
        self._register(ToolDescriptor(
            name="list_directory",
            description="List files and directories at a given path (non-recursive).",
            args_schema={"path": "directory path (string, default '.')"},
            handler=self._list_directory,
        ))
        self._register(ToolDescriptor(
            name="find_files",
            description="Recursively find files matching a glob pattern.",
            args_schema={
                "pattern": "glob pattern (e.g. '**/*.py', 'src/**/*.ts')",
                "root": "search root directory (default '.')",
            },
            handler=self._find_files,
        ))
        self._register(ToolDescriptor(
            name="grep_code",
            description="Search file content for a regex pattern. Returns matching lines with file:line context.",
            args_schema={
                "pattern": "Python regex pattern to search for",
                "root": "directory to search under (default '.')",
                "include": "file glob filter (default '*.py')",
                "ignore_case": "true/false (default false)",
            },
            handler=self._grep_code,
        ))
        self._register(ToolDescriptor(
            name="write_file",
            description="Write (create or overwrite) a file with given content.",
            args_schema={
                "path": "file path (string)",
                "content": "full file content (string)",
            },
            handler=self._write_file,
            dangerous=False,
        ))
        self._register(ToolDescriptor(
            name="edit_file",
            description=(
                "Surgically replace EXACTLY ONE occurrence of old_string with new_string "
                "in an existing file. old_string must match character-for-character "
                "(including indentation). Fails if zero or multiple matches found."
            ),
            args_schema={
                "path": "file path (string)",
                "old_string": "exact text to replace — must be unique in the file",
                "new_string": "replacement text",
            },
            handler=self._edit_file,
        ))
        self._register(ToolDescriptor(
            name="delete_file",
            description="Delete a file. Irreversible — use with care.",
            args_schema={"path": "file path to delete"},
            handler=self._delete_file,
            dangerous=True,
        ))
        self._register(ToolDescriptor(
            name="run_command",
            description=(
                "Run a shell command in the workspace and return stdout+stderr. "
                "Use for: pytest, ruff, mypy, git status, pip install, etc. "
                "Blocked: rm -rf /, sudo, curl|bash."
            ),
            args_schema={
                "command": "command string (e.g. 'pytest tests/test_foo.py -x')",
                "timeout": "max seconds to wait (default 30, max 120)",
            },
            handler=self._run_command,
        ))
        self._register(ToolDescriptor(
            name="git_status",
            description="Show the current git status of the workspace.",
            args_schema={},
            handler=self._git_status,
        ))
        self._register(ToolDescriptor(
            name="git_diff",
            description="Show git diff for a file or all staged/unstaged changes.",
            args_schema={"path": "optional file path (string or empty for all)"},
            handler=self._git_diff,
        ))
        self._register(ToolDescriptor(
            name="git_add",
            description=(
                "Stage files for a git commit. Use before git_commit. "
                "Pass a list of paths or '.' to stage all changes."
            ),
            args_schema={"paths": "list of file paths to stage, or '.' for all (string or list)"},
            handler=self._git_add,
        ))
        self._register(ToolDescriptor(
            name="git_commit",
            description=(
                "Create a git commit with the staged changes. "
                "Stage files first with git_add. "
                "Only use when the user's goal explicitly involves committing code."
            ),
            args_schema={"message": "commit message (string)"},
            handler=self._git_commit,
            dangerous=False,
        ))
        self._register(ToolDescriptor(
            name="search_replace",
            description=(
                "Replace ALL occurrences of an exact string across multiple files matching "
                "a glob pattern. Useful for renaming a function, variable, or import site-wide. "
                "Returns count of replacements made and files changed."
            ),
            args_schema={
                "old_string": "exact text to replace (case-sensitive)",
                "new_string": "replacement text",
                "pattern": "file glob (e.g. '**/*.py', default '**/*.py')",
                "root": "search root directory (default '.')",
            },
            handler=self._search_replace,
        ))
        self._register(ToolDescriptor(
            name="todo_write",
            description=(
                "Write your task plan as a list of todo items. Call at the start of a task "
                "to break it into steps. Each item has a status: pending|in_progress|done. "
                "Call again to update statuses as you complete steps."
            ),
            args_schema={
                "todos": (
                    "list of objects: [{\"id\": \"1\", \"text\": \"step description\", "
                    "\"status\": \"pending\"}]"
                ),
            },
            handler=self._todo_write,
        ))
        self._register(ToolDescriptor(
            name="todo_read",
            description="Read the current todo list for this task.",
            args_schema={},
            handler=self._todo_read,
        ))

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _resolve(self, path: str, must_exist: bool = False) -> Path | None:
        """Resolve path, enforce workspace policy. Returns None on violation."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            # Anchor relative paths to the first workspace root (not cwd)
            p = next(iter(self._roots), Path.cwd()) / p
        p = p.resolve()
        if not path_is_under_workspace(p, self._roots):
            return None
        if must_exist and not p.exists():
            return None
        return p

    def _read_file(self, path: str) -> ToolResult:
        p = self._resolve(path, must_exist=True)
        if p is None:
            return ToolResult("read_file", False, "", f"File not found or outside workspace: {path!r}")
        try:
            raw = p.read_bytes()
            if len(raw) > self.MAX_READ_BYTES:
                text = raw[: self.MAX_READ_BYTES].decode("utf-8", errors="replace")
                text += f"\n… (truncated — file is {len(raw)} bytes, showing first {self.MAX_READ_BYTES})"
            else:
                text = raw.decode("utf-8", errors="replace")
            # Add line numbers — crucial for surgical edits
            lines = text.splitlines()
            numbered = "\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines))
            return ToolResult("read_file", True, f"=== {path} ({len(lines)} lines) ===\n{numbered}")
        except OSError as exc:
            return ToolResult("read_file", False, "", str(exc))

    def _list_directory(self, path: str = ".") -> ToolResult:
        p = self._resolve(path, must_exist=True)
        if p is None or not p.is_dir():
            return ToolResult("list_directory", False, "", f"Not a directory or outside workspace: {path!r}")
        try:
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
            lines = []
            for e in entries:
                if e.name.startswith("."):
                    continue
                kind = "/" if e.is_dir() else ""
                lines.append(f"  {e.name}{kind}")
            return ToolResult("list_directory", True, f"=== {path} ===\n" + "\n".join(lines))
        except OSError as exc:
            return ToolResult("list_directory", False, "", str(exc))

    def _find_files(self, pattern: str = "**/*.py", root: str = ".") -> ToolResult:
        r = self._resolve(root, must_exist=True)
        if r is None:
            return ToolResult("find_files", False, "", f"Root outside workspace: {root!r}")
        try:
            matches = sorted(str(p.relative_to(r)) for p in r.glob(pattern) if p.is_file())
            if len(matches) > self.MAX_FIND_RESULTS:
                matches = matches[: self.MAX_FIND_RESULTS]
                matches.append(f"… (truncated at {self.MAX_FIND_RESULTS} results)")
            return ToolResult("find_files", True, "\n".join(matches) if matches else "(no matches)")
        except Exception as exc:  # noqa: BLE001
            return ToolResult("find_files", False, "", str(exc))

    def _grep_code(
        self,
        pattern: str,
        root: str = ".",
        include: str = "*.py",
        ignore_case: bool | str = False,
    ) -> ToolResult:
        r = self._resolve(root, must_exist=True)
        if r is None:
            return ToolResult("grep_code", False, "", f"Root outside workspace: {root!r}")
        flags = re.IGNORECASE if str(ignore_case).lower() in ("true", "1", "yes") else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as exc:
            return ToolResult("grep_code", False, "", f"Bad regex: {exc}")

        results: list[str] = []
        for fpath in sorted(r.rglob(include)):
            if not fpath.is_file():
                continue
            # Skip hidden dirs and vendor dirs
            if any(part.startswith(".") or part in ("__pycache__", "node_modules", ".venv")
                   for part in fpath.parts):
                continue
            try:
                for lineno, line in enumerate(fpath.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        rel = str(fpath.relative_to(r))
                        results.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(results) >= self.MAX_GREP_RESULTS:
                            results.append(f"… (stopped at {self.MAX_GREP_RESULTS} matches)")
                            return ToolResult("grep_code", True, "\n".join(results))
            except OSError:
                continue

        if not results:
            return ToolResult("grep_code", True, f"(no matches for {pattern!r} in {include} under {root})")
        return ToolResult("grep_code", True, "\n".join(results))

    def _write_file(self, path: str, content: str) -> ToolResult:
        p = self._resolve(path)
        if p is None:
            return ToolResult("write_file", False, "", f"Path outside workspace: {path!r}")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            lines = content.count("\n") + 1
            return ToolResult("write_file", True, f"Wrote {lines} lines to {path}")
        except OSError as exc:
            return ToolResult("write_file", False, "", str(exc))

    def _edit_file(self, path: str, old_string: str, new_string: str) -> ToolResult:
        """Surgical single-occurrence replacement — the core of precision editing."""
        p = self._resolve(path, must_exist=True)
        if p is None:
            return ToolResult("edit_file", False, "", f"File not found or outside workspace: {path!r}")
        if not old_string:
            return ToolResult("edit_file", False, "", "old_string must not be empty")
        try:
            original = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult("edit_file", False, "", str(exc))

        count = original.count(old_string)
        if count == 0:
            # Give the model a helpful hint — show nearby lines so it can re-anchor
            snippet = _find_nearest_lines(original, old_string[:60])
            hint = f"\nNearest content:\n{snippet}" if snippet else ""
            return ToolResult(
                "edit_file", False, "",
                f"old_string not found in {path}. Check indentation and whitespace.{hint}",
            )
        if count > 1:
            # Help the model widen the context to make the match unique
            occurrences = _find_occurrence_contexts(original, old_string)
            return ToolResult(
                "edit_file", False, "",
                f"old_string matches {count} locations in {path} — it must be unique. "
                f"Add surrounding lines to disambiguate.\nOccurrences at lines: {occurrences}",
            )

        new_content = original.replace(old_string, new_string, 1)
        try:
            p.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return ToolResult("edit_file", False, "", str(exc))

        # Report the diff compactly
        old_lines = old_string.count("\n") + 1
        new_lines = new_string.count("\n") + 1
        return ToolResult(
            "edit_file", True,
            f"Replaced {old_lines}-line block with {new_lines}-line block in {path}",
        )

    def _delete_file(self, path: str) -> ToolResult:
        p = self._resolve(path, must_exist=True)
        if p is None:
            return ToolResult("delete_file", False, "", f"Not found or outside workspace: {path!r}")
        try:
            p.unlink()
            return ToolResult("delete_file", True, f"Deleted {path}")
        except OSError as exc:
            return ToolResult("delete_file", False, "", str(exc))

    def _run_command(self, command: str, timeout: int | str = 30) -> ToolResult:
        from sage.execution.tool_policy import check_run_command_policy, parse_command_argv
        from sage.execution.exceptions import SafetyViolation

        try:
            check_run_command_policy(command)
        except SafetyViolation as exc:
            return ToolResult("run_command", False, "", f"Blocked: {exc}")

        try:
            max_t = min(int(timeout), 120)
        except (ValueError, TypeError):
            max_t = 30

        argv = parse_command_argv(command)
        if not argv:
            return ToolResult("run_command", False, "", "Empty command")
        try:
            r = subprocess.run(
                argv, capture_output=True, text=True, timeout=max_t, shell=False,
                cwd=str(next(iter(self._roots), Path.cwd())),
            )
            out = r.stdout + r.stderr
            if len(out) > 8000:
                out = out[-8000:]  # keep tail (recent output is more useful)
            status = "ok" if r.returncode == 0 else f"exit {r.returncode}"
            return ToolResult("run_command", r.returncode == 0, out, "" if r.returncode == 0 else status)
        except subprocess.TimeoutExpired:
            return ToolResult("run_command", False, "", f"Timed out after {max_t}s")
        except (OSError, FileNotFoundError) as exc:
            return ToolResult("run_command", False, "", str(exc))

    def _git_status(self) -> ToolResult:
        try:
            r = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=8,
                cwd=str(next(iter(self._roots), Path.cwd())),
            )
            return ToolResult("git_status", True, r.stdout.strip() or "(clean)")
        except OSError as exc:
            return ToolResult("git_status", False, "", str(exc))

    def _git_diff(self, path: str = "") -> ToolResult:
        cmd = ["git", "diff"]
        if path:
            p = self._resolve(path)
            if p is not None:
                cmd.append(str(p))
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                cwd=str(next(iter(self._roots), Path.cwd())),
            )
            out = r.stdout[:8000] or "(no diff)"
            return ToolResult("git_diff", True, out)
        except OSError as exc:
            return ToolResult("git_diff", False, "", str(exc))

    def _git_add(self, paths: "str | list[str]" = ".") -> ToolResult:
        cwd = str(next(iter(self._roots), Path.cwd()))
        if isinstance(paths, str):
            paths = [paths]
        resolved: list[str] = []
        for p in paths:
            if p.strip() == ".":
                resolved.append(".")
            else:
                rp = self._resolve(p)
                if rp is None:
                    return ToolResult("git_add", False, "", f"Path outside workspace: {p}")
                resolved.append(str(rp))
        try:
            r = subprocess.run(
                ["git", "add"] + resolved,
                capture_output=True, text=True, timeout=15, cwd=cwd,
            )
            if r.returncode != 0:
                return ToolResult("git_add", False, r.stdout, r.stderr.strip())
            return ToolResult("git_add", True, f"Staged: {', '.join(resolved)}")
        except OSError as exc:
            return ToolResult("git_add", False, "", str(exc))

    def _git_commit(self, message: str) -> ToolResult:
        if not message or not message.strip():
            return ToolResult("git_commit", False, "", "Commit message must not be empty")
        cwd = str(next(iter(self._roots), Path.cwd()))
        try:
            r = subprocess.run(
                ["git", "commit", "-m", message.strip()],
                capture_output=True, text=True, timeout=30, cwd=cwd,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                return ToolResult("git_commit", False, out, f"exit {r.returncode}")
            return ToolResult("git_commit", True, out)
        except OSError as exc:
            return ToolResult("git_commit", False, "", str(exc))

    def _search_replace(
        self,
        old_string: str,
        new_string: str,
        pattern: str = "**/*.py",
        root: str = ".",
    ) -> ToolResult:
        if not old_string:
            return ToolResult("search_replace", False, "", "old_string must not be empty")
        base = Path(root).resolve() if root != "." else self._roots[0]
        if not path_is_under_workspace(base, self._roots):
            return ToolResult("search_replace", False, "", f"root outside workspace: {root}")
        replacements = 0
        changed_files: list[str] = []
        for path in sorted(base.rglob(pattern.lstrip("/"))):
            if not path.is_file():
                continue
            if not path_is_under_workspace(path, self._roots):
                continue
            try:
                original = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            count = original.count(old_string)
            if count == 0:
                continue
            path.write_text(original.replace(old_string, new_string), encoding="utf-8")
            replacements += count
            changed_files.append(str(path.relative_to(base)))
        if replacements == 0:
            return ToolResult("search_replace", True, "0 replacements — string not found")
        summary = (
            f"{replacements} replacement(s) in {len(changed_files)} file(s):\n"
            + "\n".join(f"  {f}" for f in changed_files)
        )
        return ToolResult("search_replace", True, summary)

    def _todo_write(self, todos: list) -> ToolResult:
        if not isinstance(todos, list):
            return ToolResult("todo_write", False, "", "todos must be a list")
        validated: list[dict] = []
        for item in todos:
            if not isinstance(item, dict):
                return ToolResult("todo_write", False, "", f"each todo must be an object, got {type(item)}")
            tid = str(item.get("id", len(validated) + 1))
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending"))
            if status not in {"pending", "in_progress", "done"}:
                status = "pending"
            validated.append({"id": tid, "text": text, "status": status})
        self._todos = validated
        lines = [_fmt_todo(t) for t in self._todos]
        return ToolResult("todo_write", True, "Todo list updated:\n" + "\n".join(lines))

    def _todo_read(self) -> ToolResult:
        if not self._todos:
            return ToolResult("todo_read", True, "(no todos yet)")
        lines = [_fmt_todo(t) for t in self._todos]
        return ToolResult("todo_read", True, "\n".join(lines))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_nearest_lines(text: str, fragment: str, context: int = 3) -> str:
    """Find the closest lines to fragment for error hints."""
    fragment_clean = fragment.strip()
    lines = text.splitlines()
    best_score = 0
    best_idx = -1
    for i, line in enumerate(lines):
        common = sum(c1 == c2 for c1, c2 in zip(line.strip(), fragment_clean))
        if common > best_score:
            best_score = common
            best_idx = i
    if best_idx < 0:
        return ""
    start = max(0, best_idx - context)
    end = min(len(lines), best_idx + context + 1)
    return "\n".join(f"{i+1:4d} | {lines[i]}" for i in range(start, end))


def _find_occurrence_contexts(text: str, substring: str) -> list[int]:
    """Return 1-based line numbers where substring starts."""
    lines = text.splitlines()
    result = []
    cumulative = 0
    for i, line in enumerate(lines):
        start = 0
        while True:
            idx = line.find(substring, start)
            if idx < 0:
                break
            result.append(i + 1)
            start = idx + 1
        if len(result) >= 10:
            break
    return result


def _fmt_todo(todo: dict) -> str:
    icons = {"done": "[x]", "in_progress": "[~]", "pending": "[ ]"}
    icon = icons.get(todo.get("status", "pending"), "[ ]")
    return f"{icon} {todo.get('id', '?')}. {todo.get('text', '')}"
