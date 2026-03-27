"""
SAGE LangGraph Workflow Skeleton  —  Phase 1
---------------------------------------------
Core state machine: load_memory → prompt_middleware → model_router →
planner → human_checkpoint → scheduler → execute_agent → save_memory

Phase 2 adds: tool_executor → check_fix_patterns → debug_agent → circuit_breaker
"""

try:
    from langgraph.graph import StateGraph, END  # type: ignore

    _HAS_LANGGRAPH = True
except ModuleNotFoundError:  # pragma: no cover
    StateGraph = None  # type: ignore
    END = object()  # type: ignore
    _HAS_LANGGRAPH = False
from datetime import datetime, timezone

from sage.orchestrator.event_bus import EventBus
from sage.protocol.schemas import Event, AgentInsight
from sage.orchestrator.prefix_builder import build_prefix_for_agent
from sage.orchestrator.state import SAGEState


# ── Event bus (Phase 3+ in spec; minimal MVP wiring here) ────────────────────
EVENT_BUS = EventBus()


def _on_task_completed(event: Event) -> None:
    """
    MVP handler:
      - when TASK_COMPLETED events arrive, if completed_count % 5 == 0,
        emit a MEMORY_CHECKPOINT event.
    """
    completed_count = int((event.payload or {}).get("completed_count", 0) or 0)
    if completed_count > 0 and completed_count % 5 == 0:
        EVENT_BUS.emit_sync(
            Event(
                type="MEMORY_CHECKPOINT",
                task_id=event.task_id,
                payload={"completed_count": completed_count},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )


def _on_memory_checkpoint(event: Event) -> None:
    """Write a checkpoint line into the session journal."""
    completed_count = int((event.payload or {}).get("completed_count", 0) or 0)
    from sage.observability.structured_logger import log_event

    log_event(
        "MEMORY_CHECKPOINT",
        payload={"completed_count": completed_count},
        timestamp=event.timestamp,
    )


EVENT_BUS.subscribe("TASK_COMPLETED", _on_task_completed)
EVENT_BUS.subscribe("MEMORY_CHECKPOINT", _on_memory_checkpoint)


# ── Node stubs (Phase 1: sequential pipeline only) ───────────────────────────


def load_memory(state: SAGEState) -> SAGEState:
    """
    SessionStart hook.
    1. Check for handoff.json → resume mode
    2. Load system_state.json
    """
    from sage.memory.manager import MemoryManager
    from sage.orchestrator.session_manager import SessionManager
    from sage.agents.memory_optimizer import load_sage_memory
    from sage.orchestrator.intelligence_feed import OrchestratorIntelligenceFeed

    sm = SessionManager()
    handoff = sm.check_handoff()
    mm = MemoryManager()
    session_memory = mm.load_state()

    # Inject .sage-memory.md as cross-session context
    sage_memory_summary = load_sage_memory()
    if sage_memory_summary:
        session_memory["sage_memory_summary"] = sage_memory_summary

    return {
        **state,
        "session_memory": session_memory,
        "insight_feed": OrchestratorIntelligenceFeed(),
        "architect_blueprints_by_task": state.get("architect_blueprints_by_task", {}),
        "task_updates": [],
        "resume_from_handoff": handoff is not None,
        "events": [],
    }


def prompt_middleware(state: SAGEState) -> SAGEState:
    """
    UserPromptSubmit hook — Phase 4: RAG over fix_patterns.json.
    1. Build in-memory index from fix_patterns.json (nomic-embed-text)
    2. Query top-3 patterns by cosine similarity to user prompt
    3. Inject retrieved patterns into enhanced_prompt for planner/coder context
    Falls back gracefully if no patterns exist or embedding fails.
    """
    from sage.memory.rag_retriever import RagRetriever, format_patterns_for_prompt

    prompt = state["user_prompt"]
    rag_context = ""
    docs_context = ""

    try:
        retriever = RagRetriever()
        count = retriever.build_index()
        if count > 0:
            hits = retriever.query(prompt, k=3)
            high_confidence = [h for h in hits if h.get("score", 0) >= 0.5]
            if high_confidence:
                rag_context = "\n\n" + format_patterns_for_prompt(high_confidence)
                print(f"[RAG] Injecting {len(high_confidence)} pattern(s) into prompt context.")
    except Exception as e:
        print(f"[RAG] Retrieval skipped: {e}")

    enhanced = prompt + rag_context

    # Phase 4: Prompt Intelligence Middleware (RAG over docs) — MVP via Qdrant.
    def _deterministic_prompt_quality(text: str) -> float:
        """
        Offline prompt quality heuristic (0.0–1.0).

        This is a publishable, deterministic proxy used to compute strict
        middleware before/after deltas even when LLM review is unavailable.
        """
        t = text or ""
        if not t.strip():
            return 0.0

        # Normalize length into [0,1] with diminishing returns.
        length_score = min(len(t) / 2000.0, 1.0)

        # Presence of structure/instructions in the prompt.
        instruction_markers = [
            "must",
            "should",
            "constraints",
            "requirements",
            "tdd",
            "tests",
            "edge cases",
            "security",
            "schema",
            "json",
            "universal prefix",
        ]
        marker_hits = sum(1 for m in instruction_markers if m.lower() in t.lower())
        marker_score = min(marker_hits / 5.0, 1.0)

        # Reward explicit formatting / examples.
        code_fence = 1.0 if "```" in t else 0.0
        example_score = 1.0 if "example" in t.lower() else 0.0

        # Weighted sum, clamped.
        score = (
            0.20
            + 0.40 * length_score
            + 0.30 * marker_score
            + 0.10 * (0.5 * code_fence + 0.5 * example_score)
        )
        if score < 0.0:
            return 0.0
        if score > 1.0:
            return 1.0
        return float(score)

    try:
        from sage.memory.docs_rag_retriever import get_docs_rag_context

        docs_context = get_docs_rag_context(prompt, k=3)
    except Exception as e:
        print(f"[DocsRAG] Retrieval skipped: {e}")

    # Strict prompt-quality delta measurement:
    # - before_score: raw user prompt quality
    # - after_score: final enhanced_prompt quality after all middleware injections
    before_score = _deterministic_prompt_quality(prompt)

    enhanced = prompt + rag_context + docs_context

    # Store raw retrieved patterns for prompt prefix injection.
    # (We keep them as objects so `format_patterns_for_prompt` can render later.)
    retrieved_patterns: list[dict] = []
    try:
        # Re-run retrieval quickly to capture `high_confidence` objects.
        retriever = RagRetriever()
        if retriever.build_index() > 0:
            hits = retriever.query(prompt, k=3)
            retrieved_patterns = [h for h in hits if h.get("score", 0) >= 0.5]
    except Exception:
        retrieved_patterns = []

    # Inject codebase conventions (if existing-repo mode created `.sage/` cache).
    try:
        from pathlib import Path

        conventions_path = Path(".sage") / "conventions.md"
        if conventions_path.exists():
            conventions_md = conventions_path.read_text(errors="ignore")
            if conventions_md.strip():
                enhanced = (
                    prompt
                    + "\n\n"
                    + "CODEBASE CONVENTIONS:\n"
                    + conventions_md
                    + rag_context
                    + docs_context
                )
    except Exception:
        # Keep prompt_middleware resilient: if conventions injection fails,
        # fall back to fix-pattern injection only.
        enhanced = prompt + rag_context + docs_context

    # Emit strict prompt-quality delta instrumentation for Phase 4.
    try:
        from sage.observability.structured_logger import log_event

        after_score = _deterministic_prompt_quality(enhanced)
        log_event(
            "PROMPT_QUALITY_DELTA",
            payload={
                "task_id": "prompt_middleware",
                "agent": "prompt_middleware",
                "passed": True,
                "reviewer_score": after_score,
                "quality_delta": after_score - before_score,
                "model_used": "",
                "issues": [],
                "before_score": before_score,
                "after_score": after_score,
            },
        )
    except Exception:
        pass

    return {**state, "enhanced_prompt": enhanced, "retrieved_fix_patterns": retrieved_patterns}


def route_model(state: SAGEState) -> SAGEState:
    """Assign model to planner based on routing table."""
    from sage.orchestrator.model_router import ModelRouter
    from sage.agents.planner import _compute_task_complexity_score

    router = ModelRouter()
    model = router.select(
        "planner",
        task_complexity_score=_compute_task_complexity_score(
            state.get("enhanced_prompt") or state.get("user_prompt") or ""
        ),
        failure_count=0,
    )
    return {**state, "session_memory": {**state["session_memory"], "planner_model": model}}


def run_planner(state: SAGEState) -> SAGEState:
    """
    Planner produces Task DAG from enhanced prompt via real Ollama call.
    Optional clarification Q&A when ``brainstorm_questions`` is set (see ``clarify`` flag).
    """
    import os
    import sys

    from sage.agents.planner import PlannerAgent
    from sage.cli.clarify import should_offer_clarification
    from sage.orchestrator.task_graph import TaskGraph

    agent = PlannerAgent()
    universal_prefix = build_prefix_for_agent(state, agent_role="planner", task_id=None)
    mode = state.get("mode", "research")
    clarify_flag = bool(state.get("clarify", True))
    no_env = bool((os.environ.get("SAGE_NO_CLARIFY") or "").strip())
    offer = should_offer_clarification(
        mode=str(mode),
        clarify_flag=clarify_flag,
        no_clarify_env=no_env,
    )
    nodes = agent.run(
        prompt=state["enhanced_prompt"] or state["user_prompt"],
        memory=state["session_memory"],
        mode=mode,
        fix_patterns=state.get("retrieved_fix_patterns") or [],
        universal_prefix=universal_prefix,
        insight_sink=state.get("insight_feed"),
        clarify_enabled=offer,
        clarify_tty=bool(getattr(sys.stdin, "isatty", lambda: False)()),
    )

    graph = TaskGraph()
    for node in nodes:
        graph.add_node(node)

    return {**state, "task_dag": graph.to_dict()}


class HumanCancelledError(RuntimeError):
    """Raised when the user cancels a human-in-the-loop checkpoint."""


def safe_human_confirm(prompt_text: str, *, default_yes: bool = True) -> bool:
    """
    Human confirm helper that is safe in non-interactive environments.

    If stdin is not a TTY, returns `default_yes` without calling `input()`.
    """
    import sys

    try:
        is_tty = bool(getattr(sys.stdin, "isatty", lambda: False)())
    except Exception:
        is_tty = False

    if not is_tty:
        return default_yes

    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    try:
        raw = input(prompt_text + suffix)
    except EOFError:
        return default_yes

    ans = (raw or "").strip().lower()
    if not ans:
        return default_yes
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default_yes


def human_checkpoint_1_post_scan(state: SAGEState) -> SAGEState:
    """
    Human Checkpoint 1 — Post-scan.

    Only triggers in `--research` mode, after the Codebase Intelligence Layer
    for `existing_repo` runs.
    """
    if state.get("mode") != "research":
        return state

    from sage.observability.structured_logger import log_event

    brief = (state.get("session_memory") or {}).get("codebase_brief") or {}
    # Keep log payload bounded.
    brief_preview = str(brief)[:1600]

    log_event(
        "HUMAN_CHECKPOINT_REACHED",
        payload={
            "mode": state.get("mode", ""),
            "checkpoint_type": 1,
            "brief_preview": brief_preview,
        },
    )

    ok = safe_human_confirm(
        "[SAGE] HUMAN CHECKPOINT 1 (post-scan): confirm codebase understanding?",
        default_yes=True,
    )
    if not ok:
        raise HumanCancelledError("Human cancelled checkpoint 1 (post-scan).")
    return state


def human_checkpoint(state: SAGEState) -> SAGEState:
    """
    Human Checkpoint 2 — Post-planning.
    In --research mode: blocks for user approval.
    In --auto / --silent mode: auto-approve.
    """
    graph = _rebuild_task_graph(state.get("task_dag", {}))
    any_failed = any(n.status == "failed" for n in graph.nodes)
    orch_escalation = bool(state.get("orchestrator_escalation"))
    checkpoint_type = 2
    if orch_escalation:
        checkpoint_type = 5
    elif any_failed:
        checkpoint_type = 3

    # Phase 3/4 observability: confirm checkpoint routing in logs.
    try:
        from sage.observability.structured_logger import log_event

        log_event(
            "HUMAN_CHECKPOINT_REACHED",
            payload={
                "mode": state.get("mode", ""),
                "checkpoint_type": checkpoint_type,
                "any_failed": any_failed,
                "orchestrator_escalation": orch_escalation,
            },
        )
    except Exception:
        pass

    if state.get("mode") == "research":
        try:
            import json
            from pathlib import Path

            from rich import box
            from rich.panel import Panel
            from rich.prompt import Prompt
            from rich.table import Table

            from sage.cli.branding import get_console

            c = get_console()
            c.print()
            nodes = state.get("task_dag", {}).get("nodes") or []
            tbl = Table(
                title=f"[accent]Checkpoint {checkpoint_type}[/accent] — review task graph",
                box=box.ROUNDED,
                border_style="#0f766e",
                header_style="accent",
            )
            tbl.add_column("ID", style="brand", no_wrap=True)
            tbl.add_column("Status", style="muted")
            tbl.add_column("Task", style="white")
            for node in nodes:
                tbl.add_row(
                    str(node.get("id", "")),
                    str(node.get("status", "")).upper(),
                    str(node.get("description", ""))[:120],
                )
            plan_note = ""
            try:
                base = Path(state.get("repo_path") or ".")
                plan_path = base / ".sage" / "last_plan.json"
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(
                    json.dumps(state.get("task_dag", {}), indent=2),
                    encoding="utf-8",
                )
                plan_note = f"\n[muted]Snapshot:[/muted] [accent]{plan_path}[/accent]"
            except Exception:
                pass
            c.print(
                Panel(
                    tbl,
                    title="[brand]SAGE[/brand] · human checkpoint",
                    subtitle=plan_note or None,
                    border_style="#0d9488",
                    padding=(0, 1),
                )
            )
            Prompt.ask("Press Enter to continue", default="", show_default=False)
        except Exception:
            print(f"\n[SAGE] HUMAN CHECKPOINT {checkpoint_type} — review required")
            if state.get("task_dag", {}).get("nodes"):
                for node in state["task_dag"].get("nodes", []):
                    print(f"  [{node['status'].upper()}] {node['id']}: {node['description']}")
            try:
                import json
                from pathlib import Path

                base = Path(state.get("repo_path") or ".")
                plan_path = base / ".sage" / "last_plan.json"
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(
                    json.dumps(state.get("task_dag", {}), indent=2),
                    encoding="utf-8",
                )
                print(f"[SAGE] Plan snapshot written: {plan_path}")
            except Exception:
                pass
            input("\n[SAGE] Press Enter to continue...")
    elif state.get("mode") == "auto":
        # Auto mode: do not block and do not spam console output.
        # The checkpoint is still emitted via structured logs/journal.
        if checkpoint_type in (3, 5):
            state["human_checkpoint_done"] = True
    # Clear orchestrator escalation after checkpoint so we don't loop.
    state["orchestrator_escalation"] = False
    return state


def detect_mode(state: SAGEState) -> SAGEState:
    """
    Determine operating mode (greenfield vs existing repo).
    If a repo path is provided, we treat it as an existing repo; otherwise greenfield.
    """
    # Phase 1/3 compliance: always ensure `.sage/` + rules artifacts exist so
    # agents don't fall back to "No project-specific rules defined."
    try:
        from sage.codebase.sage_project_initializer import ensure_sage_project_artifacts
        from sage.scripts.git_hooks import ensure_post_commit_hook, ensure_sage_memory_file

        repo_path = state.get("repo_path") or ""
        ensure_sage_project_artifacts(cwd=repo_path or ".")
        # Phase 1: git hook + `.sage-memory.md` for continuous commit context.
        try:
            base_dir = repo_path or "."
            ensure_post_commit_hook(repo_dir=base_dir)
            ensure_sage_memory_file(repo_dir=base_dir)
        except Exception:
            pass
    except Exception:
        # Never block orchestration on local artifact initialization.
        pass

    repo_path = state.get("repo_path") or ""
    repo_mode = "existing_repo" if repo_path else "greenfield"
    return {**state, "repo_mode": repo_mode}


def codebase_intel(state: SAGEState) -> SAGEState:
    """
    Codebase Intelligence Layer (Phase 3).
    Builds a planner-ready brief and writes `.sage/` caches into the repo.
    """
    repo_path = state.get("repo_path") or ""
    if not repo_path:
        return state

    from sage.codebase.context_builder import build_codebase_brief

    brief = build_codebase_brief(repo_path)
    session_memory = state.get("session_memory", {})
    session_memory["codebase_brief"] = brief
    return {**state, "session_memory": session_memory}


def _rebuild_task_graph(task_dag: dict):
    from sage.orchestrator.task_graph import TaskGraph
    from sage.protocol.schemas import TaskNode

    graph = TaskGraph()
    for n in task_dag.get("nodes", []):
        graph.add_node(
            TaskNode(
                id=n["id"],
                description=n.get("description", ""),
                dependencies=n.get("dependencies", []),
                assigned_agent=n.get("assigned_agent", "coder"),
                status=n.get("status", "pending"),
                retry_count=n.get("retry_count", 0),
                model_used=n.get("model_used", ""),
                strategy_key=n.get("strategy_key", ""),
                verification=n.get("verification", ""),
                task_complexity_score=float(n.get("task_complexity_score", 0.0) or 0.0),
                epistemic_flags=n.get("epistemic_flags", []),
            )
        )
    return graph


def scheduler(state: SAGEState) -> SAGEState:
    """
    Pick the next ready task based on DAG dependencies.
    MVP: runs one task at a time; LangGraph loops until completion.
    """
    graph = _rebuild_task_graph(state.get("task_dag", {}))
    ready = graph.get_ready_tasks()
    if not ready:
        # If nothing is ready but the pipeline isn't done yet, mark remaining
        # pending tasks as BLOCKED so the scheduler can terminate cleanly.
        if not graph.all_done():
            for n in graph.nodes:
                if n.status == "pending":
                    n.status = "blocked"
        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task_id": "",
            "current_task": {},
            "orchestrator_escalation": False,
        }

    task = ready[0]
    task.status = "running"

    insight_feed = state.get("insight_feed")
    orchestrator_escalation = False
    if insight_feed is not None and hasattr(insight_feed, "should_escalate"):
        try:
            orchestrator_escalation = bool(insight_feed.should_escalate(task.id))
        except Exception:
            orchestrator_escalation = False

    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task_id": task.id,
        "current_task": vars(task),
        "orchestrator_escalation": orchestrator_escalation,
    }


