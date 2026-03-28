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
import re
import sys
from dataclasses import replace
from pathlib import Path

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_json_value
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


_VALID_AGENTS = frozenset({"coder", "architect", "reviewer", "test_engineer", "documentation"})

# Stronger than py_compile alone when the user asked for a real HTTP stack.
_FASTAPI_APP_VERIFY = (
    "python -m py_compile src/app.py && python -c "
    "\"import sys; sys.path.insert(0, 'src'); import app; "
    "assert getattr(app, 'app', None) is not None\""
)

_REQ_FASTAPI_SNIPPET = (
    'python -c "from pathlib import Path; '
    "p=Path('requirements.txt'); "
    "assert p.exists(), 'missing requirements.txt'; "
    "t=p.read_text(errors='ignore').lower(); "
    "assert 'fastapi' in t and 'uvicorn' in t, 'need fastapi and uvicorn in requirements'\""
)

# Non-web greenfield: manifest must exist and be non-empty — never py_compile on .txt.
_REQ_GENERIC_SNIPPET = (
    'python -c "from pathlib import Path; '
    "c=[Path('requirements.txt'),Path('src/requirements.txt')]; "
    "ok=next((p for p in c if p.is_file() and p.read_text(errors='ignore').strip()), None); "
    "assert ok is not None, 'missing or empty requirements.txt'\""
)


def _default_doc_verification(description: str) -> str:
    """Portable check that a primary doc file exists and is non-trivial."""
    d = (description or "").lower()
    if "contributing" in d:
        target = "CONTRIBUTING.md"
    elif "changelog" in d:
        target = "CHANGELOG.md"
    else:
        target = "README.md"
    return (
        "python -c \"from pathlib import Path; p=Path('%s'); "
        "assert p.is_file(), 'missing %s'; "
        "t=p.read_text(errors='ignore').strip(); "
        "assert len(t)>40 and t.count(chr(10))>=1, '%s too thin'\"" % (target, target, target)
    )


def _fallback_verification_for_goal(goal: str) -> str:
    g = (goal or "").lower()
    if "fastapi" in g or "/health" in g or " health" in g:
        return _FASTAPI_APP_VERIFY
    m = re.search(r"\bsrc/[\w./]+\.py\b", goal or "", flags=re.I)
    if m:
        return f"python -m py_compile {m.group(0)}"
    return "python -m py_compile src/app.py"


def _heuristic_library_plus_test_tasks(prompt: str) -> list[TaskNode] | None:
    """
    When JSON parsing fails, split obvious ``src/*.py`` + ``tests/test_*.py`` goals into
    two tasks so the coder is not asked to emit two files in one patch (small models fail).
    """
    pl = (prompt or "").replace("\n", " ")
    srcs = re.findall(r"\bsrc/[\w./]+\.py\b", pl, flags=re.I)
    tests = re.findall(r"\btests/test_[\w]+\.py\b", pl, flags=re.I)
    if len(srcs) != 1 or len(tests) != 1:
        return None
    src_f = srcs[0].replace("\\", "/")
    test_f = tests[0].replace("\\", "/")
    v_impl = f"python -m py_compile {src_f}"
    v_test = f"{sys.executable} -m pytest {test_f} -q"
    return [
        TaskNode(
            id="task_001",
            description=(
                f"Implement {src_f}: functions/classes required by the goal "
                f"(e.g. greet()) so imports and behavior match the prompt."
            ),
            dependencies=[],
            assigned_agent="coder",
            verification=v_impl,
            task_complexity_score=_compute_task_complexity_score(prompt),
            epistemic_flags=[],
            status="pending",
        ),
        TaskNode(
            id="task_002",
            description=(
                f"Add {test_f} with pytest tests that exercise the implementation "
                f"from {src_f} per the goal."
            ),
            dependencies=["task_001"],
            assigned_agent="test_engineer",
            verification=v_test,
            task_complexity_score=_compute_task_complexity_score(prompt),
            epistemic_flags=[],
            status="pending",
        ),
    ]


