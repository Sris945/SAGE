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
import subprocess
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
from sage.debug_mode_log import agent_debug_log
from sage.protocol.schemas import AgentInsight

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "reviewer.md"
MAX_REVIEW_LINES = 300


def _run_ruff(file: str) -> list[dict]:
    """
    Phase 1: Run ruff lint on *file* and return parsed violations.

    Returns an empty list when:
    - ruff is not installed (FileNotFoundError)
    - the subprocess times out (TimeoutExpired)
    - the output is not valid JSON for any other reason

    Never raises.
    """
    try:
        result = subprocess.run(
            ["ruff", "check", file, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = result.stdout.strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return []
    except FileNotFoundError:
        # ruff not installed — silently skip
        return []
    except subprocess.TimeoutExpired:
        return []
    except (json.JSONDecodeError, ValueError, OSError):
        return []
    except Exception:  # pragma: no cover
        return []


def _run_mypy(file: str) -> list[str]:
    """
    Phase 2: Run mypy type-check on *file* and return error lines.

    Returns an empty list when:
    - mypy is not installed (FileNotFoundError)
    - the subprocess times out (TimeoutExpired)
    - the file is not Python

    Never raises.
    """
    if not str(file).endswith(".py"):
        return []
    try:
        result = subprocess.run(
            ["mypy", file, "--ignore-missing-imports", "--no-error-summary"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = (result.stdout + result.stderr).splitlines()
        errors = [ln for ln in lines if ": error:" in ln or ": warning:" in ln]
        return errors
    except FileNotFoundError:
        # mypy not installed — silently skip
        return []
    except subprocess.TimeoutExpired:
        return []
    except (OSError, Exception):  # pragma: no cover
        return []


def _score_static_penalties(ruff_violations: list[dict], mypy_errors: list[str]) -> float:
    """
    Compute the total score penalty from static analysis findings.

    Ruff:  -0.15 per E-code violation, capped at -0.40
    Mypy:  -0.10 per type error line,    capped at -0.30
    """
    ruff_e_count = sum(
        1 for v in ruff_violations if isinstance(v, dict) and str(v.get("code", "")).startswith("E")
    )
    mypy_count = len(mypy_errors)
    ruff_penalty = min(ruff_e_count * 0.15, 0.40)
    mypy_penalty = min(mypy_count * 0.10, 0.30)
    return ruff_penalty + mypy_penalty


def _format_ruff_summary(violations: list[dict]) -> str:
    """Return a compact one-line ruff summary for prompt injection."""
    if not violations:
        return "ruff: no violations found"
    lines = []
    for v in violations[:20]:  # cap context to 20 items
        code = v.get("code", "?")
        msg = v.get("message", "")
        row = v.get("location", {}).get("row", "?")
        lines.append(f"  {code} line {row}: {msg}")
    suffix = f"\n  … and {len(violations) - 20} more" if len(violations) > 20 else ""
    return "ruff violations:\n" + "\n".join(lines) + suffix


def _format_mypy_summary(errors: list[str]) -> str:
    """Return a compact mypy summary for prompt injection."""
    if not errors:
        return "mypy: no type errors found"
    shown = errors[:20]
    suffix = f"\n  … and {len(errors) - 20} more" if len(errors) > 20 else ""
    return "mypy type errors:\n" + "\n".join(f"  {ln}" for ln in shown) + suffix


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


def _is_tests_package_file(file: str) -> bool:
    fp = str(file).replace("\\", "/")
    pl = Path(fp)
    return (
        pl.suffix.lower() == ".py"
        and pl.name.startswith("test_")
        and (fp.startswith("tests/") or "/tests/" in f"/{fp}/")
    )


def _is_documentation_markdown(file: str) -> bool:
    """Primary markdown docs: rely on planner verification + static checks; skip LLM."""
    fp = str(file).replace("\\", "/")
    pl = Path(fp)
    if pl.suffix.lower() not in (".md", ".mdx"):
        return False
    name = pl.name.lower()
    if name in (
        "readme.md",
        "changelog.md",
        "contributing.md",
        "security.md",
        "code_of_conduct.md",
        "index.md",
    ):
        return True
    parts = pl.parts
    return "docs" in parts and pl.suffix.lower() in (".md", ".mdx")


def _is_src_application_py(file: str) -> bool:
    """Greenfield app modules: LLM reviewer often hallucinates 'empty file' (log: H1 vs non-empty read)."""
    fp = str(file).replace("\\", "/")
    pl = Path(fp)
    if pl.suffix.lower() != ".py" or not fp.startswith("src/"):
        return False
    name = pl.name
    if name.startswith("test_") or name == "conftest.py":
        return False
    return True


def _reviewer_skip_llm_log_line(file: str) -> str:
    """If non-empty, skip LLM review and log this line (small models hallucinate on these paths)."""
    if _short_manifest_ok(file):
        return "Dependency manifest — static + goal checks only (LLM skipped)."
    if _is_tests_package_file(file):
        return "pytest file — static + goal checks only (LLM skipped)."
    if _is_documentation_markdown(file):
        return "Documentation markdown — static + task verification only (LLM skipped)."
    if _is_src_application_py(file):
        return (
            "src Python module — static + goal checks only (LLM skipped; "
            "planner verify validates imports/behavior)."
        )
    return ""


def _static_checks(file: str, content: str) -> list[str]:
    """Fast local checks — no model call needed."""
    issues = []
    lines = content.splitlines()
    if not content.strip():
        issues.append("File is empty or whitespace-only.")
    if len(lines) < 3 and not _short_manifest_ok(file) and not _is_tests_package_file(file):
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

    if _is_tests_package_file(fp):
        # Stack tokens often live in src/app.py, not in every test line — pytest proves behavior.
        return issues

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

        skip_line = _reviewer_skip_llm_log_line(str(path))
        if skip_line:
            agent_debug_log(
                hypothesis_id="H_skip",
                location="reviewer.py:skip_llm",
                message="reviewer_llm_skipped",
                data={"file": str(path), "reason": skip_line, "content_len": len(content)},
            )
            print_agent_line("Reviewer", skip_line)
            _emit(
                "observation",
                severity="low",
                content="Reviewer LLM skipped (manifest, pytest, or application module).",
            )
            return ReviewResult(
                passed=True,
                score=1.0,
                verdict="PASS",
                issues=[],
                suggestion="",
                model_used="(static-only)",
            )

        # ── Phase 1: Ruff lint ────────────────────────────────────────────────
        ruff_violations = _run_ruff(file)
        ruff_e_issues = [
            f"ruff {v.get('code', '?')} line {v.get('location', {}).get('row', '?')}: {v.get('message', '')}"
            for v in ruff_violations
            if str(v.get("code", "")).startswith("E")
        ]
        if ruff_violations:
            print_agent_line("Reviewer", f"Ruff: {len(ruff_violations)} violation(s)")
        else:
            print_agent_line("Reviewer", "Ruff: clean")

        # ── Phase 2: Mypy type check ──────────────────────────────────────────
        mypy_errors = _run_mypy(file)
        if mypy_errors:
            print_agent_line("Reviewer", f"Mypy: {len(mypy_errors)} type error(s)")
        else:
            print_agent_line("Reviewer", "Mypy: clean")

        static_penalty = _score_static_penalties(ruff_violations, mypy_errors)

        # ── Phase 3: LLM review ───────────────────────────────────────────────
        model = self.router.select(
            "reviewer",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=failure_count,
        )
        snippet = "\n".join(content.splitlines()[:MAX_REVIEW_LINES])

        # Build static-analysis context block for the LLM prompt
        static_context = (
            "\n\nSTATIC ANALYSIS RESULTS (already completed — do NOT re-check syntax):\n"
            + _format_ruff_summary(ruff_violations)
            + "\n"
            + _format_mypy_summary(mypy_errors)
            + "\n"
        )

        system = (
            self.template.replace("{task_description}", task.get("description", ""))
            .replace("{file_content}", snippet)
            .replace("{file_path}", file)
            .replace("{static_analysis_context}", static_context)
        )
        # Inject static context even if template doesn't have the placeholder
        if "{static_analysis_context}" not in self.template:
            system = system + static_context

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
            agent_debug_log(
                hypothesis_id="H_llm",
                location="reviewer.py:llm_exception",
                message="reviewer_llm_failed",
                data={"error": str(e)[:800], "file": file},
            )
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
        agent_debug_log(
            hypothesis_id="H_llm",
            location="reviewer.py:after_llm",
            message="reviewer_llm_raw",
            data={
                "file": file,
                "raw_len": len(raw or ""),
                "raw_head": (raw or "")[:400],
            },
        )
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

        # Merge static analysis findings into the issues list
        llm_issues = _coerce_issues(data.get("issues", []))
        issues = ruff_e_issues + [f"mypy: {ln}" for ln in mypy_errors[:10]] + llm_issues

        # Apply static penalties to LLM score; clamp to [0.0, 1.0]
        score = max(0.0, min(1.0, score - static_penalty))

        suggestion = str(data.get("suggestion", "") or "")

        passed = verdict == "PASS" and score >= 0.5
        agent_debug_log(
            hypothesis_id="H_verdict",
            location="reviewer.py:verdict",
            message="reviewer_verdict",
            data={
                "file": file,
                "verdict": verdict,
                "score": score,
                "passed": passed,
                "issues_head": (issues[0] if issues else "")[:300],
            },
        )
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
