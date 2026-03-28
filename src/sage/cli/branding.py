"""
CLI visuals — teal / amber editorial palette (distinct from generic “AI purple”).
"""

from __future__ import annotations

import os
import sys

_TAGLINE = "Self-improving Autonomous Generation Engine"


def get_console():
    from rich.console import Console
    from rich.theme import Theme

    theme = Theme(
        {
            "brand": "bold #2dd4bf",
            "brand_dim": "#5eead4",
            "accent": "bold #fbbf24",
            "muted": "dim #94a3b8",
            "rule": "#0f766e",
        }
    )
    return Console(theme=theme, stderr=False)


def _version_str() -> str:
    try:
        from sage.version import get_version

        return get_version()
    except Exception:
        return "0.1.0"


def print_banner(*, tagline: bool = True) -> None:
    """Wordmark in a panel (Rich)."""
    from rich.panel import Panel

    c = get_console()
    ver = _version_str()
    if tagline:
        inner = f"[brand]SAGE[/brand]  [muted]{ver}[/muted]\n[muted]{_TAGLINE}[/muted]"
    else:
        inner = f"[brand]SAGE[/brand]  [muted]{ver}[/muted]"
    c.print()
    c.print(
        Panel.fit(
            inner,
            border_style="#0d9488",
            padding=(0, 1),
        )
    )
    c.print()


def print_cli_help_banner() -> None:
    """Shown when non-interactive `sage` prints help."""
    print_banner(tagline=True)


def print_activation_footer() -> None:
    c = get_console()
    c.print(
        "  [muted]Tip:[/muted] [accent]sage init[/accent] [muted]·[/muted] "
        '[accent]sage doctor[/accent] [muted]·[/muted] [accent]sage run "…" --auto[/accent]'
    )
    c.print()


def print_shell_intro() -> bool:
    """
    Banner when entering interactive shell — compact; slash palette is the primary UX.

    Never raises: falls back to ASCII lines if Rich/panel fails (e.g. broken TERM).
    Returns True if the full Rich panel rendered.
    """
    quick = (
        "[accent]/commands[/accent]  [muted]·[/muted]  [accent]/help[/accent]  [muted]·[/muted]  "
        "[accent]/skill[/accent]  [muted]·[/muted]  [accent]/model[/accent]  [muted]·[/muted]  "
        "[accent]/context[/accent]  [muted]·[/muted]  [accent]/clear[/accent]  [muted]·[/muted]  "
        "[accent]/reset[/accent]  [muted]·[/muted]  [accent]/refresh[/accent]  [muted]·[/muted]  "
        "[accent]session handoff[/accent]"
    )
    body = (
        f"[accent]Interactive shell[/accent]\n{quick}\n\n"
        "[dim]────────────────────────────────────────────────────────────────[/dim]\n"
        "[white bold]Type[/white bold] [accent]/[/accent] [white bold]— command menu[/white bold] "
        "[muted](arrows · Enter · Ctrl+Space).[/muted]  "
        "[white bold]Or describe the change in plain English[/white bold] [muted](same as[/muted] "
        "[accent]run[/accent][muted]).[/muted]\n"
        "[muted]No `sage` prefix ·[/muted] [accent]/chat[/accent] [muted]local thread ·[/muted] "
        "[accent]run[/accent] [muted]·[/muted] [accent]--auto[/accent] [muted]·[/muted] "
        "[accent]--plan-only[/accent]"
    )
    try:
        from rich import box
        from rich.panel import Panel

        print_banner(tagline=True)
        c = get_console()
        c.print(
            Panel(
                body,
                title="[brand]SAGE[/brand] · shell",
                border_style="#0d9488",
                padding=(0, 1),
                box=box.ROUNDED,
            )
        )
        c.print()
        return True
    except Exception:
        try:
            print_banner(tagline=False)
        except Exception:
            print("SAGE shell")
        print(
            "  Type / for the command menu (needs prompt_toolkit). "
            "/commands · /help · /run \"…\" --auto · /exit"
        )
        print()
        return False


def print_panel_title(text: str) -> None:
    get_console().print(f"  [accent]{text}[/accent]")


def print_agent_line(role: str, message: str) -> None:
    """One Rich line for pipeline agents (Planner, Coder, Reviewer, …)."""
    try:
        from rich.markup import escape

        c = get_console()
        c.print(f"[accent]{escape(role)}[/accent] {escape(message)}")
    except Exception:
        print(f"\n[{role}] {message}")


def print_run_trust_strip() -> None:
    """One line: cwd + short tool policy (shown at start of ``sage run``)."""
    from pathlib import Path

    try:
        from sage.execution.tool_policy import format_tool_policy_summary

        c = get_console()
        cwd = str(Path.cwd().resolve())
        if len(cwd) > 72:
            cwd = "…" + cwd[-69:]
        pol = (format_tool_policy_summary() or "").replace("\n", " ").strip()
        if len(pol) > 220:
            pol = pol[:217] + "…"
        c.print(f"  [muted]workspace[/muted] {cwd}")
        if pol:
            c.print(f"  [muted]policy[/muted] {pol}")
    except Exception:
        pass


def print_run_task_header(task_id: str, description: str, attempt: int) -> None:
    """Rich line for ``sage run`` when a DAG task starts (replaces plain ``[SAGE] Executing``)."""
    from rich.panel import Panel

    c = get_console()
    desc = (description or "").replace("\n", " ")
    if len(desc) > 96:
        desc = desc[:93] + "…"
    c.print()
    c.print(
        Panel.fit(
            f"[brand]{task_id}[/brand]  [muted]attempt {attempt}[/muted]\n[muted]{desc}[/muted]",
            border_style="#0d9488",
            title="[accent]Task[/accent]",
            padding=(0, 1),
        )
    )


def print_session_complete_banner() -> None:
    """Footer when a run finishes and memory is saved."""
    from rich.panel import Panel

    c = get_console()
    c.print()
    c.print(
        Panel.fit(
            "[brand]Session complete[/brand]  ·  [muted]memory saved[/muted]",
            border_style="#0d9488",
            title="[accent]SAGE[/accent]",
            padding=(0, 2),
        )
    )
    c.print()


def should_activate_shell() -> bool:
    """True when bare `sage` should drop into the shell (TTY, not opted out)."""
    if os.environ.get("SAGE_NON_INTERACTIVE", "").strip():
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False
