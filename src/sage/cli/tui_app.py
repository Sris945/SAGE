"""
Optional full-screen TUI shell (Textual).

Install::

    python -m pip install textual
    # or
    pip install 'sage[tui]`

Run::

    sage tui

Same CLI tokens as ``sage shell``, but with an on-screen log and a ``/`` command
hint list (no prompt_toolkit required for the canvas — only Textual).
"""

from __future__ import annotations

import io
import os
import shlex
import sys
from contextlib import redirect_stderr, redirect_stdout


def _completion_lines(prefix: str) -> list[str]:
    from sage.cli.shell_support import COMMAND_CATALOG, SHELL_BUILTIN_COMMANDS

    p = prefix.strip().lower()
    out: list[str] = []
    seen: set[str] = set()
    for b in sorted(SHELL_BUILTIN_COMMANDS):
        tok = f"/{b}"
        if tok.lower().startswith(p) and tok not in seen:
            seen.add(tok)
            out.append(f"{tok}  (builtin)")
    for row in COMMAND_CATALOG:
        tok = f"/{row.name}"
        if tok.lower().startswith(p) and tok not in seen:
            seen.add(tok)
            out.append(f"{tok}  — {row.summary}")
    return out[:22]


def _exec_cli_line(line: str, log) -> None:
    from argparse import ArgumentError

    from sage.cli.main import build_parser, dispatch_command

    line = line.strip()
    if not line:
        return
    if line in {"/exit", "/quit", "exit", "quit"}:
        raise KeyboardInterrupt
    if line.startswith("/"):
        line = line[1:].strip()
    if not line:
        return
    try:
        parts = shlex.split(line)
    except ValueError as e:
        log.write(f"[red]parse error:[/red] {e}")
        return
    if not parts:
        return

    parser = build_parser(exit_on_error=False)
    try:
        ns = parser.parse_args(parts)
    except ArgumentError as e:
        log.write(f"[red]usage:[/red] {e}")
        return

    if getattr(ns, "command", None) == "shell":
        log.write("[yellow]Open[/yellow] `sage shell` in another terminal — nested shell is disabled in TUI.")
        return
    if getattr(ns, "command", None) == "tui":
        log.write("[dim]Already in TUI.[/dim]")
        return

    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            code = dispatch_command(ns, parser)
        text = buf.getvalue().rstrip()
        if text:
            for ln in text.splitlines():
                log.write(ln)
        if code:
            log.write(f"[dim]exit {code}[/dim]")
    except SystemExit as e:
        text = buf.getvalue().rstrip()
        if text:
            for ln in text.splitlines():
                log.write(ln)
        c = e.code
        ci = int(c) if isinstance(c, int) else 1
        if ci:
            log.write(f"[dim]exit {ci}[/dim]")


def run_tui_shell() -> None:
    try:
        from textual import on
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Vertical
        from textual.widgets import Footer, Input, RichLog, Static
    except ImportError as e:
        print(
            "[SAGE] Textual is not installed (full-screen TUI).\n\n"
            f"  {sys.executable} -m pip install 'textual>=0.58.0'\n"
            "  # or: pip install 'sage[tui]'\n\n"
            "For the line-based shell with a `/` dropdown, install prompt_toolkit:\n"
            f"  {sys.executable} -m pip install 'prompt_toolkit>=3.0.36'\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    os.environ.setdefault("SAGE_INSIDE_SHELL", "1")
    os.environ.setdefault("SAGE_SHELL_MODE", "shell")
    os.environ.setdefault("SAGE_UI_MODE", "tui")

    class SageTuiShell(App[None]):
        CSS = """
        Screen { background: #0c1222; }
        #main { height: 1fr; }
        RichLog { height: 1fr; border: heavy #5b6578; background: #0f172a; padding: 0 1; }
        #comp {
            height: auto;
            max-height: 12;
            border: solid #475569;
            background: #111827;
            color: #e2e8f0;
            padding: 0 1;
            margin-top: 0;
            display: none;
        }
        #inp {
            dock: bottom;
            height: 3;
            border: heavy #5b6578;
            background: #0f172a;
            padding: 0 1;
        }
        Input {
            background: #111827;
            border: none;
            color: #f8fafc;
        }
        Footer { background: #0f172a; color: #94a3b8; }
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit"),
            Binding("escape", "blur", "Unfocus", show=False),
        ]

        def compose(self) -> ComposeResult:
            with Vertical(id="main"):
                yield RichLog(id="log", highlight=True, markup=True, auto_scroll=True)
                yield Static("", id="comp")
            yield Input(placeholder="› /commands · run \"…\" --auto · doctor · exit", id="inp")
            yield Footer()

        def on_mount(self) -> None:
            self.title = "SAGE"
            self.sub_title = "tui"
            log = self.query_one("#log", RichLog)
            log.write("[bold #2dd4bf]SAGE[/] [dim]TUI ·[/dim] [yellow]/[/][dim] filters commands · Enter runs · Ctrl+Q quit[/dim]")
            log.write("[dim]Install prompt_toolkit + run `sage` for the framed line shell with the same menu inline.[/dim]")

        def _update_comp(self, value: str) -> None:
            comp = self.query_one("#comp", Static)
            if not value.startswith("/"):
                comp.display = False
                comp.update("")
                return
            lines = _completion_lines(value)
            if not lines:
                comp.display = False
                comp.update("")
                return
            comp.display = True
            comp.update("\n".join(lines))

        @on(Input.Changed, "#inp")
        def _inp_change(self, event: Input.Changed) -> None:
            self._update_comp(event.value)

        @on(Input.Submitted, "#inp")
        def _inp_submit(self, event: Input.Submitted) -> None:
            raw = event.value
            event.input.value = ""
            self._update_comp("")
            log = self.query_one("#log", RichLog)
            if raw.strip() in {"/exit", "/quit", "exit", "quit"}:
                self.exit()
                return
            log.write(f"[#94a3b8]›[/] {raw}")
            try:
                _exec_cli_line(raw, log)
            except KeyboardInterrupt:
                self.exit()
            except Exception as e:
                log.write(f"[red]{e}[/red]")

        def action_blur(self) -> None:
            try:
                self.query_one("#inp").blur()
            except Exception:
                pass

        def action_quit(self) -> None:
            self.exit()

    SageTuiShell().run()
