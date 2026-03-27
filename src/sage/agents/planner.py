"""
SAGE Planner Agent
------------------
Converts user prompt → Task DAG + project spec.
Primary model: qwen3:14b (local) / Claude (cloud fallback)
Output schema: list of TaskNode dicts

Pipeline:
  1. Load planner.md template
  2. Brainstorming checkpoint (ask clarifying Qs if needed)
  3. Call Ollama → get JSON DAG
  4. Validate output schema
  5. Return TaskGraph
"""

import json
import os
from pathlib import Path

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_json_object
from sage.cli.branding import print_agent_line
from sage.orchestrator.model_router import ModelRouter
from sage.protocol.schemas import TaskNode
from sage.protocol.schemas import AgentInsight
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "planner.md"


def _planner_chat_timeout_s() -> float | None:
    """Override with SAGE_PLANNER_CHAT_TIMEOUT_S; else same as global (see default_chat_timeout_s)."""
    raw = (os.environ.get("SAGE_PLANNER_CHAT_TIMEOUT_S") or "").strip()
    if raw:
        try:
            v = float(raw)
            return None if v <= 0 else max(5.0, v)
        except ValueError:
            pass
    from sage.llm.ollama_safe import default_chat_timeout_s

    return default_chat_timeout_s()


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text()
    return ""


def _build_system_prompt(template: str, memory: dict, fix_patterns: list) -> str:
    ctx = json.dumps(memory, indent=2) if memory else "No prior state"
    patterns = json.dumps(fix_patterns, indent=2) if fix_patterns else "None"
    return (
        template.replace("{project_memory_summary}", ctx)
        .replace("{system_state_summary}", ctx)
        .replace("{relevant_fix_patterns_if_applicable}", patterns)
    )


_VALID_AGENTS = frozenset({"coder", "architect", "reviewer", "test_engineer"})


def _normalize_assigned_agent(raw: object) -> str:
    """Map planner / model output to a workflow ``assigned_agent``."""
    if raw is None:
        return "coder"
    s = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "te": "test_engineer",
        "tester": "test_engineer",
        "tests_engineer": "test_engineer",
        "test_eng": "test_engineer",
        "qa": "test_engineer",
        "arch": "architect",
        "architecture": "architect",
        "code": "coder",
        "implementation": "coder",
        "implement": "coder",
        "review": "reviewer",
    }
    s = aliases.get(s, s)
    if s in _VALID_AGENTS:
        return s
    if "test" in s and ("eng" in s or s.endswith("_tests")):
        return "test_engineer"
    return "coder"


def _maybe_upgrade_to_test_engineer(description: str, agent: str) -> str:
    """If the task is clearly test-only but mislabeled, prefer test_engineer."""
    if agent == "test_engineer":
        return agent
    if agent not in ("coder", "reviewer"):
        return agent
    d = (description or "").lower()
    hints = (
        "add test",
        "add tests",
        "pytest",
        "unit test",
        "tests/test",
        "test file",
        "write test",
        "write tests",
        "test suite",
    )
    if any(h in d for h in hints):
        return "test_engineer"
    return agent


def _extract_json(text: str) -> dict:
    """Parse planner JSON via shared :func:`parse_json_object`."""
    return parse_json_object(text)

def _compute_task_complexity_score(text: str) -> float:
    """
    Deterministic heuristic used for ModelRouter fallback triggers.

    The spec expects `task_complexity_score` to exist on TaskNode and be
    available to routing decisions (e.g. YAML expression `> 0.8`).
    """
    t = (text or "").lower()
    # Length contributes up to ~60%.
    length_score = (len(t) / 2500.0) * 0.6
    kw_markers = [
        "build",
        "feature",
        "frontend",
        "backend",
        "database",
        "authentication",
        "jwt",
        "security",
        "integration",
        "refactor",
        "optimization",
        "multi-agent",
        "existing",
        "complex",
        "fix",
        "tdd",
    ]
    kw_hits = sum(1 for m in kw_markers if m in t)
    kw_score = min(kw_hits / 6.0, 1.0) * 0.4
    return float(min(1.0, max(0.0, length_score + kw_score)))


