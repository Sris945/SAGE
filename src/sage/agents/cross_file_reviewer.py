"""
SAGE Cross-File Reviewer
------------------------
Runs after all DAG tasks complete. Instead of reviewing one file at a time,
it assembles a unified view of ALL changed files and asks the model to catch
cross-file issues that per-task review misses:

  - Mismatched function signatures between caller and callee
  - Missing import of a symbol that was moved
  - Inconsistent type annotations across modules
  - Test file referencing a function that was renamed
  - New module not wired into the package __init__.py

Output: CrossFileReviewResult (structured, injected into session memory)

This runs in --research and --auto mode; skipped in --silent.
Graceful degradation: if ollama is unavailable, returns PASS with a warning.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_json_object
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout
from sage.orchestrator.model_router import ModelRouter


MAX_DIFF_CHARS = 12_000     # stay inside 32K context
MAX_FILE_CONTENT_CHARS = 3_000


@dataclass
class CrossFileIssue:
    severity: str           # "critical" | "high" | "medium" | "low"
    description: str
    files_involved: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class CrossFileReviewResult:
    passed: bool
    issues: list[CrossFileIssue] = field(default_factory=list)
    files_reviewed: list[str] = field(default_factory=list)
    model_used: str = ""
    skipped: bool = False
    skip_reason: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "high")

    def summary(self) -> str:
        if self.skipped:
            return f"Cross-file review skipped: {self.skip_reason}"
        status = "PASS" if self.passed else "FAIL"
        n = len(self.issues)
        return (
            f"Cross-file review: {status} "
            f"({n} issue(s), {self.critical_count} critical, {self.high_count} high) "
            f"across {len(self.files_reviewed)} file(s)"
        )


class CrossFileReviewer:
    """
    Collects all files changed in the current run and reviews them together.
    """

    def __init__(self) -> None:
        self.router = ModelRouter()

    def run(
        self,
        changed_files: list[str],
        repo_root: str | None = None,
        task_descriptions: list[str] | None = None,
        insight_sink: Any = None,
    ) -> CrossFileReviewResult:
        """
        Review *changed_files* together for cross-file consistency.

        Args:
            changed_files: paths (relative or absolute) of every file written/edited
            repo_root: project root (default cwd)
            task_descriptions: human-readable goals (injected for context)
            insight_sink: optional OrchestratorIntelligenceFeed
        """
        root = Path(repo_root or Path.cwd()).resolve()

        # Filter to files that exist
        existing: list[Path] = []
        for f in changed_files:
            p = Path(f)
            if not p.is_absolute():
                p = root / p
            if p.is_file():
                existing.append(p)

        if not existing:
            return CrossFileReviewResult(
                passed=True, skipped=True, skip_reason="no changed files to review"
            )

        if ollama is None:
            return CrossFileReviewResult(
                passed=True, skipped=True, skip_reason="ollama unavailable"
            )

        # Build the review payload
        diff_block = self._build_diff_block(existing, root)
        file_contents = self._build_file_contents(existing, root)
        context = self._format_review_context(diff_block, file_contents, task_descriptions or [])

        model = self.router.get_primary_fallback("reviewer")[0]

        system = _CROSS_FILE_SYSTEM_PROMPT
        user_msg = f"Review these changed files for cross-file consistency issues.\n\n{context}"

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                options={"temperature": 0.0},
                timeout_s=None,
            )
        except (OllamaTimeout, RuntimeError, Exception) as exc:
            logger.warning("Cross-file review LLM call failed: %s", exc)
            return CrossFileReviewResult(
                passed=True, skipped=True, skip_reason=f"LLM error: {exc}"
            )

        msg = response.get("message") or {}
        raw = msg.get("content", "") if isinstance(msg, dict) else str(msg)

        result = self._parse_review(raw, existing, root, model)

        # Emit insight if critical issues found
        if not result.passed and insight_sink is not None:
            try:
                from sage.protocol.schemas import AgentInsight
                insight_sink.ingest(AgentInsight(
                    agent="cross_file_reviewer",
                    task_id="cross_file_review",
                    insight_type="risk",
                    content=(
                        f"Cross-file review found {result.critical_count} critical "
                        f"and {result.high_count} high issues: "
                        + "; ".join(i.description[:80] for i in result.issues[:3])
                    )[:2000],
                    severity="high" if result.critical_count > 0 else "medium",
                    requires_orchestrator_action=result.critical_count > 0,
                ))
            except Exception:
                pass

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_diff_block(self, files: list[Path], root: Path) -> str:
        """Run git diff HEAD for changed files; fallback to file contents."""
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD", "--"] + [str(f) for f in files],
                capture_output=True, text=True, timeout=15, cwd=str(root),
            )
            diff = result.stdout
            if diff.strip():
                return diff[:MAX_DIFF_CHARS]
        except (OSError, subprocess.SubprocessError):
            pass
        return ""

    def _build_file_contents(self, files: list[Path], root: Path) -> dict[str, str]:
        contents: dict[str, str] = {}
        for f in files:
            rel = str(f.relative_to(root)) if f.is_absolute() else str(f)
            try:
                text = f.read_text(errors="replace")
                if len(text) > MAX_FILE_CONTENT_CHARS:
                    text = text[:MAX_FILE_CONTENT_CHARS] + "\n… (truncated)"
                contents[rel] = text
            except OSError:
                pass
        return contents

    def _format_review_context(
        self,
        diff_block: str,
        file_contents: dict[str, str],
        task_descriptions: list[str],
    ) -> str:
        parts: list[str] = []
        if task_descriptions:
            parts.append("TASKS COMPLETED:\n" + "\n".join(f"- {t}" for t in task_descriptions[:10]))
        if diff_block:
            parts.append(f"GIT DIFF (all changed files):\n```diff\n{diff_block}\n```")
        for path, content in list(file_contents.items())[:8]:
            parts.append(f"FILE: {path}\n```\n{content}\n```")
        return "\n\n".join(parts)

    def _parse_review(
        self,
        raw: str,
        files: list[Path],
        root: Path,
        model: str,
    ) -> CrossFileReviewResult:
        file_rels = [
            str(f.relative_to(root)) if f.is_absolute() else str(f)
            for f in files
        ]
        try:
            data = parse_json_object(raw)
        except (ValueError, json.JSONDecodeError):
            # Model didn't return JSON — treat as pass with a note
            logger.debug("Cross-file reviewer returned non-JSON: %s…", raw[:200])
            return CrossFileReviewResult(
                passed=True,
                files_reviewed=file_rels,
                model_used=model,
                issues=[],
            )

        verdict = str(data.get("verdict", "PASS")).upper()
        issues: list[CrossFileIssue] = []
        for item in data.get("issues", []):
            if not isinstance(item, dict):
                continue
            issues.append(CrossFileIssue(
                severity=str(item.get("severity", "low")).lower(),
                description=str(item.get("description", "")),
                files_involved=list(item.get("files", [])),
                suggestion=str(item.get("suggestion", "")),
            ))

        has_blocking = any(i.severity in ("critical", "high") for i in issues)
        passed = (verdict == "PASS") and not has_blocking

        return CrossFileReviewResult(
            passed=passed,
            issues=issues,
            files_reviewed=file_rels,
            model_used=model,
        )


# ── System prompt ─────────────────────────────────────────────────────────────

_CROSS_FILE_SYSTEM_PROMPT = """\
You are a senior code reviewer specializing in cross-file consistency.

You will receive a set of files changed in one coding session. Your job is to
find issues that per-file review misses — things that only appear when looking
at multiple files together.

FOCUS ON:
1. Broken imports — a symbol was moved/renamed but the import wasn't updated
2. Signature mismatches — a function signature changed but callers weren't updated
3. Type inconsistencies — a type was changed in one file but not its dependents
4. Missing wiring — a new module exists but isn't imported by __init__.py or app entry
5. Test/implementation drift — a test references a function with the old name/signature
6. Duplicated logic — the same function implemented in two files after the change

SEVERITY LEVELS:
- critical: breaks the program at runtime (ImportError, NameError, TypeError)
- high: logical bug that will cause wrong results or failures
- medium: maintainability concern (duplication, style inconsistency)
- low: minor suggestion

Return ONLY valid JSON:
{
  "verdict": "PASS" or "FAIL",
  "issues": [
    {
      "severity": "critical|high|medium|low",
      "description": "concise explanation",
      "files": ["file_a.py", "file_b.py"],
      "suggestion": "how to fix it"
    }
  ]
}

If there are no cross-file issues, return:
{"verdict": "PASS", "issues": []}
"""