def parallel_dispatch(state: SAGEState) -> SAGEState:
    """Identity node used as a fan-out anchor for dynamic parallelism."""
    return state


def scheduler_batch(state: SAGEState) -> SAGEState:
    """
    LangGraph-parallel scheduler batch.

    Select up to MAX_PARALLEL ready tasks, mark them RUNNING in the shared DAG,
    and clear single-task fields. Actual execution happens inside `task_worker`.
    """
    from sage.orchestrator.task_scheduler import MAX_PARALLEL

    graph = _rebuild_task_graph(state.get("task_dag", {}))
    ready = graph.get_ready_tasks()

    if not ready:
        if not graph.all_done():
            for n in graph.nodes:
                # In parallel mode, workers should have finished by the time
                # we re-enter the scheduler. If some tasks are still "running"
                # here, we treat them as blocked to guarantee termination.
                if n.status in ("pending", "running"):
                    n.status = "blocked"
        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task_id": "",
            "current_task": {},
            "orchestrator_escalation": False,
        }

    insight_feed = state.get("insight_feed")
    # Rule-based prioritization: prefer tasks that the intel feed marks as risky.
    if insight_feed is not None and hasattr(insight_feed, "task_risk_rank"):
        try:
            ready = sorted(ready, key=lambda t: insight_feed.task_risk_rank(t.id), reverse=True)
            selected = ready[:MAX_PARALLEL]
        except Exception:
            selected = ready[:MAX_PARALLEL]
    else:
        selected = ready[:MAX_PARALLEL]

    for t in selected:
        t.status = "running"

    orchestrator_escalation = False
    if insight_feed is not None:
        try:
            if hasattr(insight_feed, "should_require_human"):
                for t in selected:
                    if insight_feed.should_require_human(t.id):
                        orchestrator_escalation = True
                        break
            elif hasattr(insight_feed, "should_escalate"):
                for t in selected:
                    if insight_feed.should_escalate(t.id):
                        orchestrator_escalation = True
                        break
        except Exception:
            orchestrator_escalation = False

    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task_id": "",
        "current_task": {},
        "orchestrator_escalation": orchestrator_escalation,
    }


