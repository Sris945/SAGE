"""
Interactive shell line input: GNU readline fallback, or prompt_toolkit (menus + meta).
See **docs/CLI.md** in the repo for how the slash menu relates to the line buffer and Enter.

Set ``SAGE_SHELL_SIMPLE_INPUT=1`` to force plain ``input()`` + readline (tests/CI).
Set ``SAGE_SHELL_NO_STATUSBAR=1`` to hide the bottom status row (ollama, session, model).
Set ``SAGE_SHELL_INTENT=heuristic|ollama|off`` for NL routing (see ``sage.cli.shell_intent``).
Set ``SAGE_SHELL_DEBUG=1`` once to print which ``sage`` / ``shell_input`` files are loaded (dev PATH issues).
Set ``SAGE_SHELL_FANCY_PROMPT=1`` for the ``›`` prompt instead of ASCII `` > ``.
Set ``SAGE_SHELL_PLAIN_PROMPT=1`` for a bare ``sage>`` prompt (no ANSI; rarely needed).

The slash menu uses **prompt_toolkit** whenever it is installed and
``SAGE_SHELL_SIMPLE_INPUT`` is unset — even if Rich banner printing failed (so you still get
``/`` completions and the styled ``SAGE`` prompt).

**Slash command menu (OpenClaw-style):** pressing ``/`` inserts the slash and **immediately opens**
the completion menu (navigate with arrows, Enter to accept). This is not “tab-only” autofill.

Completion style defaults to **COLUMN** (floating menu) on modern terminals (``TERM`` not
``linux``/``dumb``). Override:

- ``SAGE_SHELL_COLUMN_COMPLETIONS=1`` — force column menu
- ``SAGE_SHELL_READLINE_COMPLETIONS=1`` — list above the line (linux console / SSH)

The interactive shell uses **one** :class:`prompt_toolkit.shortcuts.PromptSession` for the whole
session (see :func:`create_shell_prompt_session`). Reusing a session keeps history and avoids
per-line redraw glitches. ``SAGE_SHELL_HISTORY_SEARCH=1`` re-enables Ctrl+R incremental search at
the cost of disabling completion-while-typing (prompt_toolkit buffer behavior).
"""

from __future__ import annotations

import difflib
import os
import re
from typing import Iterator


def _read_shell_line_simple(*, use_rich: bool) -> str:
    try:
        import readline  # noqa: F401
    except ImportError:
        pass
    if use_rich:
        # Plain ASCII only: ANSI in the ``input()`` prompt confuses readline's width
        # math on many Linux/bash setups — backspace then deletes the wrong columns and
        # *looks* like it is erasing "SAGE". Set SAGE_SHELL_COLORED_SIMPLE_PROMPT=1 for teal ANSI.
        if os.environ.get("SAGE_SHELL_COLORED_SIMPLE_PROMPT", "").strip():
            return input("\x1b[36;1mSAGE\x1b[0m\x1b[2m >\x1b[0m ")
        return input("SAGE > ")
    return input("sage> ")


def _completion_words_and_meta() -> tuple[list[str], dict[str, str]]:
    from sage.cli.shell_support import COMMAND_CATALOG, SHELL_BUILTIN_COMMANDS

    meta: dict[str, str] = {}
    words: set[str] = set()

    builtin_desc: dict[str, str] = {
        "help": "Full help + command table",
        "commands": "Print command table",
        "chat": "Chat thread — transcript attaches to next run",
        "start": "start chat — new Cursor-style thread",
        "agent": "agent | agent clear — build mode / drop attach",
        "?": "Same as /help",
        "skill": "List or show bundled SKILL.md (prompt injection)",
        "skills": "Alias for skill",
        "model": "Show models.yaml routing summary",
        "models": "Alias for model",
        "context": "cwd, memory size, config paths",
        "clear": "Clear the terminal",
        "exit": "Leave the shell",
        "quit": "Leave the shell",
        "reset": "Clear system_state.json + new session id",
        "refresh": "Re-print session state from disk",
    }
    for b in SHELL_BUILTIN_COMMANDS:
        desc = builtin_desc.get(b, "Shell builtin")
        words.add(b)
        meta[b] = desc
        words.add(f"/{b}")
        meta[f"/{b}"] = desc

    for row in COMMAND_CATALOG:
        words.add(row.name)
        meta[row.name] = row.summary
        words.add(f"/{row.name}")
        meta[f"/{row.name}"] = row.summary

    for sub, desc in (
        ("scan", "Hardware: OS, RAM, VRAM"),
        ("suggest", "Suggest Ollama tags + tier"),
        ("apply", "Merge suggested routing into models.yaml"),
        ("pull", "ollama pull suggested tags"),
        ("permissions set policy strict", "Persist strict tool policy"),
        ("permissions set policy standard", "Persist standard tool policy"),
        ("permissions set workspace clear", "Drop saved workspace override"),
        ("permissions set skills clear", "Use bundled skills tree"),
        ("permissions reset", "Remove .sage/policy.json + clear env"),
    ):
        words.add(sub)
        meta[sub] = desc

    for flag, desc in (
        ("--auto", "run: skip most human checkpoints"),
        ("--silent", "run: fully autonomous"),
        ("--no-clarify", "run: skip planner Q&A"),
        ("--repo", "run: existing repo path for codebase intel"),
        ("--explain-routing", "run: print routing summary after"),
    ):
        words.add(flag)
        meta[flag] = desc

    return sorted(words), meta


