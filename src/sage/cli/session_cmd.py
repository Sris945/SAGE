"""``sage session`` — reset / refresh local session bookkeeping."""

from __future__ import annotations

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


def cmd_session_refresh(_args) -> None:
    """Re-print session snapshot from disk (same data as ``sage status``)."""
    from sage.cli.branding import get_console

    get_console().print("  [accent]session refresh[/accent]")
    from sage.cli.main import cmd_status

    cmd_status(_args)