def task_worker(state: SAGEState) -> dict:
    """
    Per-task worker entry point for parallel DAG fan-out.

    Contract:
      - input: state.current_task_id identifies the task to execute
      - output: emits a list of `task_updates` deltas only

    It does not return shared single-task fields (current_task_id, pending_patch_request, etc).
    """
    import copy

    task_id = state.get("current_task_id") or ""
    if not task_id:
        return {"task_updates": []}

    # Isolate mutable per-worker fields; share insight_feed pointer.
    local_state = {**state}
    local_state["task_dag"] = copy.deepcopy(state.get("task_dag", {}))
    local_state["session_memory"] = copy.deepcopy(state.get("session_memory", {}))
    local_state["artifacts_by_task"] = copy.deepcopy(state.get("artifacts_by_task", {}))
    local_state["architect_blueprints_by_task"] = copy.deepcopy(
        state.get("architect_blueprints_by_task", {})
    )

    # Reset single-task tool-contract fields for this worker run.
    local_state["current_task_id"] = task_id
    local_state["current_task"] = {}
    local_state["pending_patch_request"] = {}
    local_state["pending_patch_source"] = ""
    local_state["pending_fix_pattern_context"] = {}
    local_state["verification_passed"] = False
    local_state["verification_needs_tool_apply"] = False
    local_state["execution_result"] = {}
    local_state["last_error"] = ""
    local_state["fix_pattern_hit"] = False
    local_state["fix_pattern_applied"] = False

    did_execute_agent = False
    iteration_count = 0
    # Hard cap to prevent very long LLM-timeout-driven loops from stalling
    # LangGraph orchestration. This is intentionally lower than the legacy
    # retry loop count, because each iteration can include multiple agent
    # calls with timeouts.
    max_iterations = int(local_state.get("max_retries", 3)) * 2 + 4

    # Run the task lifecycle until it reaches a stable end-state.
    while True:
        iteration_count += 1
        if iteration_count > max_iterations:
            # Hard stop: force terminal failure to guarantee graph termination.
            graph_local_hard = _rebuild_task_graph(local_state.get("task_dag", {}))
            task_hard = graph_local_hard.get(task_id)
            if task_hard is not None:
                task_hard.retry_count = int(local_state.get("max_retries", 3))
                task_hard.status = "failed"
                local_state["task_dag"] = graph_local_hard.to_dict()
            local_state["execution_result"] = {
                "status": "error",
                "file": "",
            }
            local_state["last_error"] = "worker iteration cap exceeded"
            break

        graph_local = _rebuild_task_graph(local_state.get("task_dag", {}))
        task_local = graph_local.get(task_id)
        if task_local is None:
            break
        if task_local.status in ("completed", "failed", "blocked"):
            break

        # execute_agent -> tool_executor -> verification/check-fix/debug loop
        if not did_execute_agent:
            local_state.update(execute_agent(local_state))
            local_state.update(tool_executor(local_state))
            did_execute_agent = True

        if (local_state.get("execution_result") or {}).get("status") == "blocked":
            break

        if (local_state.get("execution_result") or {}).get("status") == "ok":
            local_state.update(verification_gate(local_state))
            if local_state.get("verification_needs_tool_apply"):
                local_state.update(tool_executor(local_state))
                local_state.update(verification_gate(local_state))
            if local_state.get("verification_passed"):
                continue

        # If verification failed or tool failed: try patterns, else debug.
        feed = local_state.get("insight_feed")
        force_debug = False
        if feed is not None and hasattr(feed, "should_escalate"):
            try:
                force_debug = bool(feed.should_escalate(task_id))
            except Exception:
                force_debug = False

        if not force_debug:
            local_state.update(check_fix_patterns(local_state))
            if local_state.get("fix_pattern_applied"):
                local_state.update(tool_executor(local_state))
                # Re-verify after applying fix; do NOT re-run execute_agent.
                continue

        # High-risk intervention: skip fix-pattern store and go straight to debugger.
        if force_debug:
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "ORCHESTRATOR_INTERVENTION",
                    payload={
                        "task_id": task_id,
                        "reason": "intel_feed_high_risk_skip_fix_patterns",
                    },
                )
            except Exception:
                pass
        local_state.update(debug_agent(local_state))
        if local_state.get("fix_pattern_applied"):
            local_state.update(tool_executor(local_state))
            # Re-verify after applying fix; do NOT re-run execute_agent.
            continue

        local_state.update(circuit_breaker(local_state))
        break

    graph_local = _rebuild_task_graph(local_state.get("task_dag", {}))
    task_local = graph_local.get(task_id)
    if task_local is None:
        return {"task_updates": []}

    artifact_file = (local_state.get("artifacts_by_task") or {}).get(task_id, "")
    blueprint = (local_state.get("architect_blueprints_by_task") or {}).get(task_id)

    return {
        "task_updates": [
            {
                "task_id": task_id,
                "task_node": vars(task_local),
                "artifact_file": artifact_file,
                "architect_blueprint": blueprint,
                "last_error": local_state.get("last_error", ""),
            }
        ]
    }


