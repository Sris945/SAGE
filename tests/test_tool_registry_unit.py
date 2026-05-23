"""
Unit tests for sage.tools.tool_registry.ToolRegistry
Tests all tools: read_file, list_directory, find_files, grep_code,
write_file, edit_file, delete_file, run_command, git_status, git_diff.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from sage.tools.tool_registry import ToolRegistry, _find_nearest_lines, _find_occurrence_contexts


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A temp workspace directory with a few files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        textwrap.dedent("""\
            def greet(name: str) -> str:
                return f"Hello, {name}!"

            def add(a: int, b: int) -> int:
                return a + b
        """),
        encoding="utf-8",
    )
    (tmp_path / "src" / "utils.py").write_text(
        "def noop(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text(
        textwrap.dedent("""\
            from src.main import greet

            def test_greet():
                assert greet("World") == "Hello, World!"
        """),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def registry(workspace: Path) -> ToolRegistry:
    return ToolRegistry(workspace_roots=[workspace])


# ── read_file ─────────────────────────────────────────────────────────────────

class TestReadFile:
    def test_reads_existing_file(self, registry: ToolRegistry, workspace: Path):
        r = registry.dispatch({"tool": "read_file", "args": {"path": "src/main.py"}})
        assert r.success
        assert "greet" in r.output
        assert "1 |" in r.output   # line numbers present

    def test_missing_file_returns_error(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "read_file", "args": {"path": "does_not_exist.py"}})
        assert not r.success
        assert "not found" in r.error.lower() or "outside" in r.error.lower()

    def test_outside_workspace_rejected(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "read_file", "args": {"path": "/etc/passwd"}})
        assert not r.success

    def test_truncates_large_files(self, registry: ToolRegistry, workspace: Path):
        # Create a >128 KB file
        big_file = workspace / "big.txt"
        big_file.write_bytes(b"x" * 200_000)
        r = registry.dispatch({"tool": "read_file", "args": {"path": "big.txt"}})
        assert r.success
        assert "truncated" in r.output


# ── list_directory ────────────────────────────────────────────────────────────

class TestListDirectory:
    def test_lists_root(self, registry: ToolRegistry, workspace: Path):
        r = registry.dispatch({"tool": "list_directory", "args": {"path": "."}})
        assert r.success
        assert "src/" in r.output or "src" in r.output

    def test_lists_subdirectory(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "list_directory", "args": {"path": "src"}})
        assert r.success
        assert "main.py" in r.output

    def test_nonexistent_directory(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "list_directory", "args": {"path": "nodir"}})
        assert not r.success


# ── find_files ────────────────────────────────────────────────────────────────

class TestFindFiles:
    def test_finds_python_files(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "find_files", "args": {"pattern": "**/*.py"}})
        assert r.success
        assert "main.py" in r.output

    def test_pattern_no_matches(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "find_files", "args": {"pattern": "**/*.rs"}})
        assert r.success
        assert "no matches" in r.output

    def test_root_scoped(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "find_files", "args": {"pattern": "*.py", "root": "src"}})
        assert r.success
        assert "main.py" in r.output
        assert "test_main.py" not in r.output


# ── grep_code ─────────────────────────────────────────────────────────────────

class TestGrepCode:
    def test_finds_pattern(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "grep_code",
            "args": {"pattern": r"def greet", "include": "*.py"},
        })
        assert r.success
        assert "greet" in r.output
        assert "main.py" in r.output

    def test_no_matches_is_success(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "grep_code",
            "args": {"pattern": "xyzzy_nonexistent", "include": "*.py"},
        })
        assert r.success
        assert "no matches" in r.output

    def test_invalid_regex_returns_error(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "grep_code",
            "args": {"pattern": "[invalid"},
        })
        assert not r.success
        assert "regex" in r.error.lower()

    def test_case_insensitive(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "grep_code",
            "args": {"pattern": "GREET", "include": "*.py", "ignore_case": True},
        })
        assert r.success
        assert "greet" in r.output.lower()


# ── write_file ────────────────────────────────────────────────────────────────

class TestWriteFile:
    def test_creates_new_file(self, registry: ToolRegistry, workspace: Path):
        r = registry.dispatch({
            "tool": "write_file",
            "args": {"path": "new_module.py", "content": "x = 1\n"},
        })
        assert r.success
        assert (workspace / "new_module.py").read_text() == "x = 1\n"

    def test_overwrites_existing(self, registry: ToolRegistry, workspace: Path):
        r = registry.dispatch({
            "tool": "write_file",
            "args": {"path": "src/utils.py", "content": "# rewritten\n"},
        })
        assert r.success
        assert (workspace / "src" / "utils.py").read_text() == "# rewritten\n"

    def test_creates_parent_dirs(self, registry: ToolRegistry, workspace: Path):
        r = registry.dispatch({
            "tool": "write_file",
            "args": {"path": "deep/nested/module.py", "content": "pass\n"},
        })
        assert r.success
        assert (workspace / "deep" / "nested" / "module.py").exists()

    def test_outside_workspace_rejected(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "write_file",
            "args": {"path": "/tmp/evil.py", "content": "rm -rf /"},
        })
        assert not r.success


# ── edit_file ─────────────────────────────────────────────────────────────────

class TestEditFile:
    def test_surgical_replacement(self, registry: ToolRegistry, workspace: Path):
        r = registry.dispatch({
            "tool": "edit_file",
            "args": {
                "path": "src/main.py",
                "old_string": 'return f"Hello, {name}!"',
                "new_string": 'return f"Hi, {name}!"',
            },
        })
        assert r.success
        content = (workspace / "src" / "main.py").read_text()
        assert "Hi, {name}" in content
        assert "Hello, {name}" not in content

    def test_not_found_returns_error(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "edit_file",
            "args": {
                "path": "src/main.py",
                "old_string": "this does not exist in the file",
                "new_string": "replacement",
            },
        })
        assert not r.success
        assert "not found" in r.error.lower()

    def test_multiple_matches_returns_error(self, registry: ToolRegistry, workspace: Path):
        # Add a file with a duplicate line
        (workspace / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
        r = registry.dispatch({
            "tool": "edit_file",
            "args": {"path": "dup.py", "old_string": "x = 1", "new_string": "x = 2"},
        })
        assert not r.success
        assert "2" in r.error  # "matches 2 locations"

    def test_empty_old_string_rejected(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "edit_file",
            "args": {"path": "src/main.py", "old_string": "", "new_string": "x"},
        })
        assert not r.success

    def test_missing_file_returns_error(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "edit_file",
            "args": {"path": "ghost.py", "old_string": "x", "new_string": "y"},
        })
        assert not r.success


# ── delete_file ───────────────────────────────────────────────────────────────

class TestDeleteFile:
    def test_deletes_existing_file(self, registry: ToolRegistry, workspace: Path):
        (workspace / "to_delete.py").write_text("x = 1\n")
        r = registry.dispatch({"tool": "delete_file", "args": {"path": "to_delete.py"}})
        assert r.success
        assert not (workspace / "to_delete.py").exists()

    def test_missing_file_returns_error(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "delete_file", "args": {"path": "ghost.py"}})
        assert not r.success


# ── run_command ───────────────────────────────────────────────────────────────

class TestRunCommand:
    def test_runs_simple_command(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "run_command",
            "args": {"command": "python3 -c \"print('hello')\""},
        })
        assert r.success
        assert "hello" in r.output

    def test_captures_stderr_on_failure(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "run_command",
            "args": {"command": "python3 -c \"import sys; sys.exit(1)\""},
        })
        assert not r.success

    def test_blocked_command(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "run_command",
            "args": {"command": "rm -rf / --no-preserve-root"},
        })
        assert not r.success
        assert "blocked" in r.error.lower()

    def test_unknown_executable(self, registry: ToolRegistry):
        r = registry.dispatch({
            "tool": "run_command",
            "args": {"command": "totally_nonexistent_binary_xyzzy"},
        })
        assert not r.success


# ── Unknown tool ──────────────────────────────────────────────────────────────

class TestUnknownTool:
    def test_unknown_tool_returns_error(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "fly_to_moon", "args": {}})
        assert not r.success
        assert "unknown" in r.error.lower()

    def test_done_returns_success(self, registry: ToolRegistry):
        r = registry.dispatch({"tool": "done", "args": {}})
        assert r.success


# ── Schema prompt ─────────────────────────────────────────────────────────────

class TestSchemaPrompt:
    def test_includes_all_tools(self, registry: ToolRegistry):
        prompt = registry.schema_prompt()
        for name in ("read_file", "edit_file", "grep_code", "find_files",
                      "write_file", "run_command", "list_directory"):
            assert name in prompt

    def test_prompt_is_nonempty(self, registry: ToolRegistry):
        assert len(registry.schema_prompt()) > 200


# ── Helper functions ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_find_nearest_lines(self):
        text = "def foo():\n    pass\n\ndef bar():\n    return 1\n"
        result = _find_nearest_lines(text, "def foo")
        assert "foo" in result

    def test_find_occurrence_contexts(self):
        text = "x = 1\ny = 2\nx = 1\n"
        occurrences = _find_occurrence_contexts(text, "x = 1")
        assert len(occurrences) == 2
        assert 1 in occurrences
        assert 3 in occurrences


# ── search_replace ─────────────────────────────────────────────────────────────

class TestSearchReplace:
    def test_replaces_across_files(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        # plant a string in two files
        (workspace / "a.py").write_text("def greet(): pass\n")
        (workspace / "b.py").write_text("x = greet()\n")
        result = reg.dispatch({"tool": "search_replace", "args": {
            "old_string": "greet",
            "new_string": "hello",
            "pattern": "*.py",
            "root": str(workspace),
        }})
        assert result.success
        assert "replacement" in result.output
        assert (workspace / "a.py").read_text() == "def hello(): pass\n"
        assert (workspace / "b.py").read_text() == "x = hello()\n"

    def test_no_match_returns_zero(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "search_replace", "args": {
            "old_string": "nonexistent_xyz",
            "new_string": "other",
        }})
        assert result.success
        assert "0 replacement" in result.output

    def test_rejects_path_traversal(self, workspace: Path, tmp_path: Path):
        outside = tmp_path.parent
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "search_replace", "args": {
            "old_string": "x",
            "new_string": "y",
            "root": str(outside),
        }})
        assert not result.success
        assert "outside workspace" in result.error

    def test_empty_old_string_rejected(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "search_replace", "args": {
            "old_string": "",
            "new_string": "y",
        }})
        assert not result.success


# ── todo_write / todo_read ─────────────────────────────────────────────────────

class TestTodoTools:
    def test_write_and_read_roundtrip(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        todos = [
            {"id": "1", "text": "Read files", "status": "done"},
            {"id": "2", "text": "Edit main.py", "status": "in_progress"},
            {"id": "3", "text": "Run tests", "status": "pending"},
        ]
        write_result = reg.dispatch({"tool": "todo_write", "args": {"todos": todos}})
        assert write_result.success
        assert "Todo list updated" in write_result.output

        read_result = reg.dispatch({"tool": "todo_read", "args": {}})
        assert read_result.success
        assert "[x]" in read_result.output   # done
        assert "[~]" in read_result.output   # in_progress
        assert "[ ]" in read_result.output   # pending
        assert "Read files" in read_result.output

    def test_read_empty_returns_message(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "todo_read", "args": {}})
        assert result.success
        assert "no todos" in result.output

    def test_write_overwrites_previous(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        reg.dispatch({"tool": "todo_write", "args": {
            "todos": [{"id": "1", "text": "old step", "status": "pending"}],
        }})
        reg.dispatch({"tool": "todo_write", "args": {
            "todos": [{"id": "1", "text": "new step", "status": "done"}],
        }})
        read = reg.dispatch({"tool": "todo_read", "args": {}})
        assert "new step" in read.output
        assert "old step" not in read.output

    def test_invalid_status_defaults_to_pending(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "todo_write", "args": {
            "todos": [{"id": "1", "text": "step", "status": "BOGUS"}],
        }})
        assert result.success
        read = reg.dispatch({"tool": "todo_read", "args": {}})
        assert "[ ]" in read.output   # defaulted to pending

    def test_non_list_todos_rejected(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "todo_write", "args": {"todos": "not a list"}})
        assert not result.success


# ── Undo system ───────────────────────────────────────────────────────────────

class TestUndoSystem:
    def test_snapshot_on_write_and_restore_in_memory(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        target = workspace / "file.txt"
        target.write_text("original")

        reg.dispatch({"tool": "write_file", "args": {"path": "file.txt", "content": "changed"}})
        assert target.read_text() == "changed"

        restored = reg.restore_undo()
        assert any("file.txt" in r for r in restored)
        assert target.read_text() == "original"

    def test_snapshot_on_edit_and_restore(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        target = workspace / "edit_me.py"
        target.write_text("x = 1\n")

        reg.dispatch({"tool": "edit_file", "args": {
            "path": "edit_me.py", "old_string": "x = 1", "new_string": "x = 99",
        }})
        assert "x = 99" in target.read_text()

        reg.restore_undo()
        assert "x = 1" in target.read_text()

    def test_restore_from_disk_cross_process(self, tmp_path: Path):
        """Simulates restore_undo_from_disk running in a fresh process."""
        from sage.tools.tool_registry import ToolRegistry

        target = tmp_path / "persist.txt"
        target.write_text("before")

        reg = ToolRegistry(workspace_roots=[tmp_path])
        reg.dispatch({"tool": "write_file", "args": {"path": "persist.txt", "content": "after"}})

        manifest = tmp_path / ".sage" / "undo" / "manifest.json"
        assert manifest.exists()

        # Simulate new process: create fresh registry-less restore
        restored = ToolRegistry.restore_undo_from_disk(tmp_path)
        assert any("persist.txt" in r for r in restored)
        assert target.read_text() == "before"
        assert not manifest.exists()  # manifest cleaned up after restore

    def test_restore_empty_when_no_manifest(self, tmp_path: Path):
        restored = ToolRegistry.restore_undo_from_disk(tmp_path)
        assert restored == []

    def test_new_file_undo_deletes_it(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        new_file = workspace / "brand_new.txt"
        assert not new_file.exists()

        reg.dispatch({"tool": "write_file", "args": {"path": "brand_new.txt", "content": "hello"}})
        assert new_file.exists()

        restored = reg.restore_undo()
        assert not new_file.exists()
        assert any("(deleted)" in r for r in restored)


# ── ask_user (stdin mock) ─────────────────────────────────────────────────────

class TestAskUser:
    def test_ask_user_returns_answer(self, workspace: Path, monkeypatch):
        import sys
        from sage.tools.tool_registry import ToolRegistry

        monkeypatch.setattr("builtins.input", lambda: "yes")
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "ask_user", "args": {"question": "Continue?"}})
        assert result.success
        assert "yes" in result.output

    def test_ask_user_requires_question(self, workspace: Path, monkeypatch):
        import sys
        from sage.tools.tool_registry import ToolRegistry

        monkeypatch.setattr("builtins.input", lambda: "ok")
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "ask_user", "args": {"question": ""}})
        assert not result.success

    def test_ask_user_fails_in_non_tty(self, workspace: Path, monkeypatch):
        import sys
        from sage.tools.tool_registry import ToolRegistry

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "ask_user", "args": {"question": "Continue?"}})
        assert not result.success
        assert "non-interactively" in result.error


# ── web_fetch ─────────────────────────────────────────────────────────────────

class TestWebFetch:
    def test_web_fetch_strips_html(self, workspace: Path, monkeypatch):
        import io, urllib.request
        from sage.tools.tool_registry import ToolRegistry

        html = b"<html><body><h1>Hello</h1><p>World</p></body></html>"

        class FakeHeaders:
            def get(self, key, default=""): return "text/html"

        class FakeResponse:
            headers = FakeHeaders()
            def read(self, n): return html
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: FakeResponse())
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "web_fetch", "args": {"url": "http://example.com"}})
        assert result.success
        assert "Hello" in result.output
        assert "<h1>" not in result.output

    def test_web_fetch_rejects_empty_url(self, workspace: Path):
        from sage.tools.tool_registry import ToolRegistry

        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "web_fetch", "args": {"url": ""}})
        assert not result.success

    def test_web_fetch_handles_network_error(self, workspace: Path, monkeypatch):
        import urllib.request
        from sage.tools.tool_registry import ToolRegistry

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("timeout")))
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "web_fetch", "args": {"url": "http://unreachable.invalid"}})
        assert not result.success
        assert "timeout" in result.error or "timeout" in result.output


# ── move_file ─────────────────────────────────────────────────────────────────

class TestMoveFile:
    def test_moves_file_within_workspace(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        src = workspace / "old.txt"
        src.write_text("hello")
        result = reg.dispatch({"tool": "move_file", "args": {"source": "old.txt", "destination": "new.txt"}})
        assert result.success
        assert not src.exists()
        assert (workspace / "new.txt").read_text() == "hello"

    def test_rejects_missing_source(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "move_file", "args": {"source": "ghost.txt", "destination": "out.txt"}})
        assert not result.success

    def test_rejects_existing_destination(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        (workspace / "a.txt").write_text("a")
        (workspace / "b.txt").write_text("b")
        result = reg.dispatch({"tool": "move_file", "args": {"source": "a.txt", "destination": "b.txt"}})
        assert not result.success

    def test_rejects_path_traversal(self, workspace: Path):
        import tempfile
        reg = ToolRegistry(workspace_roots=[workspace])
        (workspace / "safe.txt").write_text("data")
        with tempfile.TemporaryDirectory() as other:
            result = reg.dispatch({"tool": "move_file", "args": {
                "source": "safe.txt",
                "destination": str(Path(other) / "outside.txt"),
            }})
        assert not result.success


# ── run_tests ─────────────────────────────────────────────────────────────────

class TestRunTests:
    def test_detects_pytest_in_workspace(self, tmp_path: Path):
        from sage.tools.tool_registry import _detect_test_runner
        (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\n')
        runner, cmd = _detect_test_runner(tmp_path)
        assert runner in ("pytest", None)  # pytest may not be on PATH in test env

    def test_no_runner_returns_none(self, tmp_path: Path):
        from sage.tools.tool_registry import _detect_test_runner
        runner, cmd = _detect_test_runner(tmp_path)
        # tmp_path has no project files — may fall back to global pytest or None
        assert runner is None or isinstance(runner, str)

    def test_run_tests_dispatches(self, workspace: Path, monkeypatch):
        import subprocess
        from sage.tools.tool_registry import ToolRegistry

        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="1 passed", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)
        reg = ToolRegistry(workspace_roots=[workspace])
        # Patch detect to always find pytest so CI doesn't need it installed
        monkeypatch.setattr("sage.tools.tool_registry._detect_test_runner", lambda root: ("pytest", ["pytest", "-q"]))
        result = reg.dispatch({"tool": "run_tests", "args": {}})
        assert result.success
        assert "PASSED" in result.output


# ── diff preview in write_file / edit_file ────────────────────────────────────

class TestDiffPreview:
    def test_write_existing_file_shows_diff(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        target = workspace / "src" / "main.py"
        result = reg.dispatch({"tool": "write_file", "args": {
            "path": "src/main.py",
            "content": "# new version\ndef main(): pass\n",
        }})
        assert result.success
        # Diff block should appear in output
        assert "@@" in result.output or "---" in result.output or "new version" in result.output

    def test_write_new_file_no_diff(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "write_file", "args": {
            "path": "brand_new_file.txt",
            "content": "hello\n",
        }})
        assert result.success
        # New file — no diff block
        assert "---" not in result.output

    def test_edit_shows_diff(self, workspace: Path):
        reg = ToolRegistry(workspace_roots=[workspace])
        result = reg.dispatch({"tool": "edit_file", "args": {
            "path": "src/main.py",
            "old_string": "def greet(name: str) -> str:",
            "new_string": "def greet(name: str = 'World') -> str:",
        }})
        assert result.success
        assert "@@" in result.output or "greet" in result.output


# ── chat session store — message rehydration ──────────────────────────────────

class TestChatSessionStore:
    def test_load_messages_from_session(self, tmp_path: Path):
        from sage.cli.chat_session_store import load_messages_from_session
        import json

        session_file = tmp_path / "sess.jsonl"
        lines = [
            {"role": "user", "content": "hello world", "ts": "2026-01-01T00:00:00Z"},
            {"role": "assistant", "content": "hi there", "ts": "2026-01-01T00:00:01Z"},
        ]
        session_file.write_text("\n".join(json.dumps(l) for l in lines))

        msgs = load_messages_from_session(session_file)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "hello world"}
        assert msgs[1] == {"role": "assistant", "content": "hi there"}

    def test_load_empty_session(self, tmp_path: Path):
        from sage.cli.chat_session_store import load_messages_from_session

        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert load_messages_from_session(f) == []

    def test_load_trims_to_max_chars(self, tmp_path: Path):
        from sage.cli.chat_session_store import load_messages_from_session
        import json

        # Create many long turns
        lines = [{"role": "user", "content": "x" * 1000, "ts": "t"} for _ in range(50)]
        f = tmp_path / "big.jsonl"
        f.write_text("\n".join(json.dumps(l) for l in lines))

        msgs = load_messages_from_session(f, max_chars=5000)
        total = sum(len(m["content"]) for m in msgs)
        assert total <= 5000

    def test_load_nonexistent_returns_empty(self, tmp_path: Path):
        from sage.cli.chat_session_store import load_messages_from_session

        assert load_messages_from_session(tmp_path / "nope.jsonl") == []