def _repair_dag_if_goal_mismatch(prompt: str, nodes: list[TaskNode]) -> list[TaskNode]:
    """
    Small models often emit a canned FastAPI 4-task DAG. When the user goal explicitly
    names ``src/foo.py`` and ``tests/test_*.py`` and does not ask for HTTP/FastAPI, replace
    the DAG with the 2-task library + pytest heuristic.
    """
    alt = _heuristic_library_plus_test_tasks(prompt)
    if not alt:
        return nodes
    g = _goal_for_stack_detection(prompt)
    if any(x in g for x in ("fastapi", "/health", "uvicorn")):
        return nodes
    blog = " ".join((n.description or "").lower() for n in nodes).replace("\\", "/")
    srcs = re.findall(r"\bsrc/[\w./]+\.py\b", prompt, flags=re.I)
    tests = re.findall(r"\btests/test_[\w]+\.py\b", prompt, flags=re.I)
    if len(srcs) == 1 and len(tests) == 1:
        ws = srcs[0].lower().replace("\\", "/")
        wt = tests[0].lower().replace("\\", "/")
        if ws in blog and wt in blog:
            return nodes
    if "fastapi" in blog or "src/app.py" in blog or "testclient" in blog or "test_app.py" in blog:
        print_agent_line(
            "Planner",
            "Replacing generic web-app DAG with implement + test tasks matching your goal.",
        )
        return alt
    return nodes


def _fallback_dag_nodes(prompt: str, *, log_line: str) -> list[TaskNode]:
    """One coder task, or implement + test split when ``src/*.py`` + ``tests/test_*.py`` match."""
    h = _heuristic_library_plus_test_tasks(prompt)
    if h:
        print_agent_line("Planner", log_line)
        return h
    return [
        TaskNode(
            id="task_001",
            description=prompt,
            dependencies=[],
            assigned_agent="coder",
            verification=_fallback_verification_for_goal(prompt),
            task_complexity_score=_compute_task_complexity_score(prompt),
            epistemic_flags=[],
            status="pending",
        )
    ]


def _warn_goal_mismatch_health_stub(goal: str, nodes: list[TaskNode]) -> None:
    """
    If the user asked for a rich web app but every task looks like a /health template,
    emit a visible warning (planner template should prevent this; models still slip).
    """
    g = (goal or "").lower()
    rich_goal = any(
        k in g
        for k in (
            "calculator",
            "html",
            "single page",
            "single-page",
            "evaluate",
            "/api",
            "dashboard",
            "form",
            "post endpoint",
            "post /",
        )
    )
    if not rich_goal:
        return
    blob = " ".join((n.description or "") for n in nodes).lower()
    if "/health" not in blob:
        return
    if any(x in blob for x in ("calculator", "html", "eval", "/api", "index.html", "post")):
        return
    print_agent_line(
        "Planner",
        "WARNING: DAG mentions /health but not the GOAL’s UI/API features — "
        "model may have ignored the prompt; re-run or use a larger planner model.",
    )


def _dedupe_task_nodes(nodes: list[TaskNode]) -> list[TaskNode]:
    """
    Drop duplicate tasks that share the same description, dependencies, and agent.

    Planners sometimes emit parallel clones (e.g. three identical “Implement src/app.py…”).
    Dependencies are rewritten so references to removed ids point to the kept id.
    """
    key_to_kept_id: dict[tuple, str] = {}
    removed_to_kept: dict[str, str] = {}
    for n in nodes:
        key = (
            (n.description or "").strip().lower(),
            tuple(n.dependencies or []),
            n.assigned_agent,
        )
        if key in key_to_kept_id:
            removed_to_kept[n.id] = key_to_kept_id[key]
        else:
            key_to_kept_id[key] = n.id

    if not removed_to_kept:
        return nodes

    def resolve_dep(did: str) -> str:
        while did in removed_to_kept:
            did = removed_to_kept[did]
        return did

    out: list[TaskNode] = []
    for n in nodes:
        if n.id in removed_to_kept:
            continue
        new_deps: list[str] = []
        for d in n.dependencies or []:
            rd = resolve_dep(d)
            if rd not in new_deps:
                new_deps.append(rd)
        out.append(replace(n, dependencies=new_deps))
    print_agent_line(
        "Planner",
        f"Merged {len(removed_to_kept)} duplicate DAG node(s) (same description+deps+agent).",
    )
    return out


def _goal_for_stack_detection(user_goal: str) -> str:
    """
    Use only the user-visible goal for FastAPI/requirements heuristics.

    ``prompt_middleware`` may append ``CODEBASE CONVENTIONS`` blocks; those can mention
    frameworks and falsely trigger FastAPI-specific verification.
    """
    g = user_goal or ""
    for sep in ("\nCODEBASE CONVENTIONS", "\n## CODEBASE CONVENTIONS", "\n---\n"):
        if sep in g:
            g = g.split(sep, 1)[0]
            break
    return g.lower()