def merge_task_updates(state: SAGEState) -> SAGEState:
    """
    Apply per-task deltas emitted by `task_worker` back into the shared DAG.
    """
    graph = _rebuild_task_graph(state.get("task_dag", {}))
    artifacts_by_task = state.get("artifacts_by_task") or {}
    arch_map = state.get("architect_blueprints_by_task") or {}

    updates = state.get("task_updates") or []
    for upd in updates:
        task_id = upd.get("task_id", "")
        if not task_id:
            continue
        task = graph.get(task_id)
        if task is None:
            continue

        old_status = getattr(task, "status", "")
        task_node = upd.get("task_node") or {}
        # Replace task fields from the worker-local snapshot.
        for k, v in task_node.items():
            if hasattr(task, k):
                setattr(task, k, v)

        new_status = getattr(task, "status", "")
        if new_status != old_status:
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "TASK_STATUS_CHANGED",
                    payload={
                        "task_id": task_id,
                        "from_status": old_status,
                        "to_status": new_status,
                    },
                )
            except Exception:
                pass

        artifact_file = upd.get("artifact_file", "") or ""
        if artifact_file:
            artifacts_by_task[task_id] = artifact_file

        blueprint = upd.get("architect_blueprint")
        if blueprint:
            arch_map[task_id] = blueprint

        # Task-scoped errors only: keep the most recent one as a summary.
        if upd.get("last_error"):
            state["last_error"] = str(upd.get("last_error"))

    return {
        **state,
        "task_dag": graph.to_dict(),
        "artifacts_by_task": artifacts_by_task,
        "architect_blueprints_by_task": arch_map,
        # Clear worker accumulator.
        "task_updates": [{"__reset__": True}],
    }


def execute_agent(state: SAGEState) -> SAGEState:
    """
    Spec contract (Phase 2): agents emit PatchRequest; workflow applies it.

    This node only performs agent-role work:
      - `coder`: emits `pending_patch_request`
      - `test_engineer`: emits test `PatchRequest` from dependency artifacts
      - `architect`: marks task completed via blueprint side-effects
      - `reviewer`: produces no patch; verification runs in `verification_gate`
    """
    from pathlib import Path

    from sage.agents.coder import CoderAgent
    from sage.agents.architect import ArchitectAgent
    from sage.agents.test_engineer import TestEngineerAgent

    graph = _rebuild_task_graph(state.get("task_dag", {}))
    task = graph.get(state.get("current_task_id", ""))
    if task is None:
        return state

    # If the task was already marked complete by `execute_agent` (e.g. architect),
    # skip verification gate to avoid requiring an artifact file.
    if task.status == "completed":
        state["verification_passed"] = True
        return state

    attempt = int(task.retry_count)
    coder = CoderAgent()
    architect = ArchitectAgent()
    insight_sink = state.get("insight_feed")

    try:
        from sage.cli.branding import print_run_task_header

        print_run_task_header(task.id, task.description, attempt)
    except Exception:
        print(f"\n[SAGE] Executing: {task.id} — {task.description} (attempt={attempt})")

    # Reset tool contract fields for this node.
    pending_patch_request = {}
    pending_patch_source = ""
    pending_fix_pattern_context = {}

    if task.assigned_agent == "architect":
        universal_prefix = build_prefix_for_agent(state, agent_role="architect", task_id=task.id)
        task_complexity_score = float(getattr(task, "task_complexity_score", 0.0) or 0.0)
        arch_result = architect.run(
            task={
                "id": task.id,
                "description": task.description,
                "task_complexity_score": task_complexity_score,
            },
            memory=state["session_memory"],
            universal_prefix=universal_prefix,
            insight_sink=insight_sink,
        )
        if arch_result.get("status") == "completed":
            blueprint = arch_result.get("blueprint") or {}
            if blueprint:
                arch_map = state.get("architect_blueprints_by_task") or {}
                arch_map[task.id] = blueprint
                state["architect_blueprints_by_task"] = arch_map
            task.status = "completed"
            task.retry_count = attempt
            return {
                **state,
                "task_dag": graph.to_dict(),
                "current_task": vars(task),
                "execution_result": {"status": "ok", "file": ""},
                "last_error": "",
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "pending_patch_request": pending_patch_request,
                "pending_patch_source": pending_patch_source,
                "pending_fix_pattern_context": pending_fix_pattern_context,
            }

        error = arch_result.get("error") or "architect failed"
        task.status = "failed"
        state["last_error"] = str(error)
        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task": vars(task),
            "execution_result": {"status": "error", "file": ""},
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
            "pending_patch_request": pending_patch_request,
            "pending_patch_source": pending_patch_source,
            "pending_fix_pattern_context": pending_fix_pattern_context,
        }

    if task.assigned_agent == "coder":
        universal_prefix = build_prefix_for_agent(state, agent_role="coder", task_id=task.id)
        task_complexity_score = float(getattr(task, "task_complexity_score", 0.0) or 0.0)
        # Inject only this task's architect blueprint into coder memory.
        memory = dict(state.get("session_memory") or {})
        memory["architect_blueprint"] = (state.get("architect_blueprints_by_task") or {}).get(
            task.id, {}
        )
        coder_result = coder.run(
            task={
                "id": task.id,
                "description": task.description,
                "task_complexity_score": task_complexity_score,
            },
            memory=memory,
            mode=state.get("mode", "auto"),
            failure_count=attempt,
            universal_prefix=universal_prefix,
            insight_sink=insight_sink,
        )

        if coder_result.get("status") != "patch_ready":
            error = coder_result.get("error") or coder_result.get("reason") or "coder failed"
            task.status = "failed"
            state["last_error"] = str(error)
            return {
                **state,
                "task_dag": graph.to_dict(),
                "current_task": vars(task),
                "execution_result": {"status": "error", "file": coder_result.get("file", "")},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "pending_patch_request": pending_patch_request,
                "pending_patch_source": pending_patch_source,
                "pending_fix_pattern_context": pending_fix_pattern_context,
            }

        pending_patch_request = coder_result.get("patch_request") or {}
        pending_patch_source = "coder"
        task.model_used = coder_result.get("model_used", "") or ""
        task.strategy_key = coder_result.get("strategy_key", "") or ""
        task.status = "running"

        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task": vars(task),
            "execution_result": {"status": "ok", "file": coder_result.get("file", "")},
            "last_error": "",
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
            "pending_patch_request": pending_patch_request,
            "pending_patch_source": pending_patch_source,
            "pending_fix_pattern_context": pending_fix_pattern_context,
        }

    if task.assigned_agent == "test_engineer":
        artifacts = state.get("artifacts_by_task") or {}
        source_file = ""
        for dep_id in task.dependencies:
            cand = (artifacts.get(dep_id) or "").strip()
            if cand.endswith(".py"):
                name_l = Path(cand).name.lower()
                if name_l.startswith("test_") or name_l.endswith("_test.py"):
                    continue
                source_file = cand
                break
        if not source_file:
            for dep_id in task.dependencies:
                cand = (artifacts.get(dep_id) or "").strip()
                if cand.endswith(".py"):
                    source_file = cand
                    break
        if not source_file:
            for _tid, path in artifacts.items():
                p = (path or "").strip()
                if p.endswith(".py") and "test_" not in Path(p).name.lower():
                    source_file = p
                    break
        if not source_file:
            task.status = "failed"
            state["last_error"] = (
                f"test_engineer task {task.id}: no Python artifact from dependencies "
                f"{task.dependencies!r} — run coder tasks first."
            )
            return {
                **state,
                "task_dag": graph.to_dict(),
                "current_task": vars(task),
                "execution_result": {"status": "error", "file": ""},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "pending_patch_request": pending_patch_request,
                "pending_patch_source": pending_patch_source,
                "pending_fix_pattern_context": pending_fix_pattern_context,
            }

        te_prefix = build_prefix_for_agent(state, agent_role="test_engineer", task_id=task.id)
        te_result = TestEngineerAgent().run(
            source_file=source_file,
            task={
                "id": task.id,
                "description": task.description,
                "task_complexity_score": float(
                    getattr(task, "task_complexity_score", 0.0) or 0.0
                ),
            },
            memory=state["session_memory"],
            failure_count=attempt,
            universal_prefix=te_prefix,
            insight_sink=insight_sink,
        )
        if te_result.get("status") == "skipped":
            task.status = "failed"
            state["last_error"] = te_result.get("test_file") or "test_engineer skipped (source missing or non-Python)"
            return {
                **state,
                "task_dag": graph.to_dict(),
                "current_task": vars(task),
                "execution_result": {"status": "error", "file": ""},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "pending_patch_request": pending_patch_request,
                "pending_patch_source": pending_patch_source,
                "pending_fix_pattern_context": pending_fix_pattern_context,
            }

        if te_result.get("status") != "patch_ready":
            err = te_result.get("error") or te_result.get("reason") or "test_engineer failed"
            task.status = "failed"
            state["last_error"] = str(err)
            return {
                **state,
                "task_dag": graph.to_dict(),
                "current_task": vars(task),
                "execution_result": {"status": "error", "file": te_result.get("test_file", "")},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "pending_patch_request": pending_patch_request,
                "pending_patch_source": pending_patch_source,
                "pending_fix_pattern_context": pending_fix_pattern_context,
            }

        pending_patch_request = te_result.get("patch_request") or {}
        pending_patch_source = "test_engineer"
        task.status = "running"
        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task": vars(task),
            "execution_result": {"status": "ok", "file": source_file},
            "last_error": "",
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
            "pending_patch_request": pending_patch_request,
            "pending_patch_source": pending_patch_source,
            "pending_fix_pattern_context": pending_fix_pattern_context,
        }

    # Reviewer tasks are no-op at this stage; `verification_gate` handles them.
    if task.assigned_agent == "reviewer":
        task.status = "running"
        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task": vars(task),
            "execution_result": {
                "status": "ok",
                "file": (state.get("artifacts_by_task") or {}).get(task.id, ""),
            },
            "last_error": "",
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
            "pending_patch_request": pending_patch_request,
            "pending_patch_source": pending_patch_source,
            "pending_fix_pattern_context": pending_fix_pattern_context,
        }

    # Unknown agent role
    task.status = "failed"
    state["last_error"] = f"Unknown agent role: {task.assigned_agent}"
    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task": vars(task),
        "execution_result": {"status": "error", "file": ""},
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "pending_patch_request": pending_patch_request,
        "pending_patch_source": pending_patch_source,
        "pending_fix_pattern_context": pending_fix_pattern_context,
    }


