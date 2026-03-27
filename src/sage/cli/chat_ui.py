"""
Rich helpers for shell chat transcript and metadata boxes (OpenClaw-style).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

_ASSISTANT_TAG = "reply_to_current"


def chat_timestamp_str() -> str:
    try:
        tz = datetime.now(timezone.utc).astimezone()
        return tz.strftime("%a %Y-%m-%d %H:%M %Z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%a %Y-%m-%d %H:%M UTC")


def print_user_line(*, text: str, use_rich: bool) -> None:
    ts = chat_timestamp_str()
    if use_rich:
        from sage.cli.branding import get_console
        from rich.markup import escape

        get_console().print(f"[muted][{escape(ts)}][/muted] {escape(text)}")
    else:
        print(f"[{ts}] {text}")


def print_assistant_block(*, body: str, tag: str | None = _ASSISTANT_TAG, use_rich: bool) -> None:
    if use_rich:
        from sage.cli.branding import get_console
        from rich.markup import escape

        c = get_console()
        if tag:
            c.print(f"[accent][[{escape(tag)}]][/accent]")
        c.print(escape(body))
    else:
        if tag:
            print(f"[[{tag}]]")
        print(body)


def print_conversation_info_box(
    payload: Mapping[str, Any] | dict[str, Any],
    *,
    title: str = "Conversation info (untrusted metadata):",
    use_rich: bool,
) -> None:
    """JSON in a slightly elevated panel (syntax-highlighted)."""
    if not use_rich:
        print(title)
        print(json.dumps(dict(payload), indent=2))
        return

    from rich import box
    from rich.panel import Panel
    from rich.syntax import Syntax

    from sage.cli.branding import get_console

    text = json.dumps(dict(payload), indent=2)
    syntax = Syntax(text, "json", theme="monokai", word_wrap=True)
    c = get_console()
    c.print()
    c.print(
        Panel(
            syntax,
            title=f"[muted]{title}[/muted]",
            border_style="#4c566a",
            style="on #2e3440",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def new_message_id() -> str:
    return uuid.uuid4().hex[:12]


def print_chat_enter_banner(*, use_rich: bool, session_id: str = "") -> None:
    if use_rich:
        from rich import box
        from rich.panel import Panel

        from sage.cli.branding import get_console

        sid = f" [muted]session[/muted] [accent]{session_id}[/accent]" if session_id else ""
        body = (
            "[white]Chat mode[/white] (Cursor-style thread)"
            f"{sid}[white].[/white] Transcript is saved under [accent].sage/chat_sessions/[/accent] "
            "[muted]and is prepended to the next[/muted] [accent]run[/accent] [muted]or NL build.[/muted]\n"
            "[accent]/back[/accent] [muted]·[/muted] [accent]/agent[/accent] [muted]→ agent mode (build) ·[/muted] "
            "[accent]/exit[/accent] [muted]→ quit ·[/muted] "
            "[accent]/info[/accent] [muted]metadata.[/muted] "
            "[accent]chat resume[/accent] [muted]continues last thread;[/muted] [accent]chat new …[/accent] [muted]fresh thread.[/muted]"
        )
        get_console().print()
        get_console().print(
            Panel(
                body,
                title="[brand]SAGE[/brand] · chat",
                border_style="#0d9488",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        get_console().print()
    else:
        print("[SAGE] Chat mode — session saved to .sage/chat_sessions/; /back or /agent for build; /exit to quit.")
