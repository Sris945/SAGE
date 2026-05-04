"""
Unit tests for sage.execution.tool_loop.ToolLoopEngine
Tests the agentic loop: parse errors, tool execution, done signal,
max_turns cap, mutation tracking, and system prompt building.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sage.execution.tool_loop import (
    ToolLoopEngine,
    LoopResult,
    _parse_tool_call,
    _stream_turn,
    build_system_prompt,
    make_ollama_chat_fn,
)
from sage.tools.tool_registry import ToolResult
from sage.tools.tool_registry import ToolRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("def hi(): return 'hi'\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def registry(workspace: Path) -> ToolRegistry:
    return ToolRegistry(workspace_roots=[workspace])


def _make_engine(responses: list[str], registry: ToolRegistry, max_turns: int = 10) -> ToolLoopEngine:
    """Create an engine whose chat_fn cycles through provided responses."""
    call_count = [0]

    def fake_chat(messages, model, options):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]

    return ToolLoopEngine(
        registry=registry,
        chat_fn=fake_chat,
        model="test-model",
        max_turns=max_turns,
    )


# ── _parse_tool_call ──────────────────────────────────────────────────────────

class TestParseToolCall:
    def test_parses_valid_json(self):
        call, err = _parse_tool_call('{"tool": "read_file", "args": {"path": "x.py"}}')
        assert err == ""
        assert call["tool"] == "read_file"
        assert call["args"]["path"] == "x.py"

    def test_handles_prose_around_json(self):
        raw = 'I will read the file: {"tool": "read_file", "args": {"path": "x.py"}} done.'
        call, err = _parse_tool_call(raw)
        assert err == ""
        assert call["tool"] == "read_file"

    def test_strips_markdown_fences(self):
        raw = "```json\n{\"tool\": \"done\", \"args\": {}}\n```"
        call, err = _parse_tool_call(raw)
        assert err == ""
        assert call["tool"] == "done"

    def test_strips_think_blocks(self):
        raw = '<think>I should call done now</think>{"tool": "done", "args": {}}'
        call, err = _parse_tool_call(raw)
        assert err == ""
        assert call["tool"] == "done"

    def test_invalid_json_returns_error(self):
        call, err = _parse_tool_call("this is not json at all")
        assert err != ""
        assert call == {}

    def test_missing_tool_key_returns_error(self):
        call, err = _parse_tool_call('{"action": "read_file"}')
        assert err != ""

    def test_array_returns_error(self):
        call, err = _parse_tool_call('[{"tool": "read_file"}]')
        assert err != ""  # arrays are not tool calls


# ── ToolLoopEngine ────────────────────────────────────────────────────────────

class TestToolLoopEngine:
    def test_immediate_done(self, registry: ToolRegistry):
        engine = _make_engine(['{"tool": "done", "args": {}}'], registry)
        result = engine.run("system", "task")
        assert result.success
        assert result.status == "done"
        assert result.turns == 1

    def test_read_then_done(self, registry: ToolRegistry):
        responses = [
            '{"tool": "read_file", "args": {"path": "src/hello.py"}}',
            '{"tool": "done", "args": {"summary": "read the file"}}',
        ]
        engine = _make_engine(responses, registry)
        result = engine.run("system", "read and confirm")
        assert result.success
        assert result.turns == 2

    def test_write_then_done_tracks_file(self, registry: ToolRegistry, workspace: Path):
        responses = [
            '{"tool": "write_file", "args": {"path": "new.py", "content": "x = 1\\n"}}',
            '{"tool": "done", "args": {}}',
        ]
        engine = _make_engine(responses, registry)
        result = engine.run("system", "create new.py")
        assert result.success
        assert "new.py" in result.files_written
        assert (workspace / "new.py").exists()

    def test_edit_then_done_tracks_edit(self, registry: ToolRegistry, workspace: Path):
        responses = [
            json.dumps({
                "tool": "edit_file",
                "args": {
                    "path": "src/hello.py",
                    "old_string": "def hi(): return 'hi'",
                    "new_string": "def hi(): return 'hello'",
                },
            }),
            '{"tool": "done", "args": {}}',
        ]
        engine = _make_engine(responses, registry)
        result = engine.run("system", "edit hello.py")
        assert result.success
        assert "src/hello.py" in result.files_edited
        assert "hello" in (workspace / "src" / "hello.py").read_text()

    def test_max_turns_cap(self, registry: ToolRegistry):
        # Never emit done — always emit a no-op read
        responses = ['{"tool": "read_file", "args": {"path": "src/hello.py"}}']
        engine = _make_engine(responses, registry, max_turns=3)
        result = engine.run("system", "never done")
        assert result.status == "max_turns"
        assert result.turns == 3
        assert not result.success

    def test_parse_error_recovers(self, registry: ToolRegistry):
        responses = [
            "I am going to read the file now",   # parse error
            '{"tool": "done", "args": {}}',
        ]
        engine = _make_engine(responses, registry, max_turns=5)
        result = engine.run("system", "task")
        # The engine sends a recovery message and tries again → done
        assert result.success

    def test_llm_failure_returns_error(self, registry: ToolRegistry):
        def failing_chat(messages, model, options):
            raise RuntimeError("connection refused")

        engine = ToolLoopEngine(
            registry=registry,
            chat_fn=failing_chat,
            model="test",
            max_turns=5,
        )
        result = engine.run("system", "task")
        assert result.status == "error"
        assert "connection refused" in result.error

    def test_unknown_tool_continues(self, registry: ToolRegistry):
        responses = [
            '{"tool": "fly_to_moon", "args": {}}',
            '{"tool": "done", "args": {}}',
        ]
        engine = _make_engine(responses, registry, max_turns=5)
        result = engine.run("system", "do something weird then done")
        assert result.success   # unknown tool → error fed back → model recovers

    def test_history_tracked(self, registry: ToolRegistry):
        responses = [
            '{"tool": "read_file", "args": {"path": "src/hello.py"}}',
            '{"tool": "done", "args": {}}',
        ]
        engine = _make_engine(responses, registry)
        result = engine.run("system", "read and done")
        assert len(result.history) >= 1
        assert result.history[0].tool == "read_file"

    def test_run_command_tracked(self, registry: ToolRegistry):
        responses = [
            '{"tool": "run_command", "args": {"command": "python3 -c \\"print(1)\\"", "timeout": 10}}',
            '{"tool": "done", "args": {}}',
        ]
        engine = _make_engine(responses, registry)
        result = engine.run("system", "run a command")
        assert result.success
        assert len(result.commands_run) == 1

    def test_budget_warning_injected(self, registry: ToolRegistry):
        """Budget warning message injected when turn == TOOL_CALL_BUDGET_WARN."""
        from sage.execution.tool_loop import TOOL_CALL_BUDGET_WARN

        captured_messages: list[list] = []

        def chat_fn(messages, model, options):
            captured_messages.append(list(messages))
            turn = len(captured_messages)
            if turn == TOOL_CALL_BUDGET_WARN + 1:
                return '{"tool": "done", "args": {}}'
            return '{"tool": "read_file", "args": {"path": "src/hello.py"}}'

        engine = ToolLoopEngine(
            registry=registry,
            chat_fn=chat_fn,
            model="test",
            max_turns=TOOL_CALL_BUDGET_WARN + 2,
        )
        result = engine.run("system", "task")
        assert result.success
        # Check that some message at the budget turn contains the warning
        budget_msgs = [m for msgs in captured_messages for m in msgs
                       if "tool calls remaining" in m.get("content", "")]
        assert len(budget_msgs) >= 1


# ── build_system_prompt ───────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_includes_tool_catalogue(self, registry: ToolRegistry):
        prompt = build_system_prompt(
            task_description="do a thing",
            memory_context="",
            user_rules="",
            registry=registry,
        )
        assert "read_file" in prompt
        assert "edit_file" in prompt
        assert "grep_code" in prompt

    def test_includes_task_description(self, registry: ToolRegistry):
        prompt = build_system_prompt(
            task_description="implement JWT auth",
            memory_context="",
            user_rules="",
            registry=registry,
        )
        assert "implement JWT auth" in prompt

    def test_includes_universal_prefix(self, registry: ToolRegistry):
        prompt = build_system_prompt(
            task_description="x",
            memory_context="",
            user_rules="",
            registry=registry,
            universal_prefix="MY_GLOBAL_RULES",
        )
        assert "MY_GLOBAL_RULES" in prompt

    def test_includes_user_rules(self, registry: ToolRegistry):
        prompt = build_system_prompt(
            task_description="x",
            memory_context="",
            user_rules="Always write tests first.",
            registry=registry,
        )
        assert "Always write tests first" in prompt

    def test_omits_empty_user_rules(self, registry: ToolRegistry):
        prompt = build_system_prompt(
            task_description="x",
            memory_context="",
            user_rules="No project-specific rules defined.",
            registry=registry,
        )
        assert "No project-specific rules defined" not in prompt

    def test_includes_memory_context(self, registry: ToolRegistry):
        prompt = build_system_prompt(
            task_description="x",
            memory_context='{"project": "myapp"}',
            user_rules="",
            registry=registry,
        )
        assert "myapp" in prompt


# ── LoopResult ────────────────────────────────────────────────────────────────

class TestLoopResult:
    def test_success_when_done(self):
        r = LoopResult(status="done", turns=5)
        assert r.success is True

    def test_not_success_when_max_turns(self):
        r = LoopResult(status="max_turns", turns=24)
        assert r.success is False

    def test_not_success_when_error(self):
        r = LoopResult(status="error", turns=1)
        assert r.success is False


# ── _stream_turn ──────────────────────────────────────────────────────────────

class TestStreamTurn:
    def test_ok_tool_prints_line(self, capsys):
        result = ToolResult(tool="read_file", success=True, output="contents")
        _stream_turn(1, 24, "read_file", {"path": "src/main.py"}, result)
        captured = capsys.readouterr()
        assert "[01/24]" in captured.out
        assert "read_file" in captured.out
        assert "src/main.py" in captured.out
        assert "ok" in captured.out

    def test_error_tool_prints_error(self, capsys):
        result = ToolResult(tool="edit_file", success=False, output="", error="file not found")
        _stream_turn(3, 24, "edit_file", {"path": "missing.py"}, result)
        captured = capsys.readouterr()
        assert "ERROR" in captured.out
        assert "file not found" in captured.out

    def test_command_arg_surfaced(self, capsys):
        result = ToolResult(tool="run_command", success=True, output="ok")
        _stream_turn(2, 24, "run_command", {"command": "pytest tests/"}, result)
        captured = capsys.readouterr()
        assert "pytest tests/" in captured.out

    def test_no_args_still_prints(self, capsys):
        result = ToolResult(tool="todo_read", success=True, output="[ ] step 1")
        _stream_turn(5, 24, "todo_read", {}, result)
        captured = capsys.readouterr()
        assert "todo_read" in captured.out

    def test_streaming_fires_on_each_loop_turn(self, workspace: Path):
        """Integration: verify _stream_turn is called inside the engine loop."""
        responses = [
            json.dumps({"tool": "todo_read", "args": {}}),
            json.dumps({"tool": "done", "args": {}}),
        ]
        idx = 0
        def chat_fn(messages, model, options):
            nonlocal idx
            r = responses[idx]; idx += 1; return r

        reg = ToolRegistry(workspace_roots=[workspace])
        engine = ToolLoopEngine(registry=reg, chat_fn=chat_fn, model="m", max_turns=24)
        with patch("sage.execution.tool_loop._stream_turn") as mock_stream:
            engine.run(system_prompt="sys", task_description="task")
        assert mock_stream.call_count == 1   # called once for todo_read, not for done
