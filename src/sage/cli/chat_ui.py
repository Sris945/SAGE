"""
Rich helpers for the SAGE chat interface.

Key design points:
  - Responses are streamed and rendered as live Markdown (Rich Live + Markdown).
  - A clean "SAGE ›" header replaces the old [[reply_to_current]] tag.
  - User lines are timestamped, dim, right-aligned conceptually.
  - Falls back to plain print() when Rich is unavailable.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Generator, Mapping


def chat_timestamp_str() -> str:
    try:
        tz = datetime.now(timezone.utc).astimezone()
        return tz.strftime("%H:%M")
    except Exception:
        return datetime.now(timezone.utc).strftime("%H:%M")


def new_message_id() -> str:
    return uuid.uuid4().hex[:12]


# ── User line ─────────────────────────────────────────────────────────────────

def print_user_line(*, text: str, use_rich: bool) -> None:
    ts = chat_timestamp_str()
    if use_rich:
        from rich.markup import escape
        from sage.cli.branding import get_console
        c = get_console()
        c.print(f"\n[bold white]You[/bold white] [dim]{ts}[/dim]")
        c.print(f"  {escape(text)}\n")
    else:
        print(f"\nYou [{ts}]\n  {text}\n")


# ── Assistant block (streaming Markdown) ──────────────────────────────────────

def print_assistant_block(
    *,
    body: str,
    tag: str | None = None,  # ignored — kept for call-site compat
    use_rich: bool,
    model: str = "",
) -> None:
    """Render a fully-buffered assistant response as Markdown."""
    if use_rich:
        _render_markdown_block(body, model=model)
    else:
        label = f"SAGE [{model}]" if model else "SAGE"
        print(f"\n{label}\n{body}\n")


def stream_assistant_block(
    *,
    chunks: Generator[str, None, None],
    use_rich: bool,
    model: str = "",
) -> str:
    """
    Stream tokens from `chunks` and render as live Markdown.
    Returns the full accumulated text.
    """
    if use_rich:
        return _stream_markdown_live(chunks, model=model)
    else:
        label = f"SAGE [{model}]" if model else "SAGE"
        print(f"\n{label}")
        accumulated = ""
        for chunk in chunks:
            print(chunk, end="", flush=True)
            accumulated += chunk
        print("\n")
        return accumulated


def _render_markdown_block(text: str, *, model: str = "") -> None:
    """Print a single Markdown-rendered block with an assistant header."""
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich import box
    from sage.cli.branding import get_console
    c = get_console()
    _print_assistant_header(c, model=model)
    c.print(Markdown(text, code_theme="monokai"))
    c.print()


def _stream_markdown_live(chunks: Generator[str, None, None], *, model: str = "") -> str:
    """Stream token chunks and update a live Markdown render."""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.text import Text
    from sage.cli.branding import get_console
    c = get_console()
    _print_assistant_header(c, model=model)

    accumulated = ""
    # Use Live for smooth streaming
    with Live(
        Text(""),
        console=c,
        refresh_per_second=12,
        vertical_overflow="visible",
    ) as live:
        for chunk in chunks:
            accumulated += chunk
            # Render partial markdown; it degrades gracefully for incomplete blocks
            try:
                live.update(Markdown(accumulated, code_theme="monokai"))
            except Exception:
                live.update(Text(accumulated))
    c.print()
    return accumulated


def _print_assistant_header(console: Any, *, model: str = "") -> None:
    ts = chat_timestamp_str()
    model_part = f" [dim]{model}[/dim]" if model else ""
    console.print(f"\n[bold #2dd4bf]SAGE[/bold #2dd4bf]{model_part} [dim]{ts}[/dim]")


# ── Conversation info box ─────────────────────────────────────────────────────

def print_conversation_info_box(
    payload: Mapping[str, Any] | dict[str, Any],
    *,
    title: str = "Session info:",
    use_rich: bool,
) -> None:
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
            title=f"[dim]{title}[/dim]",
            border_style="#4c566a",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


# ── Enter banner ──────────────────────────────────────────────────────────────

def print_chat_enter_banner(*, use_rich: bool, session_id: str = "") -> None:
    if use_rich:
        from rich import box
        from rich.panel import Panel
        from sage.cli.branding import get_console

        sid = f" [dim]#{session_id[:8]}[/dim]" if session_id else ""
        body = (
            f"[bold #2dd4bf]Chat mode[/bold #2dd4bf]{sid}  "
            "[dim]Responses stream as Markdown.[/dim]\n\n"
            "[dim]Commands:[/dim] "
            "[bold #fbbf24]/back[/bold #fbbf24] [dim]agent mode ·[/dim] "
            "[bold #fbbf24]/clear[/bold #fbbf24] [dim]reset history ·[/dim] "
            "[bold #fbbf24]/paste[/bold #fbbf24] [dim]multiline ·[/dim] "
            "[bold #fbbf24]/run[/bold #fbbf24] [dim]trigger pipeline ·[/dim] "
            "[bold #fbbf24]/context[/bold #fbbf24] [dim]show workspace ·[/dim] "
            "[bold #fbbf24]/model[/bold #fbbf24] [dim]current model ·[/dim] "
            "[bold #fbbf24]/exit[/bold #fbbf24] [dim]quit\n[/dim]"
            "[dim]Tip: type[/dim] [bold #fbbf24]@filename[/bold #fbbf24] "
            "[dim]to inject a file into the conversation.[/dim]"
        )
        get_console().print()
        get_console().print(
            Panel(
                body,
                title="[bold #2dd4bf]SAGE[/bold #2dd4bf] · chat",
                border_style="#0d9488",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        get_console().print()
    else:
        print(
            "[SAGE] Chat — /back agent, /clear history, /paste multiline, "
            "@file inject, /run pipeline, /exit quit."
        )
