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
    if skills_block.strip():
        return base_prefix + "\n\nSKILL DISCIPLINE CONTEXT:\n" + skills_block
    return base_prefix
