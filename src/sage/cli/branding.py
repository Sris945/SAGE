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


def print_shell_intro() -> None:
    """Banner when entering interactive shell."""
    from rich.panel import Panel

    print_banner(tagline=True)
    c = get_console()
    quick = (
        "[accent]/commands[/accent]  [muted]·[/muted]  [accent]/help[/accent]  [muted]·[/muted]  "
        "[accent]/skill[/accent]  [muted]·[/muted]  [accent]/model[/accent]  [muted]·[/muted]  "
        "[accent]/context[/accent]  [muted]·[/muted]  [accent]/clear[/accent]"
    )
    c.print(
        Panel.fit(
            f"[accent]Interactive shell[/accent]\n{quick}\n"
            "[muted]Omit the `sage` prefix; leading `/` optional.[/muted]",
            border_style="#0d9488",
            padding=(0, 1),
        )
    )
    c.print(
        "  [muted]e.g.[/muted] [brand]/prep[/brand]   [brand]/doctor[/brand]   "
        '[brand]/run[/brand] [muted]"your goal"[/muted] [muted]--auto[/muted]'
    )
    c.print()


def print_panel_title(text: str) -> None:
    get_console().print(f"  [accent]{text}[/accent]")


def should_activate_shell() -> bool:
    """True when bare `sage` should drop into the shell (TTY, not opted out)."""
    if os.environ.get("SAGE_NON_INTERACTIVE", "").strip():
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False