def _validate_dag(dag_data: dict) -> list[TaskNode]:
    """Convert raw dict list into typed TaskNode list."""
    raw = dag_data.get("dag", dag_data)
    if isinstance(raw, list):
        nodes = raw
    elif isinstance(raw, dict):
        nodes = raw.get("nodes", [])
    else:
        nodes = []
    result: list[TaskNode] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        desc = str(n.get("description", "") or "")
        agent = _normalize_assigned_agent(n.get("assigned_agent", "coder"))
        agent = _maybe_upgrade_to_test_engineer(desc, agent)
        result.append(
            TaskNode(
                id=n.get("id", f"task_{len(result):03d}"),
                description=desc,
                dependencies=n.get("dependencies", []),
                assigned_agent=agent,
                verification=n.get("verification", ""),
                epistemic_flags=n.get("epistemic_flags", []),
                strategy_key=n.get("strategy_key", ""),
                task_complexity_score=_compute_task_complexity_score(desc),
                status="pending",
            )
        )
    return result


class PlannerAgent:
    def __init__(self):
        self.router = ModelRouter()
        self.template = _load_template()

    def run(
        self,
        prompt: str,
        memory: dict,
        fix_patterns: list | None = None,
        mode: str = "research",
        failure_count: int = 0,
        universal_prefix: str = "",
        insight_sink=None,
        *,
        clarify_enabled: bool = True,
        clarify_tty: bool = True,
        _clarification_depth: int = 0,
    ) -> list[TaskNode]:
        """
        Returns a list of TaskNode objects.

        When ``clarify_enabled`` and the model returns ``brainstorm_questions``,
        the user is prompted (TTY) for answers — including in ``auto`` mode unless
        disabled via ``--no-clarify`` / ``SAGE_NO_CLARIFY``.
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
                        agent="planner",
                        task_id="planner",  # no task_id yet at DAG time
                        insight_type=insight_type,
                        content=(content or "")[:2000],
                        severity=severity,
                        requires_orchestrator_action=requires_orchestrator_action,
                    )
                )
            except Exception:
                return

        fix_patterns = fix_patterns or []
        model = self.router.select(
            "planner",
            task_complexity_score=_compute_task_complexity_score(prompt),
            failure_count=failure_count,
        )
        _emit(
            "decision",
            severity="low",
            content=f"Planner selected model={model} to generate Task DAG.",
        )

        system = _build_system_prompt(self.template, memory, fix_patterns)

        # Phase 1: inline task description for simplicity
        task_desc = prompt
        system_filled = system.replace("{task_description}", task_desc)
        if universal_prefix:
            system_filled = universal_prefix + "\n\n" + system_filled

        print_agent_line("Planner", f"Using model: {model}")
        print_agent_line("Planner", f"Generating Task DAG for: {prompt!r}")

        # ── Call Ollama ────────────────────────────────────────────────────────
        if ollama is None:
            print_agent_line("Planner", "WARNING: ollama module not available; using fallback DAG.")
            _emit(
                "risk",
                severity="high",
                content="ollama module not available; planner used fallback single-task DAG.",
                requires_orchestrator_action=True,
            )
            return [
                TaskNode(
                    id="task_001",
                    description=prompt,
                    dependencies=[],
                    assigned_agent="coder",
                    task_complexity_score=_compute_task_complexity_score(prompt),
                    epistemic_flags=[],
                    status="pending",
                )
            ]

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system_filled},
                    {
                        "role": "user",
                        "content": (
                            f"Generate a Task DAG for the following goal.\n\n"
                            f"GOAL: {prompt}\n\n"
                            "Return ONLY a JSON object in the specified OUTPUT FORMAT. "
                            "No prose, no explanation outside the JSON."
                        ),
                    },
                ],
                options={"temperature": 0.2},
                timeout_s=_planner_chat_timeout_s(),
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            print_agent_line(
                "Planner", f"Ollama unavailable/timeout ({e}). Falling back to single-task DAG."
            )
            _emit(
                "risk",
                severity="high",
                content=f"planner model call failed/timeout: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return [
                TaskNode(
                    id="task_001",
                    description=prompt,
                    dependencies=[],
                    assigned_agent="coder",
                    task_complexity_score=_compute_task_complexity_score(prompt),
                    epistemic_flags=[],
                    status="pending",
                )
            ]

        raw = response["message"]["content"]

        # ── Parse ──────────────────────────────────────────────────────────────
        try:
            parsed = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            print_agent_line(
                "Planner", f"WARNING: JSON parse failed ({e}). Falling back to single-task DAG."
            )
            _emit(
                "risk",
                severity="high",
                content=f"planner output parse failed: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return [
                TaskNode(
                    id="task_001",
                    description=prompt,
                    dependencies=[],
                    assigned_agent="coder",
                    task_complexity_score=_compute_task_complexity_score(prompt),
                )
            ]

        # ── Clarification checkpoint (brainstorm_questions) ────────────────────
        questions = [str(q).strip() for q in (parsed.get("brainstorm_questions") or []) if str(q).strip()]
        _max_clar_rounds = 2
        if (
            questions
            and clarify_enabled
            and _clarification_depth < _max_clar_rounds
            and mode != "silent"
        ):
            if clarify_tty:
                from sage.cli.clarify import collect_clarification_answers

                print_agent_line("Planner", f"Asking {len(questions)} clarifying question(s)…")
                answers = collect_clarification_answers(questions)
                if answers:
                    return self.run(
                        prompt=f"{prompt}\n\n## User clarifications\n{answers}",
                        memory=memory,
                        fix_patterns=fix_patterns,
                        mode=mode,
                        failure_count=failure_count,
                        universal_prefix=universal_prefix,
                        insight_sink=insight_sink,
                        clarify_enabled=clarify_enabled,
                        clarify_tty=clarify_tty,
                        _clarification_depth=_clarification_depth + 1,
                    )
            else:
                print_agent_line(
                    "Planner",
                    f"Clarifying questions not shown (non-interactive); continuing without answers. "
                    f"Questions were: {questions[:2]}{'…' if len(questions) > 2 else ''}",
                )
        elif questions and not clarify_enabled:
            print_agent_line(
                "Planner",
                f"Clarification skipped (--no-clarify or SAGE_NO_CLARIFY); {len(questions)} question(s) ignored.",
            )

        # ── Validate + return ──────────────────────────────────────────────────
        try:
            nodes = _validate_dag(parsed)
        except Exception as e:
            print_agent_line(
                "Planner", f"WARNING: DAG validation failed ({e}). Single-task fallback."
            )
            _emit(
                "risk",
                severity="high",
                content=f"planner DAG validation failed: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return [
                TaskNode(
                    id="task_001",
                    description=prompt,
                    dependencies=[],
                    assigned_agent="coder",
                    task_complexity_score=_compute_task_complexity_score(prompt),
                )
            ]

        if not nodes:
            print_agent_line("Planner", "WARNING: Empty DAG returned. Single-task fallback.")
            _emit(
                "risk",
                severity="high",
                content="planner returned empty DAG; using single-task fallback.",
                requires_orchestrator_action=True,
            )
            return [
                TaskNode(
                    id="task_001",
                    description=prompt,
                    dependencies=[],
                    assigned_agent="coder",
                    task_complexity_score=_compute_task_complexity_score(prompt),
                )
            ]

        print_agent_line("Planner", f"DAG ready — {len(nodes)} task(s):")
        for n in nodes:
            deps = f" (depends: {', '.join(n.dependencies)})" if n.dependencies else ""
            print(f"  [{n.id}] {n.description[:80]}{deps}")

        _emit(
            "observation",
            severity="low",
            content=f"Planner DAG ready with {len(nodes)} node(s).",
            requires_orchestrator_action=False,
        )
        return nodes