def tool_executor(state: SAGEState) -> SAGEState:
    """
    Tool execution node.
    Spec contract (Phase 2): the workflow applies `pending_patch_request` only.
    """
    from sage.execution.exceptions import SafetyViolation
    from sage.execution.executor import ToolExecutionEngine
    from sage.protocol.schemas import PatchRequest
    from sage.memory.manager import MemoryManager

    graph = _rebuild_task_graph(state.get("task_dag", {}))
    task = graph.get(state.get("current_task_id", ""))
    if task is None:
        return state

    pending = state.get("pending_patch_request") or {}
    pending_context = state.get("pending_fix_pattern_context") or {}
    pending_source = state.get("pending_patch_source") or ""

    artifacts_by_task = state.get("artifacts_by_task") or {}

    # If no patch was emitted, tool_executor becomes a controlled no-op.
    if not pending:
        artifact_file = artifacts_by_task.get(task.id, "")
        existing = state.get("execution_result") or {}
        if (existing or {}).get("status") == "error":
            return state
        return {**state, "execution_result": {"status": "ok", "file": artifact_file}}

    try:
        patch_req = PatchRequest(**pending)
    except Exception as e:
        return {
            **state,
            "execution_result": {
                "status": "error",
                "file": pending.get("file", ""),
                "error": str(e),
            },
            "last_error": str(e),
        }

    # Human Checkpoint 4 — Pre-deploy.
    # Before destructive operations in research mode.
    if state.get("mode") == "research" and getattr(patch_req, "operation", "") in {
        "delete",
        "run_command",
    }:
        from sage.observability.structured_logger import log_event

        log_event(
            "HUMAN_CHECKPOINT_REACHED",
            payload={
                "mode": state.get("mode", ""),
                "checkpoint_type": 4,
                "operation": patch_req.operation,
                "file": patch_req.file,
            },
        )
        ok = safe_human_confirm(
            f"[SAGE] HUMAN CHECKPOINT 4 (pre-deploy): confirm destructive operation '{patch_req.operation}' on '{patch_req.file}'?",
            default_yes=True,
        )
        if not ok:
            raise HumanCancelledError(
                "Human cancelled checkpoint 4 (pre-deploy destructive operation)."
            )

    engine = ToolExecutionEngine()
    try:
        result = engine.execute(patch_req)
    except SafetyViolation as e:
        try:
            from sage.observability.structured_logger import log_event

            log_event(
                "TOOL_EXECUTION_FAILED",
                payload={
                    "task_id": getattr(task, "id", ""),
                    "operation": patch_req.operation,
                    "file": patch_req.file,
                    "error": f"SafetyViolation: {e}",
                },
            )
        except Exception:
            pass
        return {
            **state,
            "execution_result": {
                "status": "error",
                "file": patch_req.file,
                "error": f"SafetyViolation: {e}",
            },
            "last_error": str(e),
        }
    except Exception as e:
        try:
            from sage.observability.structured_logger import log_event

            log_event(
                "TOOL_EXECUTION_FAILED",
                payload={
                    "task_id": getattr(task, "id", ""),
                    "operation": patch_req.operation,
                    "file": patch_req.file,
                    "error": str(e),
                },
            )
        except Exception:
            pass
        return {
            **state,
            "execution_result": {"status": "error", "file": patch_req.file, "error": str(e)},
            "last_error": str(e),
        }

    # Phase 3 observability: record every tool call and bounded outputs.
    try:
        from sage.observability.structured_logger import log_event

        stdout_preview = (result.get("stdout") or "")[:1000] if isinstance(result, dict) else ""
        stderr_preview = (result.get("stderr") or "")[:1000] if isinstance(result, dict) else ""
        tool_returncode = result.get("returncode") if isinstance(result, dict) else None

        log_event(
            "TOOL_EXECUTED",
            payload={
                "task_id": getattr(task, "id", ""),
                "operation": patch_req.operation,
                "file": patch_req.file,
                "tool_status": result.get("status") if isinstance(result, dict) else "",
                "returncode": tool_returncode,
                "stdout_preview": stdout_preview,
                "stderr_preview": stderr_preview,
                "reason": result.get("reason") if isinstance(result, dict) else "",
            },
        )
    except Exception:
        pass

    if result.get("status") == "blocked":
        # File write conflicts under parallel scheduling: mark the task as blocked
        # so it can be rescheduled later (dependencies will be re-evaluated).
        task.status = "blocked"
        return {
            **state,
            "task_dag": graph.to_dict(),
            "execution_result": {**result, "file": patch_req.file},
            "pending_patch_request": {},
            "pending_patch_source": "",
            "pending_fix_pattern_context": {},
            "last_error": str(result.get("reason") or "file lock busy"),
            "verification_needs_tool_apply": False,
        }

    if result.get("status") == "ok":
        # For tool-first TDD patches, keep the "source artifact" stable.
        if pending_source != "test_engineer":
            artifacts_by_task[task.id] = patch_req.file
        # Persist fix-pattern only after a successful tool apply.
        if pending_context:
            MemoryManager().save_fix_pattern(pending_context)
            # Phase 4 metrics: record fix pattern application.
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "FIX_PATTERN_APPLIED",
                    payload={
                        "task_id": task.id,
                        "error_signature": pending_context.get("error_signature", ""),
                        "fix_file": patch_req.file,
                        "fix_operation": pending_context.get("fix_operation", ""),
                        "success_rate": pending_context.get("success_rate", 1.0),
                    },
                )
                # Spec contract: when we successfully store/learn a fix pattern,
                # emit PATTERN_LEARNED for the learning curve.
                log_event(
                    "PATTERN_LEARNED",
                    payload={
                        "task_id": task.id,
                        "error_signature": pending_context.get("error_signature", ""),
                        "fix_file": patch_req.file,
                        "fix_operation": pending_context.get("fix_operation", ""),
                        "success_rate": pending_context.get("success_rate", 1.0),
                        "times_applied": pending_context.get("times_applied", 1),
                        "source": pending_context.get("source", "unknown"),
                    },
                )
            except Exception:
                pass

    # Clear pending patch fields after applying attempt.
    return {
        **state,
        "task_dag": graph.to_dict(),
        "artifacts_by_task": artifacts_by_task,
        "execution_result": {**result, "file": patch_req.file},
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "verification_needs_tool_apply": False,
    }