def _postprocess_task_nodes(nodes: list[TaskNode], user_goal: str) -> list[TaskNode]:
    """
    Patch weak model output: py_compile-only implementation tasks for FastAPI goals,
    and empty/weak requirements checks.
    """
    g = _goal_for_stack_detection(user_goal)
    out: list[TaskNode] = []
    for n in nodes:
        nn = n
        desc_l = (n.description or "").lower()
        merged = f"{g} {desc_l}"
        v = (nn.verification or "").strip()

        if nn.assigned_agent == "coder":
            # Dependency manifest: only use FastAPI-specific checks when the *user goal* asks for
            # a web stack — not when the planner hallucinated "FastAPI" into a task description.
            want_fastapi_stack = "fastapi" in g or "/health" in g or " uvicorn" in g
            if "requirements" in desc_l:
                if want_fastapi_stack:
                    if not v or ("assert" not in v and "fastapi" not in v.lower()):
                        nn = replace(nn, verification=_REQ_FASTAPI_SNIPPET)
                        v = nn.verification
                else:
                    if (
                        (not v)
                        or "py_compile" in v
                        or (v and "fastapi" in v.lower() and not want_fastapi_stack)
                    ):
                        nn = replace(nn, verification=_REQ_GENERIC_SNIPPET)
                        v = nn.verification
            if (
                want_fastapi_stack
                and "fastapi" in merged
                and v
                and "py_compile" in v
                and "import app" not in v
            ):
                if "src/app.py" in v or "src/app.py" in desc_l:
                    if "&&" not in v:
                        nn = replace(nn, verification=_FASTAPI_APP_VERIFY)
        if nn.assigned_agent == "documentation":
            if not v or len(v.strip()) < 8:
                nn = replace(nn, verification=_default_doc_verification(nn.description))
        out.append(nn)
    return out


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
        "docs": "documentation",
        "doc": "documentation",
        "documents": "documentation",
        "documenter": "documentation",
        "technical_writer": "documentation",
        "tech_writer": "documentation",
    }
    s = aliases.get(s, s)
    if s in _VALID_AGENTS:
        return s
    if "test" in s and ("eng" in s or s.endswith("_tests")):
        return "test_engineer"
    if "documentation" in s or s.endswith("_docs"):
        return "documentation"
    return "coder"


def _maybe_upgrade_to_documentation(description: str, agent: str) -> str:
    if agent == "documentation" or agent == "test_engineer":
        return agent
    if agent not in ("coder", "reviewer", "architect"):
        return agent
    d = (description or "").lower()
    if any(
        k in d
        for k in (
            "pytest",
            "unit test",
            "unit tests",
            "test file",
            "add test",
            "add tests",
            "write test",
            "write tests",
            "tests/test",
            "tests\\test",
        )
    ):
        return agent
    doc_hints = (
        "readme",
        "changelog",
        "contributing",
        "documentation",
        "user guide",
        " markdown ",
        "docs/",
        "doc/",
        "api reference",
    )
    if any(h in d for h in doc_hints):
        return "documentation"
    return agent


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
    """
    Parse planner JSON. Models sometimes emit a **raw array** of task nodes instead of
    ``{\"nodes\": [...]}`` — accept both.
    """
    val = parse_json_value(text)
    if isinstance(val, dict):
        return val
    if isinstance(val, list):
        return {"dag": val}
    raise ValueError(f"Planner JSON must be object or array, got {type(val).__name__}")


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
        agent = _maybe_upgrade_to_documentation(desc, agent)
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
            return _fallback_dag_nodes(
                prompt,
                log_line="Ollama unavailable — using fallback DAG (heuristic split if applicable).",
            )

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
            return _fallback_dag_nodes(
                prompt,
                log_line="Planner call failed — fallback DAG (heuristic split if applicable).",
            )

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
            return _fallback_dag_nodes(
                prompt,
                log_line="JSON parse failed — fallback DAG (heuristic split if applicable).",
            )

        # ── Clarification checkpoint (brainstorm_questions) ────────────────────
        questions = [
            str(q).strip() for q in (parsed.get("brainstorm_questions") or []) if str(q).strip()
        ]
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
            return _fallback_dag_nodes(
                prompt,
                log_line="DAG validation failed — fallback DAG (heuristic split if applicable).",
            )

        if not nodes:
            print_agent_line("Planner", "WARNING: Empty DAG returned. Single-task fallback.")
            _emit(
                "risk",
                severity="high",
                content="planner returned empty DAG; using single-task fallback.",
                requires_orchestrator_action=True,
            )
            return _fallback_dag_nodes(
                prompt, log_line="Empty planner DAG — fallback (heuristic split if applicable)."
            )

        nodes = _repair_dag_if_goal_mismatch(prompt, nodes)

        nodes = _postprocess_task_nodes(nodes, prompt)
        nodes = _dedupe_task_nodes(nodes)
        _warn_goal_mismatch_health_stub(prompt, nodes)

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
