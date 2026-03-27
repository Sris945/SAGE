"""``sage permissions`` — show or set workspace + tool policy (``.sage/policy.json``)."""

from __future__ import annotations


def cmd_permissions_show(args) -> None:
    import json

    from sage.execution.executor import ToolExecutionEngine
    from sage.execution.policy_store import (
        effective_skills_root_str,
        policy_file_path,
        skills_root_source,
        tool_policy_source,
        workspace_root_source,
    )
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
    pf = policy_file_path()
    lines.append(f"Policy file: {pf} {'(exists)' if pf.is_file() else '(none — use `sage permissions set …`)'}")
    lines.append("")
    lines.append(f"tool_policy={tool_policy_mode()}  [source: {tool_policy_source()}]")
    lines.append(
        f"workspace roots ({len(roots)}): {', '.join(str(r) for r in roots)}  "
        f"[source: {workspace_root_source()}]"
    )
    es = effective_skills_root_str()
    sk_disp = "(bundled package skills)" if not es else es
    lines.append(f"skills: {sk_disp}  [source: {skills_root_source()}]")
    lines.append("")
    lines.append("Change in this shell: `sage permissions set policy strict|standard`,")
    lines.append("`sage permissions set workspace <path|clear>`, `sage permissions set skills <path|clear>`.")
    lines.append("`sage permissions reset` removes the file and clears these env vars in-process.")
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "workspace_roots": [str(r) for r in roots],
                    "blocked_command_substrings": list(DENY_SUBSTRINGS),
                    "tool_policy": tool_policy_mode(),
                    "tool_policy_source": tool_policy_source(),
                    "workspace_root_source": workspace_root_source(),
                    "skills_root_source": skills_root_source(),
                    "policy_file": str(policy_file_path()),
                    "policy_file_exists": policy_file_path().is_file(),
                },
                indent=2,
            )
        )
        return
    print("[SAGE] Effective permissions")
    print("\n".join(lines))


def cmd_permissions_set(args) -> None:
    import os
    from pathlib import Path

    from sage.execution.policy_store import load_policy_file, save_policy_file

    cmd = getattr(args, "permissions_set_command", None)
    if cmd == "policy":
        value = args.value
        data = load_policy_file()
        data["tool_policy"] = value
        save_policy_file(data)
        os.environ["SAGE_TOOL_POLICY"] = value
        print(f"[SAGE] tool_policy={value!r} — saved {policy_file_path_display()} and applied in this process.")
        return
    if cmd == "workspace":
        raw = (args.value or "").strip()
        data = load_policy_file()
        if raw.lower() == "clear":
            data.pop("workspace_root", None)
            save_policy_file(data)
            os.environ.pop("SAGE_WORKSPACE_ROOT", None)
            print(
                "[SAGE] workspace override cleared — saved "
                f"{policy_file_path_display()} and unset SAGE_WORKSPACE_ROOT in this process."
            )
            return
        data["workspace_root"] = raw
        save_policy_file(data)
        os.environ["SAGE_WORKSPACE_ROOT"] = raw
        print(
            f"[SAGE] workspace_root={raw!r} — saved {policy_file_path_display()} "
            "and applied in this process."
        )
        return
    if cmd == "skills":
        from sage.prompt_engine.skill_injector import clear_skill_text_cache

        raw = (args.value or "").strip()
        data = load_policy_file()
        if raw.lower() == "clear":
            data.pop("skills_root", None)
            save_policy_file(data)
            os.environ.pop("SAGE_SKILLS_ROOT", None)
            clear_skill_text_cache()
            print(
                "[SAGE] skills override cleared — saved "
                f"{policy_file_path_display()} and unset SAGE_SKILLS_ROOT; skill cache cleared."
            )
            return
        p = Path(raw).expanduser()
        try:
            resolved = str(p.resolve())
        except OSError as e:
            print(f"[SAGE] invalid path: {e}")
            return
        if not p.is_dir():
            print(f"[SAGE] warning: skills path is not a directory (yet): {resolved}")
        data["skills_root"] = resolved
        save_policy_file(data)
        os.environ["SAGE_SKILLS_ROOT"] = resolved
        clear_skill_text_cache()
        print(
            f"[SAGE] skills_root={resolved!r} — saved {policy_file_path_display()} "
            "and applied; skill cache cleared."
        )
        return
    print("[SAGE] permissions set: unknown subcommand")


def policy_file_path_display() -> str:
    from sage.execution.policy_store import policy_file_path

    return str(policy_file_path())


def cmd_permissions_reset() -> None:
    import os

    from sage.execution.policy_store import delete_policy_file
    from sage.prompt_engine.skill_injector import clear_skill_text_cache

    deleted = delete_policy_file()
    for key in ("SAGE_TOOL_POLICY", "SAGE_WORKSPACE_ROOT", "SAGE_SKILLS_ROOT"):
        os.environ.pop(key, None)
    clear_skill_text_cache()
    msg = "[SAGE] policy reset — "
    msg += "removed .sage/policy.json" if deleted else "no .sage/policy.json to remove"
    msg += "; cleared SAGE_TOOL_POLICY, SAGE_WORKSPACE_ROOT, SAGE_SKILLS_ROOT in this process; skill cache cleared."
    print(msg)


def cmd_permissions(args) -> None:
    pc = getattr(args, "permissions_command", None)
    if pc == "set":
        cmd_permissions_set(args)
        return
    if pc == "reset":
        cmd_permissions_reset()
        return
    cmd_permissions_show(args)