def verification_gate(state: SAGEState) -> SAGEState:
    """
    Review/tests/verification gate after `tool_executor`.

    On success: mark task completed.
    On failure: set `last_error` and leave task for fix-pattern/debug loop.
    """
    from sage.agents.reviewer import ReviewerAgent
    from sage.agents.test_engineer import TestEngineerAgent
    from sage.execution.verifier import VerificationEngine
    from sage.observability.trajectory_logger import record_quality_delta, record_trajectory_step
    from sage.orchestrator.model_router import ModelRouter
    from sage.rl.ucb_bandit import get_global_bandit

    graph = _rebuild_task_graph(state.get("task_dag", {}))
    task = graph.get(state.get("current_task_id", ""))
    if task is None:
        return state

    # Prefer the "source artifact" (set by coder/fix patterns) even if the
    # most recent tool execution was a test file patch.
    artifact_file = (state.get("artifacts_by_task") or {}).get(task.id, "") or (
        state.get("execution_result") or {}
    ).get("file", "")
    artifact_file = artifact_file or ""

    # Default to failure until proven otherwise.
    state["verification_passed"] = False
    state["verification_needs_tool_apply"] = False

    if not artifact_file:
        # Nothing to verify.
        state["last_error"] = "No artifact file available for verification."
        return {
            **state,
            "task_dag": graph.to_dict(),
            "execution_result": {"status": "error", "file": ""},
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
        }

    # Reviewer gate (static + optional LLM).
    reviewer_prefix = build_prefix_for_agent(state, agent_role="reviewer", task_id=task.id)
    task_complexity_score = float(getattr(task, "task_complexity_score", 0.0) or 0.0)
    review = ReviewerAgent().run(
        file=artifact_file,
        task={
            "id": task.id,
            "description": task.description,
            "task_complexity_score": task_complexity_score,
        },
        memory=state["session_memory"],
        failure_count=int(task.retry_count),
        universal_prefix=reviewer_prefix,
        insight_sink=state.get("insight_feed"),
    )
    if not review.passed:
        error = (
            f"Review FAILED (score={review.score:.2f}): "
            f"{'; '.join(review.issues)}. "
            f"Suggestion: {review.suggestion}"
        )
        record_quality_delta(
            task_id=task.id,
            agent="reviewer",
            current_score=review.score,
            passed=False,
            model_used=getattr(review, "model_used", "") or "",
            issues=review.issues,
            extra={"verdict": "FAIL"},
        )
        # Phase 4+ trajectory logging: capture reviewer gate outcome.
        record_trajectory_step(
            task_id=task.id,
            agent="reviewer",
            action_model=getattr(task, "model_used", "") or getattr(review, "model_used", "") or "",
            action_strategy_key=getattr(task, "strategy_key", "") or "",
            reward=float(review.score),
            terminal=False,
            state={
                "verification_passed": False,
                "task_complexity_score": task_complexity_score,
                "primary_failure_count": int(task.retry_count),
            },
            extra={"verdict": "FAIL"},
        )
        if task.assigned_agent == "coder":
            # Tier 1 RL: reward-update the discrete coder strategy actually selected.
            strategy_key = getattr(task, "strategy_key", "") or ""
            if not strategy_key and task.model_used:
                mr = ModelRouter()
                primary_model, fallback_model = mr.get_primary_fallback("coder")
                if task.model_used == primary_model:
                    strategy_key = "coder:primary"
                elif task.model_used == fallback_model:
                    strategy_key = "coder:fallback"
            if strategy_key:
                get_global_bandit().update(strategy_key=strategy_key, reward=float(review.score))
        state["last_error"] = error
        return {
            **state,
            "task_dag": graph.to_dict(),
            "execution_result": {"status": "error", "file": artifact_file},
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
        }

    # Ensure tests exist; if not, emit a PatchRequest and route through tool_executor.
    from pathlib import Path

    emit_guard = dict(state.get("_test_emit_guard") or {})
    _emits = int(emit_guard.get(task.id, 0))
    test_file = str(Path("tests") / f"test_{Path(artifact_file).stem}.py")
    test_path = Path(test_file)
    if not test_path.exists() or not test_path.read_text(errors="ignore").strip():
        if _emits >= 4:
            state["last_error"] = (
                "Stopped after repeated test-generation attempts. "
                "Inspect tests/ paths (avoid nested tests/tests/) and src layout."
            )
            return {
                **state,
                "task_dag": graph.to_dict(),
                "execution_result": {"status": "error", "file": artifact_file},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "verification_passed": False,
                "verification_needs_tool_apply": False,
                "_test_emit_guard": emit_guard,
            }
        emit_guard[task.id] = _emits + 1
        state["_test_emit_guard"] = emit_guard

        test_prefix = build_prefix_for_agent(state, agent_role="test_engineer", task_id=task.id)
        test_result = TestEngineerAgent().run(
            source_file=artifact_file,
            task={
                "id": task.id,
                "description": task.description,
                "task_complexity_score": task_complexity_score,
            },
            memory=state["session_memory"],
            failure_count=int(task.retry_count),
            universal_prefix=test_prefix,
            insight_sink=state.get("insight_feed"),
        )

        if test_result.get("status") != "patch_ready" or not test_result.get("patch_request"):
            state["last_error"] = "TestEngineerAgent failed to generate patch_request."
            return {
                **state,
                "task_dag": graph.to_dict(),
                "execution_result": {"status": "error", "file": artifact_file},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
                "verification_passed": False,
                "verification_needs_tool_apply": False,
            }

        state["pending_patch_request"] = test_result["patch_request"]
        state["pending_patch_source"] = "test_engineer"
        state["pending_fix_pattern_context"] = {}
        state["verification_passed"] = False
        state["verification_needs_tool_apply"] = True
        state["last_error"] = ""
        return {
            **state,
            "task_dag": graph.to_dict(),
            "execution_result": {"status": "ok", "file": artifact_file},
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
        }

    # Run verification command from the TaskNode.
    verify_cmd = task.verification
    if verify_cmd:
        verify_result = VerificationEngine().run(verify_cmd)
        if not verify_result["passed"]:
            stderr = verify_result.get("stderr", "") or verify_result.get("stdout", "")
            error = f"Verification failed (rc={verify_result['returncode']}): {stderr[:500]}"
            feed = state.get("insight_feed")
            if feed is not None:
                feed.ingest(
                    AgentInsight(
                        agent="verifier",
                        task_id=task.id,
                        insight_type="risk",
                        content=error[:2000],
                        severity="high",
                        requires_orchestrator_action=True,
                    )
                )
            state["last_error"] = error
            return {
                **state,
                "task_dag": graph.to_dict(),
                "execution_result": {"status": "error", "file": artifact_file},
                "fix_pattern_hit": False,
                "fix_pattern_applied": False,
            }

    # All gates passed.
    record_quality_delta(
        task_id=task.id,
        agent="reviewer",
        current_score=review.score,
        passed=True,
        model_used=getattr(review, "model_used", "") or "",
        issues=review.issues,
        extra={"verdict": "PASS"},
    )
    if task.assigned_agent == "coder":
        strategy_key = getattr(task, "strategy_key", "") or ""
        if not strategy_key and task.model_used:
            mr = ModelRouter()
            primary_model, fallback_model = mr.get_primary_fallback("coder")
            if task.model_used == primary_model:
                strategy_key = "coder:primary"
            elif task.model_used == fallback_model:
                strategy_key = "coder:fallback"
        if strategy_key:
            get_global_bandit().update(strategy_key=strategy_key, reward=float(review.score))

    # All gates passed.
    task.status = "completed"
    task.retry_count = int(task.retry_count)

    # Phase 4+ trajectory logging: final gate success.
    record_trajectory_step(
        task_id=task.id,
        agent="reviewer",
        action_model=getattr(task, "model_used", "") or getattr(review, "model_used", "") or "",
        action_strategy_key=getattr(task, "strategy_key", "") or "",
        reward=float(review.score),
        terminal=True,
        state={
            "verification_passed": True,
            "task_complexity_score": task_complexity_score,
            "primary_failure_count": int(task.retry_count),
        },
        extra={"verdict": "PASS"},
    )

    completed_count = sum(1 for n in graph.nodes if n.status == "completed")
    EVENT_BUS.emit_sync(
        Event(
            type="TASK_COMPLETED",
            task_id=task.id,
            payload={"completed_count": completed_count},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task": vars(task),
        "execution_result": {"status": "ok", "file": artifact_file},
        "last_error": "",
        "verification_passed": True,
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
    }


def check_fix_patterns(state: SAGEState) -> SAGEState:
    """
    Check fix-pattern store for known fixes.

    Contract: do NOT execute patches here. If a pattern match is found, set
    `pending_patch_request` for the workflow's `tool_executor`.
    """
    import hashlib

    from sage.memory.manager import MemoryManager

    graph = _rebuild_task_graph(state.get("task_dag", {}))
    task = graph.get(state.get("current_task_id", ""))
    if task is None:
        return state

    error_text = state.get("last_error", "") or (state.get("execution_result") or {}).get(
        "error", ""
    )
    error_text = error_text[:5000]  # cap to keep signature stable-ish but bounded
    error_signature = hashlib.sha256(error_text[:200].encode()).hexdigest()[:16]

    mm = MemoryManager()
    pattern = mm.find_fix_pattern(error_signature)
    if not pattern:
        # Phase 2/4 metrics: record that we missed the fix-pattern store.
        try:
            from sage.observability.structured_logger import log_event

            log_event(
                "FIX_PATTERN_MISS",
                payload={
                    "task_id": task.id,
                    "error_signature": error_signature,
                    "fix_file": "",
                    "fix_operation": "",
                    "reason": "no_pattern_match",
                },
            )
        except Exception:
            pass

        return {**state, "fix_pattern_hit": False, "fix_pattern_applied": False}

    # If not normalized yet, we can't reconstruct a usable PatchRequest.
    if not pattern.get("fix_patch"):
        # Phase 2/4 metrics: record that we found a candidate but it
        # could not be used to generate an actionable patch.
        try:
            from sage.observability.structured_logger import log_event

            fix_op_raw = str(pattern.get("fix_operation", "") or "")
            fix_op = fix_op_raw.split("|")[0].strip().lower() if fix_op_raw else ""
            log_event(
                "FIX_PATTERN_MISS",
                payload={
                    "task_id": task.id,
                    "error_signature": error_signature,
                    "fix_file": str(pattern.get("fix_file", "") or ""),
                    "fix_operation": fix_op,
                    "reason": "pattern_missing_fix_patch",
                },
            )
        except Exception:
            pass

        return {**state, "fix_pattern_hit": True, "fix_pattern_applied": False}

    pending_patch_request = {
        "file": str(pattern.get("fix_file", "")),
        "operation": str(pattern.get("fix_operation", "edit")).split("|")[0].strip().lower(),
        "patch": str(pattern.get("fix_patch", "")),
        "reason": "Applied known fix pattern (short-circuit)",
        "epistemic_flags": [],
    }

    pending_fix_pattern_context = {
        "error_signature": error_signature,
        "suspected_cause": pattern.get("suspected_cause", ""),
        "fix_operation": pending_patch_request["operation"],
        "fix_file": pending_patch_request["file"],
        "fix_patch": pending_patch_request["patch"],
        "success_rate": 1.0,
        "times_applied": 1,
        "last_used": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "check_fix_patterns",
    }

    # Phase 4 metrics: record that we hit the fix pattern store.
    try:
        from sage.observability.structured_logger import log_event

        log_event(
            "FIX_PATTERN_HIT",
            payload={
                "task_id": task.id,
                "error_signature": error_signature,
                "fix_file": pending_patch_request.get("file", ""),
                "fix_operation": pending_patch_request.get("operation", ""),
            },
        )
    except Exception:
        pass

    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task": vars(task),
        "fix_pattern_hit": True,
        "fix_pattern_applied": True,
        "pending_patch_request": pending_patch_request,
        "pending_patch_source": "fix_pattern",
        "pending_fix_pattern_context": pending_fix_pattern_context,
        "last_error": "",
        "execution_result": {},
    }


