"""``sage permissions`` — show effective workspace + tool policy."""


def cmd_permissions(args) -> None:
    import json
    import os

    from sage.execution.executor import ToolExecutionEngine
    from sage.execution.tool_policy import (
        DENY_SUBSTRINGS,
        format_tool_policy_summary,
        tool_policy_mode,
    )
    from sage.execution.workspace_policy import default_workspace_roots

    roots = default_workspace_roots()
    lines = [format_tool_policy_summary()]
    lines.append("")
    lines.append("Blocked command substrings (unified policy, same as executor / verify):")
    for b in ToolExecutionEngine.BLOCKED_COMMANDS:
        lines.append(f"  - {b}")
    lines.append("")
    lines.append(f"SAGE_TOOL_POLICY={tool_policy_mode()}")
    lines.append(f"SAGE_WORKSPACE_ROOT={os.environ.get('SAGE_WORKSPACE_ROOT', '')}")
    lines.append(f"SAGE_SKILLS_ROOT={os.environ.get('SAGE_SKILLS_ROOT', '')}")
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "workspace_roots": [str(r) for r in roots],
                    "blocked_command_substrings": list(DENY_SUBSTRINGS),
                    "tool_policy": tool_policy_mode(),
                },
                indent=2,
            )
        )
        return
    print("[SAGE] Effective permissions")
    print("\n".join(lines))
