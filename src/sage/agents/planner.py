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
import re
from pathlib import Path

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.orchestrator.model_router import ModelRouter
from sage.protocol.schemas import TaskNode
from sage.protocol.schemas import AgentInsight
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "planner.md"


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


def _extract_json(text: str) -> dict:
    """
    Extract the first JSON object from the model's response.
    Models sometimes wrap JSON in markdown code fences.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)

    # Also strip <think>...</think> blocks (qwen3 chain-of-thought)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Find first {...}
    match = re.search(r"\{[\s\S]+\}", text)
    if not match:
        raise ValueError(f"No JSON object found in model response:\n{text[:500]}")
    return json.loads(match.group())


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
    nodes = dag_data.get("dag", dag_data).get("nodes", [])
    result: list[TaskNode] = []
    for n in nodes:
        result.append(
            TaskNode(
                id=n.get("id", f"task_{len(result):03d}"),
                description=n.get("description", ""),
                dependencies=n.get("dependencies", []),
                assigned_agent=n.get("assigned_agent", "coder"),
                verification=n.get("verification", ""),
                epistemic_flags=n.get("epistemic_flags", []),
                strategy_key=n.get("strategy_key", ""),
                task_complexity_score=_compute_task_complexity_score(n.get("description", "")),
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
    ) -> list[TaskNode]:
        """
        Returns a list of TaskNode objects.
        In 'research' mode, prints brainstorm questions and waits.
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

        print(f"\n[Planner] Using model: {model}")
        print(f"[Planner] Generating Task DAG for: {prompt!r}\n")

        # ── Call Ollama ────────────────────────────────────────────────────────
        if ollama is None:
            print("[Planner] WARNING: ollama module not available; using fallback DAG.")
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
                timeout_s=6.0,
            )
        except (OllamaTimeout, RuntimeError) as e:
            print(f"[Planner] Ollama unavailable/timeout ({e}). Falling back to single-task DAG.")
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
            print(f"[Planner] WARNING: JSON parse failed ({e}). Falling back to single-task DAG.")
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

        # ── Brainstorm checkpoint ──────────────────────────────────────────────
        questions = parsed.get("brainstorm_questions", [])
        if questions and mode == "research":
            print("\n[Planner] Clarifying questions before generating DAG:")
            for i, q in enumerate(questions, 1):
                print(f"  {i}. {q}")
            print()
            try:
                answers = input("[You] Your answers (or press Enter to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                answers = ""
            if answers:
                # Re-run with clarifications injected
                return self.run(
                    prompt=f"{prompt}\n\nClarifications: {answers}",
                    memory=memory,
                    fix_patterns=fix_patterns,
                    mode=mode,
                    failure_count=failure_count,
                )
        # auto/silent mode: skip brainstorm, log questions if any
        elif questions and mode != "research":
            print(f"[Planner] Brainstorm questions suppressed in {mode!r} mode.")

        # ── Validate + return ──────────────────────────────────────────────────
        try:
            nodes = _validate_dag(parsed)
        except Exception as e:
            print(f"[Planner] WARNING: DAG validation failed ({e}). Single-task fallback.")
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
            print("[Planner] WARNING: Empty DAG returned. Single-task fallback.")
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

        print(f"[Planner] DAG ready — {len(nodes)} task(s):")
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
