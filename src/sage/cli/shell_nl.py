"""
Natural-language lines in the interactive shell are routed to the SAGE pipeline
(``sage run``) when the first token is not a CLI subcommand — OpenClaw-style UX.

Disable with ``SAGE_SHELL_NO_NL=1``. By default NL uses **research** mode (planner
checkpoints; set ``SAGE_SHELL_NL_AUTO=1`` for fully autonomous ``--auto``-style runs).
``SAGE_SHELL_NL_MODE=research`` forces research even if ``SAGE_SHELL_NL_AUTO`` is on.

Intent routing (before the pipeline): ``SAGE_SHELL_INTENT=heuristic`` (default),
``ollama`` (small local classifier), or ``off`` (always run the pipeline for NL).

Chat transcripts (``chat`` / ``start chat``) are saved under ``.sage/chat_sessions/`` and
prepended to ``sage run`` / NL pipeline prompts unless ``SAGE_CHAT_ATTACH_TO_RUN=0``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace


def shell_natural_language_enabled() -> bool:
    return not (os.environ.get("SAGE_SHELL_NO_NL") or "").strip()


def run_shell_natural_language_goal(line: str, *, use_rich: bool) -> None:
    """Invoke ``cmd_run`` with the full line as ``prompt`` (no ``run`` prefix)."""
    from sage.cli.run_cmd import cmd_run

    raw_auto = (os.environ.get("SAGE_SHELL_NL_AUTO", "0") or "0").strip().lower()
    auto = raw_auto in ("1", "true", "yes", "on")
    mode_env = (os.environ.get("SAGE_SHELL_NL_MODE") or "").strip().lower()
    if mode_env == "research":
        auto = False
    no_clarify = bool((os.environ.get("SAGE_SHELL_NL_NO_CLARIFY") or "").strip())

    args = SimpleNamespace(
        prompt=line,
        auto=auto,
        silent=False,
        no_clarify=no_clarify,
        repo="",
        explain_routing=False,
    )

    if use_rich:
        try:
            from rich.panel import Panel

            from sage.cli.branding import get_console

            preview = line[:200] + ("…" if len(line) > 200 else "")
            get_console().print()
            get_console().print(
                Panel.fit(
                    "[muted]Running your request through the coding pipeline.[/muted]\n"
                    f"[accent]{preview}[/accent]\n"
                    "[muted]Explicit[/muted] [accent]run \"…\"[/accent] [muted]for flags; "
                    "[muted]SAGE_SHELL_NL_AUTO=1[/muted] [muted]for autonomous mode; "
                    "[muted]SAGE_SHELL_NO_NL=1[/muted] [muted]to turn off NL routing.[/muted]",
                    title="[brand]SAGE[/brand] · goal",
                    border_style="#0d9488",
                )
            )
        except Exception:
            pass

    cmd_run(args)
