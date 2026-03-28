"""
Interactive shell line input: GNU readline fallback, or prompt_toolkit (menus + meta).
See **docs/CLI.md** in the repo for how the slash menu relates to the line buffer and Enter.

Set ``SAGE_SHELL_SIMPLE_INPUT=1`` to force plain ``input()`` + readline (tests/CI).
Set ``SAGE_SHELL_NO_STATUSBAR=1`` to hide the bottom status row (ollama, session, model).
Set ``SAGE_SHELL_INTENT=heuristic|ollama|off`` for NL routing (see ``sage.cli.shell_intent``).
Set ``SAGE_SHELL_DEBUG=1`` once to print which ``sage`` / ``shell_input`` files are loaded (dev PATH issues).
Set ``SAGE_SHELL_FANCY_PROMPT=1`` for the ``›`` prompt instead of ASCII `` > ``.
Set ``SAGE_SHELL_PLAIN_PROMPT=1`` for a bare ``sage>`` prompt (no ANSI; rarely needed).
Set ``SAGE_SHELL_NO_MOUSE=1`` to disable prompt_toolkit mouse reporting (menu remains keyboard-driven).
Set ``SAGE_SHELL_NO_PAGER=1`` to print `/commands` and `/help` without ``less`` (full scroll in the terminal).
Set ``SAGE_SHELL_NO_INPUT_FRAME=1`` to disable the framed “chat row” (top/bottom rules around the prompt).

The slash menu uses **prompt_toolkit** whenever it is installed and
``SAGE_SHELL_SIMPLE_INPUT`` is unset — even if Rich banner printing failed (so you still get
``/`` completions and the styled ``SAGE`` prompt).

**Slash command menu:** ``/`` inserts and **opens** completions (arrows + Enter).
**Tab** on an empty line lists commands. **Ctrl+Space** forces the menu (needed when
history-search mode disables completion-while-typing). **Mouse** wheel over the menu
scrolls the list (same interpreter as ``sage``; enable terminal mouse / do not set
``SAGE_SHELL_NO_MOUSE=1``). **PgUp** / **PgDn** jump a page while the menu is open.

``SAGE_SHELL_MENU_ROWS`` (default 12, clamped 8–40) sets both reserved terminal space and,
after a small layout patch, the completion menu’s max height (prompt_toolkit’s default is 16).

Completion style defaults to **COLUMN** (floating menu). ``TERM=linux`` without
``DISPLAY`` / ``WAYLAND_DISPLAY`` / ``SSH_CONNECTION`` uses READLINE_LIKE. Override:

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
from typing import Iterable

from prompt_toolkit.completion import Completer, CompleteEvent, Completion


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
        ("--fresh", "run: ignore memory/handoff.json this run"),
        ("--plan-only", "run: print DAG then exit (no tools)"),
        ("--dry-run", "run: log tool ops but do not apply patches"),
        ("--include", "run: scope hint (repeatable glob/path)"),
    ):
        words.add(flag)
        meta[flag] = desc

    return sorted(words), meta


def _open_completions_buffer(event, *, select_first: bool) -> None:
    """Start completion menu and refresh; works with READLINE_LIKE (no complete_while_typing)."""
    b = event.app.current_buffer
    app = event.app

    def _start() -> None:
        try:
            b.start_completion(select_first=select_first)
        except Exception:
            pass
        try:
            app.invalidate()
        except Exception:
            pass

    loop = getattr(app, "loop", None)
    if loop is not None and hasattr(loop, "call_soon"):
        loop.call_soon(_start)
    else:
        _start()


def _slash_menu_key_bindings():
    """
    ``/`` → insert + open completion menu (palette).
    Ctrl+Space → open menu without inserting (pair with Tab).

    ``eager=True`` on ``/`` so it wins over ambiguous handlers.
    Set ``SAGE_SHELL_VI_SEARCH_SLASH=1`` to skip the ``/`` binding (Vi forward search).
    """
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @Condition
    def _completion_menu_open() -> bool:
        try:
            return get_app().current_buffer.complete_state is not None
        except Exception:
            return False

    @kb.add(Keys.PageDown, filter=_completion_menu_open)
    def _completion_page_down(event) -> None:
        n = _completion_scroll_page_step()
        event.app.current_buffer.complete_next(count=n, disable_wrap_around=True)

    @kb.add(Keys.PageUp, filter=_completion_menu_open)
    def _completion_page_up(event) -> None:
        n = _completion_scroll_page_step()
        event.app.current_buffer.complete_previous(count=n, disable_wrap_around=True)

    if not os.environ.get("SAGE_SHELL_VI_SEARCH_SLASH", "").strip():

        @kb.add("/", eager=True)
        def _slash_inserts_and_completes(event) -> None:
            b = event.app.current_buffer
            b.insert_text("/")
            _open_completions_buffer(event, select_first=True)

    @kb.add(Keys.ControlSpace)
    def _ctrl_space_completes(event) -> None:
        _open_completions_buffer(event, select_first=True)

    return kb


def _menu_rows_reserved() -> int:
    try:
        r = int((os.environ.get("SAGE_SHELL_MENU_ROWS") or "12").strip())
    except ValueError:
        r = 12
    return max(8, min(r, 40))


def _completion_scroll_page_step() -> int:
    """PgUp/PgDn step size — about one screen of the completion menu."""
    h = _menu_rows_reserved()
    return max(1, min(h - 1, 24))


def _patch_completion_menu_max_height(session: object) -> None:
    """
    ``PromptSession`` hard-codes ``CompletionsMenu(..., max_height=16)``. Raise it so the
    menu matches ``SAGE_SHELL_MENU_ROWS`` / :func:`_menu_rows_reserved` (scrollbar + wheel).
    """
    if os.environ.get("SAGE_SHELL_MENU_MAX_HEIGHT", "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    try:
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.layout import walk
        from prompt_toolkit.layout.menus import CompletionsMenuControl
    except Exception:
        return
    try:
        layout = getattr(session, "layout", None)
        root = getattr(layout, "container", None) if layout is not None else None
        if root is None:
            return
    except Exception:
        return
    max_h = _menu_rows_reserved()
    for node in walk(root):
        if isinstance(node, Window) and isinstance(
            getattr(node, "content", None), CompletionsMenuControl
        ):
            node.height = Dimension(min=1, max=max_h)
            break


def _resolve_complete_style():
    """
    Prefer COLUMN (floating) menu so completion-while-typing stays enabled.

    PTK disables ``complete_while_typing`` when style is READLINE_LIKE; that breaks
    ``/`` instant menus unless the user hits Tab/Ctrl+Space — avoid READLINE_LIKE on
    typical GUI terminals even if TERM says ``linux``.
    """
    from prompt_toolkit.shortcuts import CompleteStyle

    if os.environ.get("SAGE_SHELL_COLUMN_COMPLETIONS", "").strip():
        return CompleteStyle.COLUMN
    if os.environ.get("SAGE_SHELL_READLINE_COMPLETIONS", "").strip():
        return CompleteStyle.READLINE_LIKE
    term = (os.environ.get("TERM") or "").strip().lower()
    if term == "dumb":
        return CompleteStyle.READLINE_LIKE
    if term == "linux":
        # Framebuffer TTY: list-above; else assume framebuffer on modern box is rare.
        if not (
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("SSH_CONNECTION")
        ):
            return CompleteStyle.READLINE_LIKE
    return CompleteStyle.COLUMN


class _SageSlashCompleter(Completer):
    """
    Custom completer: ``WordCompleter`` treats ``/`` as a word boundary, so ``/p``
    was parsed as ``p`` and never matched ``/prep``. We treat the last
    whitespace-delimited token as the prefix (including a leading ``/``).

    Must subclass :class:`prompt_toolkit.completion.Completer` so the default
    ``get_completions_async`` exists; recent prompt_toolkit calls the async API
    directly on the completer object.
    """

    def __init__(self, words: list[str], meta: dict[str, str]) -> None:
        self._words = words
        self._meta = meta

    def _empty_tab_candidates(self) -> list[str]:
        """Single-token commands for Tab on an empty line (no spaces in candidate)."""
        singles = [w for w in self._words if " " not in w]
        return sorted(singles)[:48]

    def get_completions(
        self, document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        ev = complete_event
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


def create_shell_prompt_session(*, use_rich: bool, minimal: bool = False):
    """
    Build a :class:`~prompt_toolkit.shortcuts.PromptSession` to reuse for every line
    in :func:`sage.cli.main.cmd_shell`. Reuse keeps readline-style history and avoids
    creating a new full-screen app each prompt (fewer redraw glitches).

    ``minimal=True`` skips the bottom toolbar and on-disk history so a broken Ollama probe,
    model router, or ``~/.cache`` permission issue cannot block the REPL.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.styles import Style

    complete_style = _resolve_complete_style()
    words, meta = _completion_words_and_meta()
    completer = _SageSlashCompleter(words, meta)

    # Input “chat row” uses PromptSession ``show_frame`` (Unicode box rules). See below.
    # Palette: teal brand + slate chrome + warm amber/peach accents (Claude Code–adjacent).
    style = Style.from_dict(
        {
            "prompt": "ansiturquoise bold",
            "separator": "ansibrightblack",
            "shell.muted": "#94a3b8",
            "shell.accent": "#fbbf24 bold",
            "shell.brand": "#2dd4bf bold",
            "shell.chevron": "#fcd34d bold",
            "shell.state": "#34d399",
            "shell.cwd": "#e2e8f0",
            "shell.hint": "#64748b",
            # Framed input (top/bottom horizontal rules + side borders).
            "frame": "bg:#0c1222",
            "frame.border": "#5b6578",
            "bottom-toolbar": "bg:#0f172a",
            "bottom-toolbar.text": "#94a3b8",
            # Slash menu: command column (warm), meta (cool gray).
            "completion-menu": "bg:#151c2e #f8fafc",
            "completion-menu.completion": "fg:#fdba74 bold",
            "completion-menu.completion.current": "bg:#3d2d4d fg:#fecaca bold",
            "completion-menu.meta.completion": "bg:#151c2e fg:#94a3b8",
            "completion-menu.meta.completion.current": "bg:#3d2d4d fg:#cbd5e1",
        }
    )

    if minimal:
        history: object = InMemoryHistory()
    else:
        history_path = os.path.expanduser("~/.cache/sage/shell_history")
        try:
            os.makedirs(os.path.dirname(history_path), mode=0o700, exist_ok=True)
            history = FileHistory(history_path)
        except OSError:
            history = InMemoryHistory()

    from prompt_toolkit.formatted_text import FormattedText, HTML

    if os.environ.get("SAGE_SHELL_PLAIN_PROMPT", "").strip():
        message = "sage> "
    elif os.environ.get("SAGE_SHELL_FANCY_PROMPT", "").strip():
        message = HTML("<prompt>SAGE</prompt> <separator>›</separator> ")
    else:
        # Default: Claude Code–style chevron (still SAGE-branded colors).
        message = FormattedText(
            [
                ("class:shell.brand", "SAGE"),
                ("class:shell.muted", " "),
                # Match common CLI habit (e.g. Claude Code): single guillemet, not heavy chevron.
                ("class:shell.chevron", "› "),
            ]
        )

    def _bottom_toolbar():
        if minimal or os.environ.get("SAGE_SHELL_NO_STATUSBAR", "").strip():
            return None
        try:
            from sage.cli.shell_tui import format_shell_bottom_toolbar

            return format_shell_bottom_toolbar()
        except Exception:
            return None

    enable_history_search = bool(os.environ.get("SAGE_SHELL_HISTORY_SEARCH", "").strip())
    mouse_support = not bool(os.environ.get("SAGE_SHELL_NO_MOUSE", "").strip())
    # Full-width top + bottom rules (and vertical edges) around the prompt row — “chat box”.
    show_frame = not bool(os.environ.get("SAGE_SHELL_NO_INPUT_FRAME", "").strip())

    session = PromptSession(
        message,
        completer=completer,
        complete_style=complete_style,
        complete_while_typing=True,
        wrap_lines=False,
        style=style,
        history=history,
        enable_history_search=enable_history_search,
        mouse_support=mouse_support,
        bottom_toolbar=_bottom_toolbar,
        key_bindings=_slash_menu_key_bindings(),
        reserve_space_for_menu=_menu_rows_reserved(),
        show_frame=show_frame,
    )
    _patch_completion_menu_max_height(session)
    return session


def try_create_shell_prompt_session(*, use_rich: bool) -> tuple[object | None, str | None]:
    """
    Try full chrome first, then a minimal PromptSession (still with slash menu).
    Returns (session, error_string_if_failed).
    """
    last_err: str | None = None
    for minimal in (False, True):
        try:
            return create_shell_prompt_session(use_rich=use_rich, minimal=minimal), None
        except Exception as e:
            last_err = f"minimal={minimal}: {e}"
    return None, last_err


def read_shell_line_ptk(*, use_rich: bool) -> str:
    """One line via a fresh prompt session (fallback when session reuse is not used)."""
    sess, err = try_create_shell_prompt_session(use_rich=use_rich)
    if sess is None:
        raise RuntimeError(err or "prompt_toolkit session unavailable")
    return sess.prompt()


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
    sess, _e = try_create_shell_prompt_session(use_rich=use_rich)
    if sess is not None:
        return sess.prompt()
    return _read_shell_line_simple(use_rich=use_rich)