def debug_agent(state: SAGEState) -> SAGEState:
    """
    Run the DebuggerAgent to generate a targeted fix patch.

    Contract: do NOT execute the patch here. Instead, set
    `pending_patch_request` so `tool_executor` applies it safely.
    """
    from sage.agents.debugger import DebuggerAgent

    graph = _rebuild_task_graph(state.get("task_dag", {}))
    task = graph.get(state.get("current_task_id", ""))
    if task is None:
        return state

    max_retries = int(state.get("max_retries", 3))
    last_error = state.get("last_error", "") or ""
    file_hint = (state.get("execution_result") or {}).get("file", "") or ""

    next_retry = int(task.retry_count) + 1
    if next_retry > max_retries:
        task.status = "failed"
        graph_snapshot = graph.to_dict()
        return {
            **state,
            "task_dag": graph_snapshot,
            "fix_pattern_applied": False,
            "execution_result": {"status": "error"},
            "pending_patch_request": {},
        }

    debugger = DebuggerAgent()
    insight_sink = state.get("insight_feed")
    debugger_prefix = build_prefix_for_agent(state, agent_role="debugger", task_id=task.id)
    debug_result = debugger.run(
        task={
            "id": task.id,
            "description": task.description,
            "task_complexity_score": float(getattr(task, "task_complexity_score", 0.0) or 0.0),
        },
        error=last_error,
        failed_file=file_hint,
        memory=state["session_memory"],
        failure_count=next_retry,
        universal_prefix=debugger_prefix,
        insight_sink=insight_sink,
    )

    # Trajectory observability: log each debug-loop iteration with patch preview.
    try:
        from sage.observability.trajectory_logger import record_trajectory_step

        patch_preview = ""
        if debug_result.get("status") == "patch_ready":
            pr = debug_result.get("patch_request") or {}
            patch_preview = str(pr.get("patch", "") or "")[:500]

        record_trajectory_step(
            task_id=task.id,
            agent="debugger",
            action_model=getattr(task, "model_used", "") or "",
            action_strategy_key=getattr(task, "strategy_key", "") or "",
            reward=0.0,
            terminal=False,
            state={
                "debug_retry": next_retry,
                "debug_status": debug_result.get("status", ""),
                "task_complexity_score": float(getattr(task, "task_complexity_score", 0.0) or 0.0),
                "primary_failure_count": int(task.retry_count),
            },
            extra={"patch_preview": patch_preview},
        )
    except Exception:
        pass

    task.retry_count = next_retry

    if debug_result.get("status") == "patch_ready" and debug_result.get("patch_request"):
        pending_patch_request = debug_result["patch_request"]

        pending_fix_pattern_context = {
            "error_signature": debug_result.get("error_signature", ""),
            "suspected_cause": debug_result.get("suspected_cause", ""),
            "fix_operation": pending_patch_request.get("operation", "edit"),
            "fix_file": pending_patch_request.get("file", ""),
            "fix_patch": pending_patch_request.get("patch", ""),
            "success_rate": 1.0,
            "times_applied": 1,
            "last_used": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": "debugger",
        }

        task.status = "running"
        return {
            **state,
            "task_dag": graph.to_dict(),
            "current_task": vars(task),
            "pending_patch_request": pending_patch_request,
            "pending_patch_source": "debugger",
            "pending_fix_pattern_context": pending_fix_pattern_context,
            "fix_pattern_hit": False,
            "fix_pattern_applied": True,
            "last_error": "",
            "execution_result": {},
        }

    # Debugger failed to generate a patch.
    task.status = "failed" if next_retry >= max_retries else "pending"
    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task": vars(task),
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "last_error": str(debug_result.get("error") or "debugger failed"),
        "execution_result": {"status": "error", "file": file_hint},
    }


def circuit_breaker(state: SAGEState) -> SAGEState:
    """
    Enforce retry limits and block dependent tasks.
    """
    graph = _rebuild_task_graph(state.get("task_dag", {}))
    task = graph.get(state.get("current_task_id", ""))
    if task is None:
        return state

    max_retries = int(state.get("max_retries", 3))
    last_error = str(state.get("last_error", "") or "")
    # If the underlying LLM call itself is timing out, retrying is typically
    # unrecoverable and only stalls orchestration.
    if "timeout" in last_error.lower() and (
        "ollama" in last_error.lower() or "OllamaTimeout".lower() in last_error.lower()
    ):
        task.status = "failed"
        from sage.observability.trajectory_logger import record_trajectory_step
        from sage.observability.structured_logger import log_event

        log_event(
            "CIRCUIT_BREAKER_ACTIVATED",
            payload={
                "task_id": task.id,
                "reason": "ollama_timeout",
                "retry_count": int(task.retry_count),
                "max_retries": max_retries,
                "error_preview": last_error[:2000],
            },
        )
        record_trajectory_step(
            task_id=task.id,
            agent="orchestrator",
            action_model=getattr(task, "model_used", "") or "",
            action_strategy_key=getattr(task, "strategy_key", "") or "",
            reward=0.0,
            terminal=True,
            state={"failed_reason": "timeout"},
            extra={"error": last_error[:2000]},
        )
    elif int(task.retry_count) < max_retries:
        return state
    else:
        task.status = "failed"
        from sage.observability.structured_logger import log_event
        from sage.observability.trajectory_logger import record_trajectory_step

        log_event(
            "CIRCUIT_BREAKER_ACTIVATED",
            payload={
                "task_id": task.id,
                "reason": "retry_limit",
                "retry_count": int(task.retry_count),
                "max_retries": max_retries,
                "error_preview": last_error[:2000],
            },
        )
        record_trajectory_step(
            task_id=task.id,
            agent="orchestrator",
            action_model=getattr(task, "model_used", "") or "",
            action_strategy_key=getattr(task, "strategy_key", "") or "",
            reward=0.0,
            terminal=True,
            state={"failed_reason": "retry_limit"},
            extra={"error": last_error[:2000]},
        )

    for n in graph.nodes:
        if task.id in n.dependencies and n.status == "pending":
            n.status = "blocked"

    return {
        **state,
        "task_dag": graph.to_dict(),
        "current_task": vars(task),
        "execution_result": {"status": "error"},
        "last_error": "",
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "verification_passed": False,
    }


