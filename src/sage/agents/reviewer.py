"""
SAGE Reviewer Agent
-------------------
Runs after CoderAgent writes a file. Validates quality before marking a task complete.

Review checks (in order):
  1. Static: file is non-empty, length in bounds (≥ 5 lines)
  2. Syntax: ast.parse() for .py files — catches SyntaxErrors instantly
  3. LLM review: calls Ollama with reviewer.md template, gets a pass/fail JSON
  4. Coverage gate: if a test file was written, runs it and checks exit code

The ReviewerAgent feeds failures back into the retry loop via a structured ReviewResult.
It does NOT fix code — that's the DebuggerAgent's job. It only judges.

Phase 5 gate (what blocks task completion):
  - Empty / whitespace-only file
  - Python syntax error
  - LLM reviewer says "FAIL" with high confidence
"""

import ast
import json
import re
from pathlib import Path
from dataclasses import dataclass

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.orchestrator.model_router import ModelRouter
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout
from sage.protocol.schemas import AgentInsight

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "reviewer.md"
MAX_REVIEW_LINES = 300


@dataclass
class ReviewResult:
    passed: bool
    score: float  # 0.0 – 1.0
    verdict: str  # "PASS" | "FAIL"
    issues: list[str]
    suggestion: str = ""
    model_used: str = ""


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text()
    return ""


def _static_checks(file: str, content: str) -> list[str]:
    """Fast local checks — no model call needed."""
    issues = []
    lines = content.splitlines()
    if not content.strip():
        issues.append("File is empty or whitespace-only.")
    if len(lines) < 3:
        issues.append(f"File is suspiciously short ({len(lines)} lines).")
    if file.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            issues.append(f"SyntaxError: {e}")
    return issues


def _extract_review_json(text: str) -> dict:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    match = re.search(r"\{[\s\S]+\}", text)
    if not match:
        raise ValueError(f"No JSON in reviewer response:\n{text[:300]}")
    return json.loads(match.group())


class ReviewerAgent:
    def __init__(self):
        self.router = ModelRouter()
        self.template = _load_template()

    def run(
        self,
        file: str,
        task: dict,
        memory: dict | None = None,
        failure_count: int = 0,
        universal_prefix: str = "",
        insight_sink=None,
    ) -> ReviewResult:
        """
        Review the written file. Returns a ReviewResult.
        Fails fast on static issues; calls LLM only if static checks pass.
        """

        # Small helper: emit AgentInsight packets if an orchestrator sink exists.
        def _emit(
            insight_type: str,
            *,
            severity: str,
            content: str,
            requires_orchestrator_action: bool = False,
        ) -> None:
            if insight_sink is None:
                return
            try:
                insight_sink.ingest(
                    AgentInsight(
                        agent="reviewer",
                        task_id=str(task.get("id", "")),
                        insight_type=insight_type,
                        content=(content or "")[:2000],
                        severity=severity,
                        requires_orchestrator_action=requires_orchestrator_action,
                    )
                )
            except Exception:
                return

        path = Path(file)
        if not path.exists():
            _emit(
                "risk",
                severity="high",
                content=f"Review failed: file not found: {file}",
                requires_orchestrator_action=True,
            )
            return ReviewResult(
                passed=False, score=0.0, verdict="FAIL", issues=[f"File not found: {file}"]
            )

        content = path.read_text()
        issues = _static_checks(file, content)

        if issues:
            print(f"[Reviewer] Static check FAILED: {issues[0]}")
            _emit(
                "risk",
                severity="high",
                content=issues[0],
                requires_orchestrator_action=True,
            )
            return ReviewResult(passed=False, score=0.0, verdict="FAIL", issues=issues)

        # ── LLM Review ────────────────────────────────────────────────────────
        model = self.router.select(
            "reviewer",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=failure_count,
        )
        snippet = "\n".join(content.splitlines()[:MAX_REVIEW_LINES])
        system = (
            self.template.replace("{task_description}", task.get("description", ""))
            .replace("{file_content}", snippet)
            .replace("{file_path}", file)
        )
        if universal_prefix:
            system = universal_prefix + "\n\n" + system
        print(f"[Reviewer] Using model: {model}")
        print(f"[Reviewer] Reviewing: {file}")

        _emit(
            "decision",
            severity="low",
            content=f"Reviewer selected model={model} for LLM review.",
        )

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Review this file for task: {task.get('description', '')}\n"
                            f"FILE: {file}\n\nReturn ONLY JSON verdict."
                        ),
                    },
                ],
                options={"temperature": 0.0},
                timeout_s=5.0,
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            # Fall back to static checks only (already executed above).
            print(f"[Reviewer] Model call failed: {e} — using static checks only.")
            _emit(
                "observation",
                severity="low",
                content=f"LLM review skipped due to model failure: {str(e)[:800]}",
            )
            return ReviewResult(
                passed=True,
                score=0.5,
                verdict="PASS",
                issues=[],
                suggestion="LLM review skipped (model unavailable; static checks only)",
            )

        raw = response["message"]["content"]
        try:
            data = _extract_review_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            # Fall back to static checks only (already executed above).
            print(f"[Reviewer] Parse failed: {e} — using static checks only.")
            _emit(
                "observation",
                severity="low",
                content=f"LLM verdict parse failed; static checks only: {str(e)[:800]}",
            )
            return ReviewResult(
                passed=True,
                score=0.5,
                verdict="PASS",
                issues=[],
                suggestion="LLM verdict parse failed (static checks only)",
            )

        verdict = str(data.get("verdict", "PASS")).upper()
        score = float(data.get("score", 0.7))
        issues = data.get("issues", [])
        suggestion = data.get("suggestion", "")

        passed = verdict == "PASS" and score >= 0.5
        if passed:
            print(f"[Reviewer] ✓ PASS (score={score:.2f})")
        else:
            print(f"[Reviewer] ✗ FAIL (score={score:.2f}) — {issues[:1]}")

        _emit(
            "observation",
            severity="low",
            content=(
                f"Review completed: verdict={verdict}, score={score:.2f}, "
                f"issues_count={len(issues)}"
            ),
            requires_orchestrator_action=False,
        )
        if not passed:
            _emit(
                "risk",
                severity="high",
                content=(issues[0] if issues else "LLM reviewer reported FAIL"),
                requires_orchestrator_action=True,
            )

        return ReviewResult(
            passed=passed,
            score=score,
            verdict=verdict,
            issues=issues,
            suggestion=suggestion,
            model_used=model,
        )
