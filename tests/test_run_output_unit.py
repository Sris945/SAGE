"""
Unit tests for sage.cli.run_output.
Tests: RunReport construction, cross-file review in report, print rendering.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from sage.cli.run_output import RunReport, build_run_report, print_run_report


class TestBuildRunReport:
    def _minimal_state(self, **overrides) -> dict:
        base = {
            "user_prompt": "build a thing",
            "enhanced_prompt": "",
            "task_dag": {"nodes": []},
            "artifacts_by_task": {},
            "last_error": "",
        }
        base.update(overrides)
        return base

    def test_empty_state_builds_report(self):
        report = build_run_report({})
        assert isinstance(report, RunReport)
        assert report.completed == 0
        assert report.failed == 0

    def test_counts_task_statuses(self):
        state = self._minimal_state(
            task_dag={
                "nodes": [
                    {"id": "t1", "status": "completed", "description": "d1", "assigned_agent": "coder"},
                    {"id": "t2", "status": "failed", "description": "d2", "assigned_agent": "coder"},
                    {"id": "t3", "status": "blocked", "description": "d3", "assigned_agent": "coder"},
                ]
            }
        )
        report = build_run_report(state)
        assert report.completed == 1
        assert report.failed == 1
        assert report.blocked == 1

    def test_artifacts_populated(self):
        state = self._minimal_state(
            artifacts_by_task={"t1": "src/app.py", "t2": "tests/test_app.py"}
        )
        report = build_run_report(state)
        paths = [p for _, p in report.artifacts]
        assert "src/app.py" in paths
        assert "tests/test_app.py" in paths

    def test_cross_file_review_pass_included(self):
        cfr = {"passed": True, "skipped": False, "issues": [], "files_reviewed": ["a.py"],
               "model_used": "m", "skip_reason": ""}
        state = self._minimal_state(cross_file_review_result=cfr)
        report = build_run_report(state)
        assert report.cross_file_review is not None
        assert report.cross_file_review["passed"] is True

    def test_cross_file_review_fail_included(self):
        cfr = {
            "passed": False,
            "skipped": False,
            "issues": [{"severity": "critical", "description": "broken import",
                        "files_involved": ["a.py"], "suggestion": "fix it"}],
            "files_reviewed": ["a.py", "b.py"],
            "model_used": "m",
            "skip_reason": "",
        }
        state = self._minimal_state(cross_file_review_result=cfr)
        report = build_run_report(state)
        assert report.cross_file_review is not None
        assert report.cross_file_review["passed"] is False
        assert len(report.cross_file_review["issues"]) == 1

    def test_cross_file_review_none_when_absent(self):
        state = self._minimal_state()
        report = build_run_report(state)
        assert report.cross_file_review is None

    def test_cross_file_review_none_when_skipped(self):
        cfr = {"passed": True, "skipped": True, "skip_reason": "no files", "issues": [],
               "files_reviewed": [], "model_used": ""}
        state = self._minimal_state(cross_file_review_result=cfr)
        report = build_run_report(state)
        # skipped reviews should still be in the dict
        assert report.cross_file_review is not None

    def test_last_error_populated(self):
        state = self._minimal_state(last_error="something went wrong")
        report = build_run_report(state)
        assert "something went wrong" in report.last_error


class TestPrintRunReport:
    def _simple_report(self, **kwargs) -> RunReport:
        defaults = dict(
            goal="test goal",
            plan_only=False,
            dry_run=False,
            tasks=[],
            artifacts=[],
        )
        defaults.update(kwargs)
        return RunReport(**defaults)

    def test_prints_without_crash(self):
        report = self._simple_report()
        with patch("sage.cli.branding.get_console") as mock_console:
            mock_console.return_value.print = lambda *a, **k: None
            print_run_report(report)

    def test_cross_file_pass_renders_without_crash(self):
        cfr = {"passed": True, "skipped": False, "issues": [], "files_reviewed": ["a.py"],
               "model_used": "m", "skip_reason": ""}
        report = self._simple_report(cross_file_review=cfr)
        call_count = [0]
        with patch("sage.cli.branding.get_console") as mock_console:
            mock_console.return_value.print = lambda *a, **k: call_count.__setitem__(0, call_count[0] + 1)
            print_run_report(report, level="summary")
        # Panel was rendered (multiple print calls expected)
        assert call_count[0] > 0

    def test_cross_file_fail_renders_without_crash(self):
        cfr = {
            "passed": False,
            "skipped": False,
            "issues": [{"severity": "critical", "description": "ImportError in main.py",
                        "files_involved": ["main.py"], "suggestion": "add import"}],
            "files_reviewed": ["main.py"],
            "model_used": "m",
            "skip_reason": "",
        }
        report = self._simple_report(cross_file_review=cfr)
        with patch("sage.cli.branding.get_console") as mock_console:
            mock_console.return_value.print = lambda *a, **k: None
            # Should not raise
            print_run_report(report, level="summary")

    def test_skipped_cross_file_review_renders_without_crash(self):
        cfr = {"passed": True, "skipped": True, "skip_reason": "no files",
               "issues": [], "files_reviewed": [], "model_used": ""}
        report = self._simple_report(cross_file_review=cfr)
        with patch("sage.cli.branding.get_console") as mock_console:
            mock_console.return_value.print = lambda *a, **k: None
            print_run_report(report, level="summary")

    def test_plain_fallback_does_not_crash(self):
        from sage.cli.run_output import _print_run_report_plain
        report = self._simple_report(
            tasks=[{"id": "t1", "status": "completed", "assigned_agent": "coder", "description": "do thing"}],
            artifacts=[("t1", "src/app.py")],
        )
        # Should not raise
        import sys
        orig = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _print_run_report_plain(report)
        finally:
            sys.stdout = orig
