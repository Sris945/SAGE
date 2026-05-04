"""
Unit tests for the DebuggerAgent tool-use loop (Phase 5).
Tests: loop dispatch, completed vs patch_ready routing, fallback to single-shot.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch


TASK = {"id": "t1", "description": "fix failing test", "task_complexity_score": 0.5}
ERROR = "AssertionError: expected 2 got 3"


class TestDebugLoopEnabled:
    def test_enabled_by_default(self):
        import sage.agents.debugger as mod
        env = {k: v for k, v in os.environ.items() if k != "SAGE_TOOL_LOOP"}
        with patch.dict(os.environ, env, clear=True):
            assert mod._debug_loop_enabled() is True

    def test_disabled_by_env(self):
        import sage.agents.debugger as mod
        with patch.dict(os.environ, {"SAGE_TOOL_LOOP": "0"}):
            assert mod._debug_loop_enabled() is False

    def test_disabled_by_false_string(self):
        import sage.agents.debugger as mod
        with patch.dict(os.environ, {"SAGE_TOOL_LOOP": "false"}):
            assert mod._debug_loop_enabled() is False


class TestDebuggerRunDispatch:
    def _loop_result(self, *, status="done", files_edited=None, files_written=None, turns=3):
        from sage.execution.tool_loop import LoopResult
        r = LoopResult(status=status, turns=turns)
        r.files_edited = files_edited or ["src/app.py"]
        r.files_written = files_written or []
        return r

    def test_dispatches_to_loop_when_enabled(self, tmp_path: Path):
        from sage.agents.debugger import DebuggerAgent

        loop_result = self._loop_result()
        with (
            patch("sage.agents.debugger._debug_loop_enabled", return_value=True),
            patch("sage.agents.debugger.ollama", object()),
            patch.object(DebuggerAgent, "run_loop", return_value={"status": "completed",
                         "files_edited": ["src/app.py"], "files_written": [],
                         "file": "src/app.py", "operation": "edit",
                         "reason": "fixed", "suspected_cause": "", "error_signature": "",
                         "fix_generated": True, "epistemic_flags": [], "error": None}) as mock_loop,
        ):
            agent = DebuggerAgent()
            result = agent.run(task=TASK, error=ERROR)
        assert mock_loop.called
        assert result["status"] == "completed"

    def test_fallback_to_single_shot_when_loop_disabled(self, tmp_path: Path):
        from sage.agents.debugger import DebuggerAgent

        with (
            patch("sage.agents.debugger._debug_loop_enabled", return_value=False),
            patch("sage.agents.debugger.ollama", None),
        ):
            agent = DebuggerAgent()
            result = agent.run(task=TASK, error=ERROR)
        # ollama=None causes single-shot to fail with "dependency_missing"
        assert result["status"] == "failed"
        assert result["suspected_cause"] == "dependency_missing"

    def test_fallback_when_ollama_none_in_loop_mode(self):
        from sage.agents.debugger import DebuggerAgent

        with (
            patch("sage.agents.debugger._debug_loop_enabled", return_value=True),
            patch("sage.agents.debugger.ollama", None),  # loop checks ollama before dispatching
        ):
            agent = DebuggerAgent()
            result = agent.run(task=TASK, error=ERROR)
        assert result["status"] == "failed"


class TestDebuggerRunLoop:
    def _make_loop_result(self, status="done", files_edited=None):
        from sage.execution.tool_loop import LoopResult
        r = LoopResult(status=status, turns=5)
        r.files_edited = files_edited or ["src/app.py"]
        r.files_written = []
        return r

    def test_completed_result_returns_completed(self, tmp_path: Path):
        from sage.agents.debugger import DebuggerAgent
        from sage.execution.tool_loop import LoopResult

        loop_result = self._make_loop_result()
        with (
            patch("sage.agents.debugger.chat_with_timeout",
                  return_value={"message": {"content": '{"tool":"done","args":{}}'}}),
            patch("sage.execution.tool_loop.ToolLoopEngine.run", return_value=loop_result),
        ):
            agent = DebuggerAgent()
            result = agent.run_loop(task=TASK, error=ERROR, repo_root=str(tmp_path))
        assert result["status"] == "completed"
        assert result["fix_generated"] is True
        assert "src/app.py" in result["files_edited"]

    def test_loop_no_files_falls_back_to_single_shot(self, tmp_path: Path):
        from sage.agents.debugger import DebuggerAgent
        from sage.execution.tool_loop import LoopResult

        loop_result = LoopResult(status="done", turns=2)
        loop_result.files_edited = []
        loop_result.files_written = []

        patch_result = {
            "status": "patch_ready",
            "patch_request": {"file": "x.py", "operation": "edit", "patch": "pass",
                              "reason": "r", "epistemic_flags": []},
            "file": "x.py", "operation": "edit", "reason": "r",
            "suspected_cause": "", "error_signature": "", "fix_generated": True,
            "epistemic_flags": [], "error": None, "debug_phases": {},
        }
        with (
            patch("sage.execution.tool_loop.ToolLoopEngine.run", return_value=loop_result),
            patch.object(DebuggerAgent, "_run_single_shot", return_value=patch_result) as mock_ss,
        ):
            agent = DebuggerAgent()
            result = agent.run_loop(task=TASK, error=ERROR, repo_root=str(tmp_path))
        assert mock_ss.called
        assert result["status"] == "patch_ready"

    def test_emits_insight_on_success(self, tmp_path: Path):
        from sage.agents.debugger import DebuggerAgent
        from sage.execution.tool_loop import LoopResult

        loop_result = self._make_loop_result()
        insight_sink = MagicMock()

        with patch("sage.execution.tool_loop.ToolLoopEngine.run", return_value=loop_result):
            agent = DebuggerAgent()
            agent.run_loop(
                task=TASK, error=ERROR, repo_root=str(tmp_path), insight_sink=insight_sink
            )
        assert insight_sink.ingest.called
        emitted = insight_sink.ingest.call_args[0][0]
        assert emitted.agent == "debugger"
        assert emitted.insight_type == "observation"


class TestRunSingleShot:
    def test_returns_patch_ready_on_success(self):
        from sage.agents.debugger import DebuggerAgent

        raw = '{"file": "a.py", "operation": "edit", "patch": "x=1", "reason": "fix it"}'
        with (
            patch("sage.agents.debugger.ollama", object()),
            patch("sage.agents.debugger.chat_with_timeout",
                  return_value={"message": {"content": raw}}),
        ):
            agent = DebuggerAgent()
            result = agent._run_single_shot(task=TASK, error=ERROR, model="test-model")
        assert result["status"] == "patch_ready"
        assert result["fix_generated"] is True

    def test_returns_failed_when_ollama_none(self):
        from sage.agents.debugger import DebuggerAgent

        with patch("sage.agents.debugger.ollama", None):
            agent = DebuggerAgent()
            result = agent._run_single_shot(task=TASK, error=ERROR, model="m")
        assert result["status"] == "failed"
        assert result["suspected_cause"] == "dependency_missing"

    def test_returns_failed_on_empty_patch(self):
        from sage.agents.debugger import DebuggerAgent

        raw = '{"file": "a.py", "operation": "edit", "patch": "", "reason": "fix"}'
        with (
            patch("sage.agents.debugger.ollama", object()),
            patch("sage.agents.debugger.chat_with_timeout",
                  return_value={"message": {"content": raw}}),
        ):
            agent = DebuggerAgent()
            result = agent._run_single_shot(task=TASK, error=ERROR, model="m")
        assert result["status"] == "failed"
        assert result["suspected_cause"] == "empty_patch"

    def test_returns_failed_on_parse_error(self):
        from sage.agents.debugger import DebuggerAgent

        with (
            patch("sage.agents.debugger.ollama", object()),
            patch("sage.agents.debugger.chat_with_timeout",
                  return_value={"message": {"content": "not json at all"}}),
        ):
            agent = DebuggerAgent()
            result = agent._run_single_shot(task=TASK, error=ERROR, model="m")
        assert result["status"] == "failed"
        assert result["suspected_cause"] == "parse failed"
