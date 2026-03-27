"""
SAGE Universal Prompt Prefix (MVP)
-----------------------------------
Builds the MD-required sections that should appear in every agent prompt:
  - CODEBASE CONTEXT
  - ORCHESTRATOR NOTES
  - TOOL PERMISSIONS
  - KNOWN PATTERNS

This is intentionally a prefix (not a full universal wrapper replacement) to
avoid invasive template rewrites while still meeting the key contract.
"""

from __future__ import annotations

import json
from typing import Any


def _short_json(obj: Any, max_chars: int = 4000) -> str:
    try:
        s = json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)
    return s if len(s) <= max_chars else s[:max_chars] + "\n...TRUNCATED..."


def build_universal_prefix(
    *,
    agent_role: str,
    codebase_brief_if_existing_repo: dict | None,
    orchestrator_injected_context: str,
    allowed_tools_for_this_task: list[str] | None,
    relevant_fix_patterns_if_applicable: str,
    user_rules_if_any: str | None = None,
    workspace_policy_block: str | None = None,
) -> str:
    codebase_block = (
        _short_json(codebase_brief_if_existing_repo) if codebase_brief_if_existing_repo else "None"
    )
    orch_block = orchestrator_injected_context.strip() or "None"
    allowed_tools = allowed_tools_for_this_task or []
    tool_block = ", ".join(allowed_tools) if allowed_tools else "None"
    patterns_block = relevant_fix_patterns_if_applicable.strip() or "None"
    user_rules_block = (user_rules_if_any or "").strip() or "None"
    workspace_block = (workspace_policy_block or "").strip() or "None"

    # Labels intentionally match the MD universal template.
    return (
        f"CODEBASE CONTEXT:\n{codebase_block}\n\n"
        f"USER RULES:\n{user_rules_block}\n\n"
        f"ORCHESTRATOR NOTES:\n{orch_block}\n\n"
        f"WORKSPACE POLICY:\n{workspace_block}\n\n"
        f"TOOL PERMISSIONS:\n{tool_block}\n\n"
        f"KNOWN PATTERNS:\n{patterns_block}\n"
    )
