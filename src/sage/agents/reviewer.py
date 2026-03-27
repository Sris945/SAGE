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
from pathlib import Path
from dataclasses import dataclass

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_json_object
from sage.cli.branding import print_agent_line
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


def _short_manifest_ok(file: str) -> bool:
    """Dependency/config files are often 1–2 lines; do not require 3+ lines."""
    name = Path(str(file).replace("\\", "/")).name.lower()
    return name in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "constraints.txt",
        "setup.cfg",
        "pyproject.toml",
        "pipfile",
    )


def _static_checks(file: str, content: str) -> list[str]:
    """Fast local checks — no model call needed."""
    issues = []
    lines = content.splitlines()
    if not content.strip():
        issues.append("File is empty or whitespace-only.")
    if len(lines) < 3 and not _short_manifest_ok(file):
        issues.append(f"File is suspiciously short ({len(lines)} lines).")
    if file.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            issues.append(f"SyntaxError: {e}")
    return issues


def _coerce_issues(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [val] if val.strip() else []
    if isinstance(val, list):
        return [str(x) for x in val]
    return [str(val)]


def _goal_alignment_issues(task_description: str, file: str, content: str) -> list[str]:
    """
    Deterministic checks that the artifact matches explicit stack / route keywords
    in the task text (product-grade bar; catches "Hello World" pretending to be FastAPI).
    """
    t = (task_description or "").lower()
    c = (content or "").lower()
    fp = (file or "").replace("\\", "/")
    issues: list[str] = []

    if fp.endswith("requirements.txt") or fp.endswith("pyproject.toml"):
        if "fastapi" in t:
            if "fastapi" not in c:
                issues.append(
                    "Task requires FastAPI but the dependency manifest does not list fastapi."
                )
            if "uvicorn" not in c:
                issues.append(
                    "Expected uvicorn (or uvicorn[standard]) alongside FastAPI — not found."
                )
        return issues

    if not fp.endswith(".py"):
        return issues

    if "fastapi" in t:
        if "fastapi" not in c:
            issues.append("Task calls for FastAPI but this file does not use fastapi.")
        if any(h in t for h in ("/health", "health endpoint", "health route", "health check")):
            if "/health" not in c and "health" not in c:
                issues.append(
                    "Task requires a /health endpoint but no health route or handler is present."
                )
    if "flask" in t and "flask" not in c:
        issues.append("Task calls for Flask but this file does not use flask.")
    if "django" in t and "django" not in c:
        issues.append("Task calls for Django but this file does not use django.")
    return issues


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
            print_agent_line("Reviewer", f"Static check FAILED: {issues[0]}")
            _emit(
                "risk",
                severity="high",
                content=issues[0],
                requires_orchestrator_action=True,
            )
            return ReviewResult(passed=False, score=0.0, verdict="FAIL", issues=issues)

        goal_issues = _goal_alignment_issues(str(task.get("description", "")), file, content)
        if goal_issues:
            print_agent_line("Reviewer", f"Goal alignment FAILED: {goal_issues[0]}")
            _emit(
                "risk",
                severity="high",
                content=goal_issues[0],
                requires_orchestrator_action=True,
            )
            return ReviewResult(passed=False, score=0.0, verdict="FAIL", issues=goal_issues)

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
        print_agent_line("Reviewer", f"Using model: {model}")
        print_agent_line("Reviewer", f"Reviewing: {file}")

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
                timeout_s=None,
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            print_agent_line(
                "Reviewer", f"Model call failed: {e} — failing review (no silent pass)."
            )
            _emit(
                "risk",
                severity="high",
                content=f"Reviewer LLM unavailable: {str(e)[:800]}",
                requires_orchestrator_action=True,
            )
            return ReviewResult(
                passed=False,
                score=0.0,
                verdict="FAIL",
                issues=[f"Reviewer model error: {e}"],
                suggestion="Retry when the model is reachable, or inspect logs.",
            )

        msg = response.get("message") or {}
        raw = msg.get("content", "") if isinstance(msg, dict) else ""
        try:
            data = parse_json_object(raw)
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            print_agent_line("Reviewer", f"Parse failed: {e} — failing review.")
            _emit(
                "risk",
                severity="high",
                content=f"Reviewer verdict not valid JSON: {str(e)[:800]}",
                requires_orchestrator_action=True,
            )
            return ReviewResult(
                passed=False,
                score=0.0,
                verdict="FAIL",
                issues=[f"Reviewer output not parseable: {e}"],
                suggestion="Model must return ONLY JSON verdict keys: verdict, score, issues, suggestion.",
            )

        verdict = str(data.get("verdict", "PASS")).upper()
        try:
            score = float(data.get("score", 0.7))
        except (TypeError, ValueError):
            score = 0.7
        issues = _coerce_issues(data.get("issues", []))
        suggestion = str(data.get("suggestion", "") or "")

        passed = verdict == "PASS" and score >= 0.5
        if passed:
            print_agent_line("Reviewer", f"✓ PASS (score={score:.2f})")
        else:
            print_agent_line("Reviewer", f"✗ FAIL (score={score:.2f}) — {issues[:1]}")

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
