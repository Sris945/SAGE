"""Universal prompt prefix + skill injection (extracted from workflow for clarity)."""

from __future__ import annotations

from pathlib import Path

from sage.execution.tool_policy import format_tool_policy_summary
from sage.memory.rag_retriever import format_patterns_for_prompt
from sage.prompt_engine.rules_manager import load_merged_rules
from sage.prompt_engine.universal_prefix import build_universal_prefix

from sage.orchestrator.state import SAGEState


def allowed_tools_for_role(agent_role: str) -> list[str]:
    """
    Spec-aligned MVP mapping of agent roles → PatchRequest operations.
    The workflow still enforces actual safety at execution time.
    """
    role = (agent_role or "").lower()
    if role in ("coder", "debugger", "test_engineer", "documentation"):
        return ["create", "edit", "delete", "run_command"]
    return []


def build_prefix_for_agent(state: SAGEState, *, agent_role: str, task_id: str | None = None) -> str:
    codebase_brief = (state.get("session_memory") or {}).get("codebase_brief")
    retrieved_patterns = state.get("retrieved_fix_patterns") or []
    patterns_str = format_patterns_for_prompt(retrieved_patterns) if retrieved_patterns else "None"

    insight_feed = state.get("insight_feed")
    orch_notes = ""
    if insight_feed is not None and hasattr(insight_feed, "get_injected_context"):
        orch_notes = insight_feed.get_injected_context(task_id or "", next_agent=agent_role)
    if (
        (agent_role or "").lower() == "reviewer"
        and insight_feed is not None
        and hasattr(insight_feed, "get_reviewer_coder_high_notes")
        and task_id
    ):
        extra = insight_feed.get_reviewer_coder_high_notes(task_id)
        if extra.strip():
            orch_notes = (orch_notes + "\n\n" + extra).strip() if orch_notes else extra

    allowed_tools = allowed_tools_for_role(agent_role)

    try:
        from sage.prompt_engine.skill_injector import get_skill_injection_context

        task_desc = ((state.get("current_task") or {}) or {}).get("description") or state.get(
            "user_prompt", ""
        )
        last_error = state.get("last_error", "") or ""
        skills_block = get_skill_injection_context(
            agent_role=agent_role,
            task_description=task_desc,
            last_error=last_error,
        )
    except Exception:
        skills_block = ""

    user_rules_block = ""
    try:
        repo_root = state.get("repo_path") or ""
        base_dir = Path(repo_root).resolve() if repo_root else Path.cwd()
        user_rules_block = load_merged_rules(agent_role=agent_role, base_dir=base_dir)
    except Exception:
        user_rules_block = ""

    base_prefix = build_universal_prefix(
        agent_role=agent_role,
        codebase_brief_if_existing_repo=codebase_brief,
        orchestrator_injected_context=orch_notes,
        allowed_tools_for_this_task=allowed_tools,
        relevant_fix_patterns_if_applicable=patterns_str,
        user_rules_if_any=user_rules_block,
        workspace_policy_block=format_tool_policy_summary(),
    )
    # Inject intelligence feed notes for this task
    feed = state.get("insight_feed")
    if feed is not None and hasattr(feed, "get_pending_notes"):
        notes = feed.get_pending_notes(task_id or "")
        if notes:
            base_prefix += "\n## ORCHESTRATOR NOTES\n" + "\n".join(f"- {n}" for n in notes)

    # If codebase was semantically indexed, inject relevant symbols for this task
    brief = (state.get("session_memory") or {}).get("codebase_brief", {})
    if brief.get("queryable_codebase") and agent_role in ("coder", "debugger"):
        task_desc = ""
        if task_id:
            dag = state.get("task_dag", {})
            for node in dag.get("nodes", []):
                if node.get("id") == task_id:
                    task_desc = node.get("description", "")
        if task_desc:
            try:
                from sage.codebase.semantic_reader import query_codebase

                hits = query_codebase(task_desc, k=3)
                if hits:
                    sym_lines = [
                        f"  - {h['name']} in {h['file']}:{h.get('line', '')} — {h.get('source_preview', '')[:100]}"
                        for h in hits
                    ]
                    base_prefix += "\n## RELEVANT EXISTING CODE\n" + "\n".join(sym_lines)
            except Exception:
                pass

    if skills_block.strip():
        return base_prefix + "\n\nSKILL DISCIPLINE CONTEXT:\n" + skills_block
    return base_prefix