def _slash_menu_key_bindings():
    """
    Open prompt_toolkit completion as soon as ``/`` is typed (OpenClaw-style palette).

    ``eager=True`` so this wins over generic printable handlers in the merged
    registry. No emacs/vi filter — those were preventing the handler from
    firing in some sessions (menu never appeared).

    Set ``SAGE_SHELL_VI_SEARCH_SLASH=1`` to skip this binding (Vi forward search).
    """
    from prompt_toolkit.key_binding import KeyBindings

    if os.environ.get("SAGE_SHELL_VI_SEARCH_SLASH", "").strip():
        return KeyBindings()

    kb = KeyBindings()

    @kb.add("/", eager=True)
    def _open_slash_menu(event) -> None:
        b = event.app.current_buffer
        b.insert_text("/")
        # Defer so the buffer/layout updates before the completion UI builds (fixes menu not opening).
        app = event.app

        def _start() -> None:
            b.start_completion(select_first=False)
            app.invalidate()

        loop = getattr(app, "loop", None)
        if loop is not None and hasattr(loop, "call_soon"):
            loop.call_soon(_start)
        else:
            _start()

    return kb


def _menu_rows_reserved() -> int:
    try:
        r = int((os.environ.get("SAGE_SHELL_MENU_ROWS") or "12").strip())
    except ValueError:
        r = 12
    return max(8, min(r, 40))


def _resolve_complete_style():
    """COLUMN menu on capable terminals; READLINE_LIKE on bare Linux console."""
    from prompt_toolkit.completion import CompleteStyle

    if os.environ.get("SAGE_SHELL_COLUMN_COMPLETIONS", "").strip():
        return CompleteStyle.COLUMN
    if os.environ.get("SAGE_SHELL_READLINE_COMPLETIONS", "").strip():
        return CompleteStyle.READLINE_LIKE
    term = (os.environ.get("TERM") or "").strip().lower()
    if term in ("linux", "dumb"):
        return CompleteStyle.READLINE_LIKE
    return CompleteStyle.COLUMN


class _SageSlashCompleter:
    """
    Custom completer: ``WordCompleter`` treats ``/`` as a word boundary, so ``/p``
    was parsed as ``p`` and never matched ``/prep``. We treat the last
    whitespace-delimited token as the prefix (including a leading ``/``).
    """

    # Subclassing prompt_toolkit.completion.Completer is optional; duck-typing works.

    def __init__(self, words: list[str], meta: dict[str, str]) -> None:
        self._words = words
        self._meta = meta

    def _empty_tab_candidates(self) -> list[str]:
        """Single-token commands for Tab on an empty line (no spaces in candidate)."""
        singles = [w for w in self._words if " " not in w]
        return sorted(singles)[:48]

    def get_completions(self, document, complete_event) -> Iterator:
        from prompt_toolkit.completion import CompleteEvent, Completion

        ev = complete_event or CompleteEvent()
        text = document.text_before_cursor
        if text.endswith(" "):
            return

        m = re.search(r"(\S+)$", text)
        prefix = m.group(1) if m else ""
        if prefix == "":
            # Tab on empty line: explicit completion only (not while-typing flood).
            if ev.completion_requested:
                for w in self._empty_tab_candidates():
                    yield Completion(
                        w,
                        start_position=0,
                        display_meta=self._meta.get(w, ""),
                    )
            return

        pl = prefix.lower()
        words = self._words
        meta = self._meta

        hits = [w for w in words if w.lower().startswith(pl)]
        if len(hits) < 3:
            extra = difflib.get_close_matches(pl, words, n=16, cutoff=0.2)
            for w in extra:
                if w not in hits:
                    hits.append(w)
        if len(hits) < 3:
            for w in words:
                if pl in w.lower() and w not in hits:
                    hits.append(w)

        start_pos = -len(prefix)
        cap = 48
        hits = hits[:cap]
        n = len(hits)
        for i, w in enumerate(hits):
            m = meta.get(w, "")
            if prefix.startswith("/") and n > 1:
                suffix = f" ({i + 1}/{n})"
                m = f"{m}{suffix}" if m else suffix.strip()
            yield Completion(
                w,
                start_position=start_pos,
                display_meta=m,
            )


