"""``sage run`` implementation.

Environment (see also ``docs/TRUST_AND_SCALE.md``):

- ``SAGE_MODEL_PROFILE=test`` — force one small local Ollama model for all roles (laptop / CI).
- ``SAGE_FORCE_LOCAL_MODEL=<tag>`` — same, but set the tag explicitly.
- ``SAGE_TRACE_ID`` — optional correlation id for structured JSON logs.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sage.cli.log_utils import print_routing_summary_for_session
from sage.version import get_version


def _print_run_header(*, mode: str, prompt: str) -> None:
    try:
        from rich.panel import Panel

        from sage.cli.branding import get_console

        c = get_console()
        c.print()
        c.print(
            Panel.fit(
                f"[brand]run[/brand]  [muted]v{get_version()}[/muted]  [accent]{mode}[/accent]\n[muted]{prompt[:500]}{'…' if len(prompt) > 500 else ''}[/muted]",
                border_style="#0d9488",
                title="SAGE",
            )
        )
        c.print()
    except Exception:
        print(f"\n[SAGE] v{get_version()} — starting (mode={mode})")
        print(f"[SAGE] Prompt: {prompt}\n")


def cmd_run(args) -> None:
    from sage.orchestrator.workflow import app

    repo_path = args.repo or ""
    if repo_path:
        os.chdir(repo_path)

    os.environ["SAGE_WORKSPACE_ROOT"] = str(Path.cwd().resolve())

    mode = "auto" if args.auto else ("silent" if args.silent else "research")
    prev_session_id = os.environ.get("SAGE_SESSION_ID")
    new_session_id = uuid.uuid4().hex
    os.environ["SAGE_SESSION_ID"] = new_session_id
    initial_state = {
        "user_prompt": args.prompt,
        "enhanced_prompt": "",
        "task_dag": {},
        "current_task": {},
        "current_task_id": "",
        "agent_output": {},
        "execution_result": {},
        "debug_attempts": 0,
        "session_memory": {},
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "artifacts_by_task": {},
        "architect_blueprints_by_task": {},
        "verification_passed": False,
        "verification_needs_tool_apply": False,
        "orchestrator_escalation": False,
        "task_updates": [],
        "repo_path": repo_path,
        "repo_mode": "greenfield",
        "last_error": "",
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "max_retries": 5,
        "events": [],
        "mode": mode,
        "resume_from_handoff": False,
    }
    _print_run_header(mode=mode, prompt=args.prompt)
    try:
        app.invoke(initial_state)
        if getattr(args, "explain_routing", False):
            print_routing_summary_for_session(new_session_id)
    finally:
        if prev_session_id is None:
            os.environ.pop("SAGE_SESSION_ID", None)
        else:
            os.environ["SAGE_SESSION_ID"] = prev_session_id