def save_memory(state: SAGEState) -> SAGEState:
    """
    SessionEnd hook.
    Writes system_state.json + session journal + clears handoff.
    """
    from sage.memory.manager import MemoryManager
    from sage.orchestrator.session_manager import SessionManager
    from sage.agents.memory_optimizer import MemoryOptimizerAgent
    from datetime import datetime, timezone

    mm = MemoryManager()
    sm = SessionManager()

    completed = [n for n in state["task_dag"].get("nodes", []) if n["status"] == "completed"]
    pending = [n for n in state["task_dag"].get("nodes", []) if n["status"] == "pending"]

    new_state = {
        **state["session_memory"],
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "last_completed_task": completed[-1]["id"] if completed else "",
        "next_unblocked_task": pending[0]["id"] if pending else "",
        "session_count": state["session_memory"].get("session_count", 0) + 1,
    }
    # Strip the summary blob from state JSON — it lives in .sage-memory.md
    new_state.pop("sage_memory_summary", None)

    mm.save_state(new_state)
    mm.append_session_log(
        f"[{new_state['last_updated']}] CHECKPOINT completed={len(completed)} pending={len(pending)}"
    )
    sm.clear_handoff()

    # Run memory optimizer — generates .sage-memory.md + prunes stale patterns
    MemoryOptimizerAgent().run()

    try:
        from sage.cli.branding import print_session_complete_banner

        print_session_complete_banner()
    except Exception:
        print("\n[SAGE] Session complete. Memory saved.")
    return {**state, "session_memory": new_state}


# ── Graph assembly ────────────────────────────────────────────────────────────


def build_workflow():
    """Build and compile the LangGraph workflow (with parallel DAG execution)."""
    if not _HAS_LANGGRAPH:  # pragma: no cover
        raise RuntimeError("langgraph is not installed; parallel workflow unavailable")
    workflow = StateGraph(SAGEState)

    workflow.add_node("load_memory", load_memory)
    workflow.add_node("detect_mode", detect_mode)
    workflow.add_node("codebase_intel", codebase_intel)
    workflow.add_node("prompt_middleware", prompt_middleware)
    workflow.add_node("route_model", route_model)
    workflow.add_node("planner", run_planner)
    workflow.add_node("human_checkpoint", human_checkpoint)

    workflow.add_node("scheduler_batch", scheduler_batch)
    workflow.add_node("parallel_dispatch", parallel_dispatch)
    workflow.add_node("task_worker", task_worker)
    workflow.add_node("merge_task_updates", merge_task_updates)

    workflow.add_node("save_memory", save_memory)

    workflow.set_entry_point("load_memory")
    workflow.add_edge("load_memory", "detect_mode")

    workflow.add_conditional_edges(
        "detect_mode",
        lambda s: (
            "codebase_intel" if s.get("repo_mode") == "existing_repo" else "prompt_middleware"
        ),
        {
            "codebase_intel": "codebase_intel",
            "prompt_middleware": "prompt_middleware",
        },
    )

    workflow.add_node("human_checkpoint_1_post_scan", human_checkpoint_1_post_scan)
    workflow.add_edge("codebase_intel", "human_checkpoint_1_post_scan")
    workflow.add_edge("human_checkpoint_1_post_scan", "prompt_middleware")
    workflow.add_edge("prompt_middleware", "route_model")
    workflow.add_edge("route_model", "planner")
    workflow.add_edge("planner", "human_checkpoint")
    workflow.add_edge("human_checkpoint", "scheduler_batch")

    # If the orchestrator flagged high-risk tasks in research mode, pause again.
    workflow.add_conditional_edges(
        "scheduler_batch",
        lambda s: (
            "human_checkpoint"
            if (
                _rebuild_task_graph(s.get("task_dag", {})).all_done()
                and any(
                    n.status == "failed" for n in _rebuild_task_graph(s.get("task_dag", {})).nodes
                )
                and s.get("mode") in ("research", "auto")
                and not s.get("human_checkpoint_done", False)
            )
            else (
                "save_memory"
                if _rebuild_task_graph(s.get("task_dag", {})).all_done()
                else (
                    "human_checkpoint"
                    if s.get("orchestrator_escalation")
                    and s.get("mode") in ("research", "auto")
                    and not s.get("human_checkpoint_done", False)
                    else "parallel_dispatch"
                )
            )
        ),
        {
            "human_checkpoint": "human_checkpoint",
            "parallel_dispatch": "parallel_dispatch",
            "save_memory": "save_memory",
        },
    )

    # Fan-out: run one `task_worker` per RUNNING task (dynamic parallelism via Send).
    def _fanout_from_parallel_dispatch(s: SAGEState):
        from langgraph.types import Send

        graph = _rebuild_task_graph(s.get("task_dag", {}))
        running = [t for t in graph.nodes if t.status == "running"]
        # No ready/running tasks => no-op (merge will decide what to do next).
        return [Send("task_worker", {**s, "current_task_id": t.id}) for t in running]

    workflow.add_conditional_edges(
        "parallel_dispatch",
        _fanout_from_parallel_dispatch,
    )

    workflow.add_edge("task_worker", "merge_task_updates")

    # Loop until all tasks are in a terminal state.
    def _continue_or_stop(s: SAGEState):
        graph = _rebuild_task_graph(s.get("task_dag", {}))
        if graph.all_done():
            has_failed = any(n.status == "failed" for n in graph.nodes)
            if (
                s.get("mode") in ("research", "auto")
                and has_failed
                and not s.get("human_checkpoint_done", False)
            ):
                return "human_checkpoint"
            return "save_memory"
        return "scheduler_batch"

    workflow.add_conditional_edges(
        "merge_task_updates",
        _continue_or_stop,
        {
            "save_memory": "save_memory",
            "scheduler_batch": "scheduler_batch",
            "human_checkpoint": "human_checkpoint",
        },
    )

    workflow.add_edge("save_memory", END)
    return workflow.compile()


if _HAS_LANGGRAPH:
    app = build_workflow()
else:  # pragma: no cover

    class _RuleBasedParallelApp:
        """
        Fallback executor when `langgraph` isn't installed.

        This keeps SAGE functional while still performing rule-based DAG
        parallelism (batch scheduling + ThreadPool worker fan-out). Tool
        execution remains safe via the in-process file locks.
        """

        def invoke(self, state: SAGEState):
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from sage.orchestrator.task_scheduler import MAX_PARALLEL

            s = dict(state)
            s = load_memory(s)
            s = detect_mode(s)
            if s.get("repo_mode") == "existing_repo":
                s = codebase_intel(s)
            s = prompt_middleware(s)
            s = route_model(s)
            s = run_planner(s)
            s = human_checkpoint(s)

            while True:
                graph = _rebuild_task_graph(s.get("task_dag", {}))
                if graph.all_done():
                    return save_memory(s)

                ready = graph.get_ready_tasks()
                if not ready:
                    # Nothing is ready yet: block remaining pending tasks so we can terminate cleanly.
                    for n in graph.nodes:
                        if n.status == "pending":
                            n.status = "blocked"
                    s["task_dag"] = graph.to_dict()
                    return save_memory(s)

                selected = ready[:MAX_PARALLEL]
                for t in selected:
                    t.status = "running"
                s["task_dag"] = graph.to_dict()

                # Orchestrator high-risk escalation (research mode) before executing a batch.
                if s.get("mode") == "research":
                    feed = s.get("insight_feed")
                    if feed is not None and hasattr(feed, "should_escalate"):
                        for t in selected:
                            if feed.should_escalate(t.id):
                                s = human_checkpoint(s)
                                break

                # Fan-out: run one worker per running task.
                futures = []
                with ThreadPoolExecutor(max_workers=len(selected) or 1) as ex:
                    for t in selected:
                        worker_state = {**s, "current_task_id": t.id}
                        futures.append(ex.submit(task_worker, worker_state))

                    task_updates = []
                    for fut in as_completed(futures):
                        res = fut.result()
                        task_updates.extend(res.get("task_updates") or [])

                s["task_updates"] = task_updates
                s = merge_task_updates(s)

    app = _RuleBasedParallelApp()