def create_shell_prompt_session(*, use_rich: bool):
    """
    Build a :class:`~prompt_toolkit.shortcuts.PromptSession` to reuse for every line
    in :func:`sage.cli.main.cmd_shell`. Reuse keeps readline-style history and avoids
    creating a new full-screen app each prompt (fewer redraw glitches).
    """
    from prompt_toolkit import PromptSession

    complete_style = _resolve_complete_style()
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style

    from sage.cli.shell_tui import format_shell_bottom_toolbar

    words, meta = _completion_words_and_meta()
    completer = _SageSlashCompleter(words, meta)

    style = Style.from_dict(
        {
            "prompt": "ansiturquoise bold",
            "separator": "ansibrightblack",
            "shell.muted": "ansibrightblack",
            "shell.accent": "ansiyellow bold",
            "shell.brand": "ansiturquoise bold",
            "shell.state": "ansigreen",
            "shell.cwd": "ansiwhite",
            "shell.hint": "ansibrightblack",
            # Claude-style slash menu: cyan command column, dim meta (see prompt_toolkit layout)
            "completion-menu": "bg:#2d333b #d8dee9",
            "completion-menu.completion": "fg:#88c0d0 bold",
            "completion-menu.completion.current": "bg:#434c5e fg:#eceff4 nobold",
            "completion-menu.meta.completion": "bg:#2d333b fg:#6b7280",
            "completion-menu.meta.completion.current": "bg:#434c5e fg:#a0a8b0",
        }
    )

    history_path = os.path.expanduser("~/.cache/sage/shell_history")
    try:
        os.makedirs(os.path.dirname(history_path), mode=0o700, exist_ok=True)
        history = FileHistory(history_path)
    except OSError:
        history = None

    # Styled prompt does not require Rich (only prompt_toolkit). Plain ``sage>`` only when opted in.
    from prompt_toolkit.formatted_text import FormattedText, HTML

    if os.environ.get("SAGE_SHELL_PLAIN_PROMPT", "").strip():
        message = "sage> "
    elif use_rich and os.environ.get("SAGE_SHELL_FANCY_PROMPT", "").strip():
        message = HTML("<prompt>SAGE</prompt> <separator>›</separator> ")
    else:
        message = FormattedText(
            [
                ("class:prompt", "SAGE"),
                ("class:separator", " > "),
            ]
        )

    def _bottom_toolbar():
        if os.environ.get("SAGE_SHELL_NO_STATUSBAR", "").strip():
            return None
        return format_shell_bottom_toolbar()

    # prompt_toolkit disables buffer complete_while_typing when enable_history_search is True
    # (see PromptSession._create_buffer). Default: history search off so Tab + typing completions work.
    enable_history_search = bool(os.environ.get("SAGE_SHELL_HISTORY_SEARCH", "").strip())

    return PromptSession(
        message,
        completer=completer,
        complete_style=complete_style,
        complete_while_typing=True,
        wrap_lines=False,
        style=style,
        history=history,
        enable_history_search=enable_history_search,
        bottom_toolbar=_bottom_toolbar,
        key_bindings=_slash_menu_key_bindings(),
        reserve_space_for_menu=_menu_rows_reserved(),
    )


def read_shell_line_ptk(*, use_rich: bool) -> str:
    """One line via a fresh prompt session (fallback when session reuse is not used)."""
    return create_shell_prompt_session(use_rich=use_rich).prompt()


def print_shell_input_diagnostics(*, shell_session: object | None) -> None:
    """
    When ``SAGE_SHELL_DEBUG=1``, show which code is running. Use this if edits to the repo
    do not seem to apply — usually a different ``sage`` on ``PATH`` or no editable install.
    """
    import importlib.util
    import sys

    import sage.cli.shell_input as si

    ptk_v = "n/a"
    try:
        import prompt_toolkit

        ptk_v = getattr(prompt_toolkit, "__version__", "?")
    except Exception:
        pass

    spec = importlib.util.find_spec("sage")
    root = (spec.origin if spec else "") or ""
    print(f"[SAGE shell] debug  sage package: {root}")
    print(f"[SAGE shell] debug  shell_input: {si.__file__}")
    print(f"[SAGE shell] debug  prompt_toolkit: {ptk_v}")
    print(
        f"[SAGE shell] debug  SAGE_SHELL_SIMPLE_INPUT="
        f"{os.environ.get('SAGE_SHELL_SIMPLE_INPUT', '')!r}"
    )
    print(f"[SAGE shell] debug  reused PromptSession: {shell_session is not None}")
    print(f"[SAGE shell] debug  python: {sys.executable}")


def read_shell_line(*, use_rich: bool, session: object | None = None) -> str:
    """
    One line from the user. Uses prompt_toolkit when available unless
    ``SAGE_SHELL_SIMPLE_INPUT`` is set.

    Pass ``session`` from :func:`create_shell_prompt_session` so the same session is used
    for every line (recommended from ``cmd_shell``).
    """
    if os.environ.get("SAGE_SHELL_SIMPLE_INPUT", "").strip():
        return _read_shell_line_simple(use_rich=use_rich)
    if session is not None:
        return session.prompt()
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return _read_shell_line_simple(use_rich=use_rich)
    try:
        return read_shell_line_ptk(use_rich=use_rich)
    except Exception:
        return _read_shell_line_simple(use_rich=use_rich)
