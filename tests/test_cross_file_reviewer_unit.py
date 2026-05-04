"""
Unit tests for sage.agents.cross_file_reviewer.
Tests: skipping logic, diff/content building, JSON parsing, verdict logic,
insight emission, and graceful degradation.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sage.agents.cross_file_reviewer import (
    CrossFileIssue,
    CrossFileReviewResult,
    CrossFileReviewer,
)


# ── CrossFileReviewResult helpers ─────────────────────────────────────────────

class TestCrossFileReviewResult:
    def test_critical_count(self):
        r = CrossFileReviewResult(
            passed=False,
            issues=[
                CrossFileIssue(severity="critical", description="boom"),
                CrossFileIssue(severity="high", description="bad"),
                CrossFileIssue(severity="critical", description="boom2"),
            ],
        )
        assert r.critical_count == 2

    def test_high_count(self):
        r = CrossFileReviewResult(
            passed=False,
            issues=[
                CrossFileIssue(severity="high", description="h1"),
                CrossFileIssue(severity="medium", description="m1"),
            ],
        )
        assert r.high_count == 1

    def test_summary_pass(self):
        r = CrossFileReviewResult(passed=True, files_reviewed=["a.py", "b.py"])
        s = r.summary()
        assert "PASS" in s
        assert "2 file" in s

    def test_summary_fail(self):
        r = CrossFileReviewResult(
            passed=False,
            issues=[CrossFileIssue(severity="critical", description="x")],
            files_reviewed=["a.py"],
        )
        s = r.summary()
        assert "FAIL" in s
        assert "1 critical" in s

    def test_summary_skipped(self):
        r = CrossFileReviewResult(passed=True, skipped=True, skip_reason="ollama unavailable")
        assert "skipped" in r.summary().lower()
        assert "ollama" in r.summary()


# ── CrossFileReviewer.run — skipping cases ────────────────────────────────────

class TestCrossFileReviewerSkipping:
    def test_no_files_returns_skipped(self, tmp_path: Path):
        reviewer = CrossFileReviewer()
        result = reviewer.run(changed_files=[], repo_root=str(tmp_path))
        assert result.skipped
        assert result.passed

    def test_nonexistent_files_filtered_out(self, tmp_path: Path):
        reviewer = CrossFileReviewer()
        result = reviewer.run(
            changed_files=[str(tmp_path / "ghost.py")],
            repo_root=str(tmp_path),
        )
        assert result.skipped
        assert "no changed files" in result.skip_reason

    def test_ollama_none_returns_skipped(self, tmp_path: Path):
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        with patch("sage.agents.cross_file_reviewer.ollama", None):
            reviewer = CrossFileReviewer()
            result = reviewer.run(changed_files=[str(f)], repo_root=str(tmp_path))
        assert result.skipped
        assert "ollama" in result.skip_reason.lower()

    def test_llm_error_returns_skipped_with_pass(self, tmp_path: Path):
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        with (
            patch("sage.agents.cross_file_reviewer.ollama", object()),
            patch(
                "sage.agents.cross_file_reviewer.chat_with_timeout",
                side_effect=RuntimeError("connection refused"),
            ),
        ):
            reviewer = CrossFileReviewer()
            result = reviewer.run(changed_files=[str(f)], repo_root=str(tmp_path))
        assert result.skipped
        assert result.passed


# ── CrossFileReviewer._parse_review ──────────────────────────────────────────

class TestParseReview:
    def _reviewer(self) -> CrossFileReviewer:
        return CrossFileReviewer()

    def test_pass_verdict_no_issues(self, tmp_path: Path):
        f = tmp_path / "a.py"
        raw = json.dumps({"verdict": "PASS", "issues": []})
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "test-model")
        assert result.passed
        assert result.issues == []
        assert result.model_used == "test-model"

    def test_fail_verdict_with_critical(self, tmp_path: Path):
        f = tmp_path / "a.py"
        raw = json.dumps({
            "verdict": "FAIL",
            "issues": [
                {
                    "severity": "critical",
                    "description": "ImportError: missing symbol",
                    "files": ["a.py", "b.py"],
                    "suggestion": "add import",
                }
            ],
        })
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "m")
        assert not result.passed
        assert result.critical_count == 1
        assert result.issues[0].suggestion == "add import"

    def test_pass_verdict_overridden_by_critical_issue(self, tmp_path: Path):
        f = tmp_path / "a.py"
        raw = json.dumps({
            "verdict": "PASS",
            "issues": [{"severity": "critical", "description": "boom", "files": [], "suggestion": ""}],
        })
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "m")
        # critical issue overrides PASS verdict
        assert not result.passed

    def test_high_issue_overrides_pass_verdict(self, tmp_path: Path):
        f = tmp_path / "a.py"
        raw = json.dumps({
            "verdict": "PASS",
            "issues": [{"severity": "high", "description": "bad", "files": [], "suggestion": ""}],
        })
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "m")
        assert not result.passed

    def test_medium_issue_does_not_fail(self, tmp_path: Path):
        f = tmp_path / "a.py"
        raw = json.dumps({
            "verdict": "PASS",
            "issues": [{"severity": "medium", "description": "style", "files": [], "suggestion": ""}],
        })
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "m")
        assert result.passed

    def test_non_json_response_treated_as_pass(self, tmp_path: Path):
        f = tmp_path / "a.py"
        reviewer = self._reviewer()
        result = reviewer._parse_review("Looks great to me!", [f], tmp_path, "m")
        assert result.passed
        assert result.issues == []

    def test_markdown_fenced_json_parsed(self, tmp_path: Path):
        f = tmp_path / "a.py"
        raw = '```json\n{"verdict": "PASS", "issues": []}\n```'
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "m")
        assert result.passed

    def test_files_reviewed_are_relative(self, tmp_path: Path):
        f = tmp_path / "src" / "main.py"
        f.parent.mkdir()
        f.write_text("pass")
        raw = json.dumps({"verdict": "PASS", "issues": []})
        reviewer = self._reviewer()
        result = reviewer._parse_review(raw, [f], tmp_path, "m")
        assert "src/main.py" in result.files_reviewed
        assert str(tmp_path) not in result.files_reviewed[0]


# ── CrossFileReviewer._build_file_contents ────────────────────────────────────

class TestBuildFileContents:
    def test_reads_files(self, tmp_path: Path):
        f = tmp_path / "x.py"
        f.write_text("hello world")
        reviewer = CrossFileReviewer()
        contents = reviewer._build_file_contents([f], tmp_path)
        assert "x.py" in contents
        assert "hello world" in contents["x.py"]

    def test_truncates_large_file(self, tmp_path: Path):
        f = tmp_path / "big.py"
        f.write_text("x" * 10_000)
        reviewer = CrossFileReviewer()
        from sage.agents.cross_file_reviewer import MAX_FILE_CONTENT_CHARS
        contents = reviewer._build_file_contents([f], tmp_path)
        assert len(contents["big.py"]) <= MAX_FILE_CONTENT_CHARS + 20  # + truncation suffix

    def test_skips_unreadable_file(self, tmp_path: Path):
        f = tmp_path / "missing.py"
        reviewer = CrossFileReviewer()
        contents = reviewer._build_file_contents([f], tmp_path)
        assert contents == {}


# ── CrossFileReviewer._format_review_context ─────────────────────────────────

class TestFormatReviewContext:
    def test_includes_task_descriptions(self):
        reviewer = CrossFileReviewer()
        ctx = reviewer._format_review_context("", {}, ["add auth", "fix tests"])
        assert "add auth" in ctx
        assert "fix tests" in ctx

    def test_includes_diff_block(self):
        reviewer = CrossFileReviewer()
        ctx = reviewer._format_review_context("-old +new", {}, [])
        assert "GIT DIFF" in ctx
        assert "-old +new" in ctx

    def test_includes_file_contents(self):
        reviewer = CrossFileReviewer()
        ctx = reviewer._format_review_context("", {"app.py": "def main(): pass"}, [])
        assert "app.py" in ctx
        assert "def main" in ctx

    def test_limits_file_count_to_eight(self):
        reviewer = CrossFileReviewer()
        many = {f"file_{i}.py": f"content {i}" for i in range(20)}
        ctx = reviewer._format_review_context("", many, [])
        included = sum(1 for i in range(20) if f"file_{i}.py" in ctx)
        assert included <= 8


# ── CrossFileReviewer.run — full integration (LLM mocked) ────────────────────

class TestCrossFileReviewerRun:
    def _run_with_response(self, tmp_path: Path, llm_content: str) -> CrossFileReviewResult:
        f = tmp_path / "main.py"
        f.write_text("def foo(): pass\n")
        with (
            patch("sage.agents.cross_file_reviewer.ollama", object()),
            patch(
                "sage.agents.cross_file_reviewer.chat_with_timeout",
                return_value={"message": {"content": llm_content}},
            ),
        ):
            return CrossFileReviewer().run(
                changed_files=[str(f)],
                repo_root=str(tmp_path),
            )

    def test_pass_verdict_propagates(self, tmp_path: Path):
        result = self._run_with_response(tmp_path, '{"verdict":"PASS","issues":[]}')
        assert result.passed
        assert not result.skipped

    def test_fail_verdict_propagates(self, tmp_path: Path):
        payload = json.dumps({
            "verdict": "FAIL",
            "issues": [{"severity": "critical", "description": "broken import",
                        "files": ["main.py"], "suggestion": "fix it"}],
        })
        result = self._run_with_response(tmp_path, payload)
        assert not result.passed
        assert result.critical_count == 1

    def test_files_reviewed_populated(self, tmp_path: Path):
        result = self._run_with_response(tmp_path, '{"verdict":"PASS","issues":[]}')
        assert "main.py" in result.files_reviewed

    def test_model_used_populated(self, tmp_path: Path):
        result = self._run_with_response(tmp_path, '{"verdict":"PASS","issues":[]}')
        assert result.model_used != ""


# ── Insight sink emission ─────────────────────────────────────────────────────

class TestInsightEmission:
    def test_emits_insight_on_critical_issues(self, tmp_path: Path):
        f = tmp_path / "a.py"
        f.write_text("pass")
        payload = json.dumps({
            "verdict": "FAIL",
            "issues": [{"severity": "critical", "description": "ImportError",
                        "files": ["a.py"], "suggestion": ""}],
        })
        insight_sink = MagicMock()
        with (
            patch("sage.agents.cross_file_reviewer.ollama", object()),
            patch(
                "sage.agents.cross_file_reviewer.chat_with_timeout",
                return_value={"message": {"content": payload}},
            ),
        ):
            CrossFileReviewer().run(
                changed_files=[str(f)],
                repo_root=str(tmp_path),
                insight_sink=insight_sink,
            )
        assert insight_sink.ingest.called
        emitted = insight_sink.ingest.call_args[0][0]
        assert emitted.insight_type == "risk"
        assert emitted.requires_orchestrator_action is True

    def test_no_insight_on_pass(self, tmp_path: Path):
        f = tmp_path / "a.py"
        f.write_text("pass")
        insight_sink = MagicMock()
        with (
            patch("sage.agents.cross_file_reviewer.ollama", object()),
            patch(
                "sage.agents.cross_file_reviewer.chat_with_timeout",
                return_value={"message": {"content": '{"verdict":"PASS","issues":[]}'}},
            ),
        ):
            CrossFileReviewer().run(
                changed_files=[str(f)],
                repo_root=str(tmp_path),
                insight_sink=insight_sink,
            )
        assert not insight_sink.ingest.called
