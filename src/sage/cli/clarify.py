"""
Interactive clarification (planner ``brainstorm_questions``) — Claude-style Q&A before execution.

Used when the planner returns clarifying questions and the run is interactive (TTY)
with clarification enabled (see ``--no-clarify`` / ``SAGE_NO_CLARIFY``).
"""

from __future__ import annotations


def collect_clarification_answers(questions: list[str]) -> str:
    """
    Present numbered questions and collect answers.

    Returns:
        A single string suitable to append to the user goal as ``Clarifications:``.
        Empty string if the user skipped everything or ``questions`` is empty.
    """
    qs = [str(q).strip() for q in (questions or []) if str(q).strip()]
    if not qs:
        return ""

    try:
        from rich import box
        from rich.panel import Panel
        from rich.prompt import Prompt

        from sage.cli.branding import get_console

        c = get_console()
        c.print()
        c.print(
            Panel.fit(
                "[accent]The planner needs a bit more detail[/accent] before building the task graph.\n"
                "[muted]Answer each prompt (Enter to skip that question).[/muted]",
                title="[brand]Clarify[/brand]",
                border_style="#0d9488",
                padding=(0, 1),
                box=box.ROUNDED,
            )
        )
        blocks: list[str] = []
        for i, q in enumerate(qs, 1):
            c.print(f"  [accent]{i}.[/accent] [white]{q}[/white]")
            try:
                ans = Prompt.ask("     Answer", default="", show_default=False)
            except (EOFError, KeyboardInterrupt):
                ans = ""
            ans = (ans or "").strip()
            if ans:
                blocks.append(f"- Q: {q}\n  A: {ans}")
        c.print()
        return "\n".join(blocks) if blocks else ""
    except Exception:
        # Fallback: plain stdin (tests / minimal env)
        print("\n[SAGE] Clarifying questions:")
        for i, q in enumerate(qs, 1):
            print(f"  {i}. {q}")
        try:
            line = input("[You] Answers (one line, or Enter to skip all): ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        return line


def should_offer_clarification(
    *,
    mode: str,
    clarify_flag: bool,
    no_clarify_env: bool,
) -> bool:
    """Whether the planner may block for Q&A."""
    if mode == "silent":
        return False
    if not clarify_flag:
        return False
    if no_clarify_env:
        return False
    return True
