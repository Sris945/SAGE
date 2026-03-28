"""``sage session`` — reset / refresh / handoff local session bookkeeping."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def cmd_session_reset(_args) -> None:
    """
    Remove ``memory/system_state.json`` and assign a new ``SAGE_SESSION_ID`` for this process.

    Next ``sage run`` still generates its own session id, but tools that read env see the new id.
    """
    from sage.cli.branding import get_console

    c = get_console()
    root = Path.cwd()
    state = root / "memory" / "system_state.json"
    if state.exists():
        try:
            state.unlink()
        except OSError as e:
            c.print(f"  [accent]![/accent]  Could not remove {state}: {e}")
            return

    sid = uuid.uuid4().hex
    os.environ["SAGE_SESSION_ID"] = sid
    c.print()
    c.print("  [accent]session reset[/accent] [muted]— cleared[/muted] memory/system_state.json")
    c.print(f"  [muted]SAGE_SESSION_ID[/muted]=[brand]{sid}[/brand]")
    c.print()


def cmd_session_handoff(args) -> None:
    """Show ``memory/handoff.json`` (interrupt snapshot); ``--clear`` removes it."""
    from sage.cli.branding import get_console

    c = get_console()
    p = Path("memory/handoff.json")
    c.print()
    if not p.is_file():
        c.print("  [muted]No handoff file —[/muted] [accent]memory/handoff.json[/accent] [muted]missing.[/muted]")
        c.print()
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        c.print(f"  [accent]![/accent]  Could not read handoff: {e}")
        c.print()
        return

    snap = raw.get("state_snapshot") or {}
    dag = snap.get("task_dag") or {}
    nodes = dag.get("nodes") if isinstance(dag, dict) else []
    n = len(nodes) if isinstance(nodes, list) else 0
    reason = raw.get("reason") or raw.get("interrupt_reason") or ""
    sid = snap.get("current_task_id") or ""
    c.print("  [accent]session handoff[/accent]")
    c.print(f"  [muted]file[/muted]     {p.resolve()}")
    c.print(f"  [muted]schema[/muted]   {raw.get('schema_version', '?')}")
    if reason:
        c.print(f"  [muted]reason[/muted]   {reason}")
    c.print(f"  [muted]tasks[/muted]     {n} in snapshot DAG")
    if sid:
        c.print(f"  [muted]current[/muted]  {sid}")
    if snap.get("last_error"):
        c.print(f"  [muted]last_err[/muted] {str(snap.get('last_error'))[:200]}")

    if getattr(args, "clear", False):
        try:
            p.unlink()
            c.print("  [brand]cleared[/brand] handoff file.")
        except OSError as e:
            c.print(f"  [accent]![/accent]  Could not delete: {e}")
    else:
        c.print("  [muted]Next[/muted] [accent]sage run[/accent] [muted]applies this snapshot unless you pass[/muted] [accent]--fresh[/accent][muted].[/muted]")
    c.print()


def cmd_session_refresh(_args) -> None:
    """Re-print session snapshot from disk (same data as ``sage status``)."""
    from sage.cli.branding import get_console

    get_console().print("  [accent]session refresh[/accent]")
    from sage.cli.main import cmd_status

    cmd_status(_args)
