"""
Interactive `/chat` loop and one-shot NL chat replies (local Ollama).

Improvements over the original:
  - Streaming Markdown responses via Rich Live
  - Workspace-aware system prompt (git branch, cwd, recent files)
  - @filename mention: injects file content into the conversation
  - /clear  — reset conversation history
  - /paste  — multiline input mode (end with a line containing only '.')
  - /run    — trigger the pipeline from within chat
  - /context — show what workspace context was injected
  - /model  — show current routing model
  - Smart context compression instead of blunt slice truncation
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

from sage.cli.chat_ui import (
    print_assistant_block,
    print_chat_enter_banner,
    print_conversation_info_box,
    print_user_line,
    stream_assistant_block,
    new_message_id,
)

_MAX_HISTORY_CHARS = 32_000   # soft cap; compressor kicks in above this
_MAX_FILE_INJECT_BYTES = 16_000
_AT_FILE_RE = re.compile(r"@([\w./\-]+)")


# ── System prompt ─────────────────────────────────────────────────────────────

def _workspace_context_block() -> str:
    """Build a concise snapshot of the current workspace for the system prompt."""
    lines: list[str] = []
    cwd = Path.cwd()
    lines.append(f"Working directory: {cwd}")

    # Git branch + status
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(cwd), stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        lines.append(f"Git branch: {branch}")
    except Exception:
        pass
    try:
        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=str(cwd), stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        if status:
            changed = status.splitlines()[:8]
            lines.append(f"Modified files ({len(changed)} shown): " + ", ".join(
                l.strip().split()[-1] for l in changed if l.strip()
            ))
    except Exception:
        pass

    # Top-level structure
    try:
        entries = sorted(cwd.iterdir(), key=lambda p: (p.is_file(), p.name))
        names = [e.name for e in entries if not e.name.startswith(".")][:12]
        if names:
            lines.append("Project layout: " + "  ".join(names))
    except Exception:
        pass

    return "\n".join(lines)


def _build_system_prompt() -> str:
    ctx = _workspace_context_block()
    return (
        "You are SAGE Chat — an expert coding assistant embedded in a terminal agent.\n"
        "You have deep knowledge of Python, system design, debugging, and software architecture.\n\n"
        "WORKSPACE CONTEXT (live snapshot):\n"
        f"{ctx}\n\n"
        "CAPABILITIES:\n"
        "- Answer questions about code, architecture, debugging, and best practices\n"
        "- Read files when the user mentions @filename (content is injected automatically)\n"
        "- For code changes, say so and the user can type /run \"task\" to invoke the pipeline\n\n"
        "STYLE:\n"
        "- Use Markdown. Wrap all code in fenced code blocks with a language tag.\n"
        "- Be concise but precise. Prefer examples over abstract explanations.\n"
        "- When suggesting shell commands, put them in ```bash blocks.\n"
        "- When unsure, say so rather than guessing.\n"
    )


# ── @file injection ───────────────────────────────────────────────────────────

def _inject_at_files(line: str, cwd: Path) -> tuple[str, list[str]]:
    """
    Find @filename mentions in line, read those files, and append their content.
    Returns (augmented_line, list_of_injected_paths).
    """
    mentions = _AT_FILE_RE.findall(line)
    if not mentions:
        return line, []
    injected: list[str] = []
    extra_blocks: list[str] = []
    for raw in mentions:
        path = (cwd / raw).resolve()
        # Security: stay in cwd subtree
        try:
            path.relative_to(cwd.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()[:_MAX_FILE_INJECT_BYTES].decode("utf-8", errors="replace")
            ext = path.suffix.lstrip(".")
            block = f"\n\n--- @{raw} ---\n```{ext}\n{content}\n```"
            extra_blocks.append(block)
            injected.append(str(path.relative_to(cwd)))
        except OSError:
            continue
    return line + "".join(extra_blocks), injected


# ── Multiline paste ───────────────────────────────────────────────────────────

def _read_paste_block(*, use_rich: bool) -> str:
    """Read lines until a line containing only '.' — returns joined content."""
    if use_rich:
        from sage.cli.branding import get_console
        get_console().print(
            "  [dim]Paste mode — type or paste lines, then enter[/dim] [bold #fbbf24].[/bold #fbbf24] [dim]alone to finish:[/dim]"
        )
    else:
        print("Paste mode — end with a line containing only '.'")
    lines: list[str] = []
    while True:
        try:
            l = input("  ")
        except (EOFError, KeyboardInterrupt):
            break
        if l.strip() == ".":
            break
        lines.append(l)
    return "\n".join(lines)


# ── Context compression ───────────────────────────────────────────────────────

def _compress_history(messages: list[dict]) -> list[dict]:
    """Drop oldest non-system turns when history grows large."""
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total <= _MAX_HISTORY_CHARS:
        return messages
    system = [m for m in messages if m["role"] == "system"]
    turns = [m for m in messages if m["role"] != "system"]
    # Drop oldest pairs until under limit
    while turns and total > _MAX_HISTORY_CHARS:
        dropped = turns.pop(0)
        total -= len(str(dropped.get("content", "")))
    return system + turns


# ── Model helper ──────────────────────────────────────────────────────────────

def _router_model() -> str:
    from sage.orchestrator.model_router import ModelRouter
    return ModelRouter().select("shell_chat", task_complexity_score=0.0, failure_count=0)


# ── One-shot turn (non-streaming, for one-liners) ─────────────────────────────

def run_shell_chat_turn(
    messages: list[dict[str, Any]],
    *,
    timeout_s: float | None = None,
) -> tuple[str, dict[str, Any] | None]:
    from sage.cli import shell_tui
    from sage.llm.ollama_safe import chat_with_timeout

    model = _router_model()
    resp = chat_with_timeout(model=model, messages=messages, timeout_s=timeout_s)
    content = ""
    try:
        content = (resp.get("message") or {}).get("content") or ""
    except Exception:
        content = str(resp)
    usage = resp.get("usage") if isinstance(resp, dict) else None
    shell_tui.set_last_model_usage(model=model, usage=usage if isinstance(usage, dict) else None)
    return content, usage if isinstance(usage, dict) else None


# ── Streaming turn ────────────────────────────────────────────────────────────

def _run_streaming_turn(
    messages: list[dict[str, Any]],
    *,
    use_rich: bool,
    model: str,
) -> str:
    """Stream a response and render it. Returns full text."""
    from sage.llm.ollama_safe import stream_chat
    chunks = stream_chat(model=model, messages=messages, options={"temperature": 0.3})
    return stream_assistant_block(chunks=chunks, use_rich=use_rich, model=model)


# ── Canned reply ──────────────────────────────────────────────────────────────

def _canned_greeting_reply() -> str:
    return (
        "Hey — I'm SAGE chat. I can answer questions about your code, explain concepts, "
        "and help you debug.\n\n"
        "For actual code changes, describe the task at the shell prompt (that runs the full pipeline), "
        "or use `/run \"task description\"` from here.\n\n"
        "Type `/commands` to see everything available, or just ask me a question."
    )


# ── NL one-shot (not the interactive loop) ────────────────────────────────────

def respond_nl_chat(
    line: str,
    *,
    use_rich: bool,
    used_heuristic: bool,
) -> None:
    if used_heuristic:
        print_assistant_block(body=_canned_greeting_reply(), use_rich=use_rich)
        return

    model = _router_model()
    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": line},
    ]
    try:
        if use_rich:
            from sage.llm.ollama_safe import stream_chat, OllamaTimeout
            try:
                chunks = stream_chat(model=model, messages=messages, options={"temperature": 0.3})
                stream_assistant_block(chunks=chunks, use_rich=use_rich, model=model)
                return
            except Exception:
                pass
        body, _ = run_shell_chat_turn(messages)
        print_assistant_block(body=body, use_rich=use_rich, model=model)
    except Exception as e:
        print_assistant_block(
            body=f"(chat unavailable: {e})\n\n{_canned_greeting_reply()}",
            use_rich=use_rich,
        )


# ── Interactive chat loop ─────────────────────────────────────────────────────

def run_shell_chat_loop(
    *,
    use_rich: bool,
    session: Any,
    initial_message: str | None,
    force_new: bool = False,
    resume: bool = False,
) -> Literal["continue", "exit_shell"]:
    """
    Multi-turn streaming chat until /back or /exit.
    Returns ``exit_shell`` when user quits SAGE entirely.
    """
    from sage.cli.chat_session_store import append_turn, begin_chat_session
    from sage.cli.shell_input import read_shell_line

    os.environ["SAGE_SHELL_MODE"] = "chat"
    os.environ["SAGE_UI_MODE"] = "chat"
    sid, _path = begin_chat_session(force_new=force_new, resume=resume)
    print_chat_enter_banner(use_rich=use_rich, session_id=sid)

    model = _router_model()
    cwd = Path.cwd()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _build_system_prompt()},
    ]

    def _do_turn(user_text: str) -> str:
        """Execute one streaming turn. Returns assistant text."""
        nonlocal messages
        messages = _compress_history(messages)
        messages.append({"role": "user", "content": user_text})
        try:
            from sage.llm.ollama_safe import stream_chat
            chunks = stream_chat(model=model, messages=messages, options={"temperature": 0.3})
            body = stream_assistant_block(chunks=chunks, use_rich=use_rich, model=model)
        except Exception as e:
            body = f"(stream error — {e})"
            print_assistant_block(body=body, use_rich=use_rich, model=model)
        messages.append({"role": "assistant", "content": body})
        append_turn(role="assistant", content=body)
        return body

    # Handle initial message passed from CLI
    if initial_message and initial_message.strip():
        msg, injected = _inject_at_files(initial_message.strip(), cwd)
        print_user_line(text=initial_message.strip(), use_rich=use_rich)
        append_turn(role="user", content=msg)
        _do_turn(msg)

    while True:
        try:
            raw = read_shell_line(use_rich=use_rich, session=session).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue

        # ── Slash commands ────────────────────────────────────────────────────
        if raw in {"/exit", "/quit", "exit", "quit"}:
            os.environ["SAGE_SHELL_MODE"] = "shell"
            os.environ["SAGE_UI_MODE"] = "agent"
            return "exit_shell"

        if raw in {"/back", "/pipeline", "/agent"}:
            os.environ["SAGE_SHELL_MODE"] = "shell"
            os.environ["SAGE_UI_MODE"] = "agent"
            _print_back_hint(use_rich)
            return "continue"

        if raw == "/clear":
            messages[:] = [{"role": "system", "content": _build_system_prompt()}]
            if use_rich:
                from sage.cli.branding import get_console
                get_console().print("  [dim]History cleared.[/dim]")
            else:
                print("[SAGE] History cleared.")
            continue

        if raw == "/paste":
            pasted = _read_paste_block(use_rich=use_rich)
            if not pasted.strip():
                continue
            msg, injected = _inject_at_files(pasted, cwd)
            print_user_line(text=f"[paste: {len(pasted.splitlines())} lines]", use_rich=use_rich)
            append_turn(role="user", content=msg)
            _do_turn(msg)
            continue

        if raw == "/context":
            ctx = _workspace_context_block()
            if use_rich:
                from sage.cli.branding import get_console
                from rich.panel import Panel
                from rich.markup import escape
                from rich import box
                get_console().print(
                    Panel(escape(ctx), title="[dim]workspace context[/dim]",
                          border_style="#4c566a", box=box.ROUNDED, padding=(0, 1))
                )
            else:
                print(ctx)
            continue

        if raw == "/model":
            if use_rich:
                from sage.cli.branding import get_console
                from rich.markup import escape
                get_console().print(f"  [dim]model:[/dim] [bold]{escape(model)}[/bold]")
            else:
                print(f"model: {model}")
            continue

        if raw.startswith("/run ") or raw == "/run":
            task = raw[5:].strip()
            if not task:
                if use_rich:
                    from sage.cli.branding import get_console
                    get_console().print("  [dim]Usage:[/dim] [bold #fbbf24]/run[/bold #fbbf24] [dim]\"task description\"[/dim]")
                else:
                    print('Usage: /run "task description"')
                continue
            _trigger_pipeline_run(task, use_rich=use_rich)
            continue

        if raw in {"/", "/commands", "commands"}:
            from sage.cli.shell_support import print_commands_table
            print_commands_table()
            continue

        if raw == "/info":
            print_conversation_info_box(
                {
                    "session_id": sid,
                    "model": model,
                    "turns": (len(messages) - 1) // 2,
                    "history_chars": sum(len(str(m.get("content", ""))) for m in messages),
                    "cwd": str(cwd),
                },
                use_rich=use_rich,
            )
            continue

        if raw.startswith("/"):
            if use_rich:
                from sage.cli.branding import get_console
                from rich.markup import escape
                get_console().print(
                    f"  [dim]Unknown command[/dim] [bold]{escape(raw)}[/bold]"
                    "[dim] — type[/dim] [bold #fbbf24]/commands[/bold #fbbf24] [dim]for the list.[/dim]"
                )
            else:
                print(f"[SAGE] Unknown: {raw} — type /commands")
            continue

        # ── Regular message ────────────────────────────────────────────────────
        msg, injected = _inject_at_files(raw, cwd)
        if injected:
            display = raw + f"  [dim](+{', '.join(injected)})[/dim]"
        else:
            display = raw
        print_user_line(text=raw, use_rich=use_rich)
        append_turn(role="user", content=msg)
        _do_turn(msg)

    os.environ["SAGE_SHELL_MODE"] = "shell"
    os.environ["SAGE_UI_MODE"] = "agent"
    return "continue"


def _print_back_hint(use_rich: bool) -> None:
    if use_rich:
        from sage.cli.branding import get_console
        get_console().print(
            "  [dim]Agent mode — NL runs the build pipeline. "
            "Chat transcript (if any) attaches to the next run.[/dim]"
        )
    else:
        print("[SAGE] Agent mode — chat transcript attaches to next run.")


def _trigger_pipeline_run(task: str, *, use_rich: bool) -> None:
    """
    Trigger a sage run from within chat mode and stream output.
    This drops back to agent mode, runs the pipeline, then returns to chat.
    """
    if use_rich:
        from sage.cli.branding import get_console
        from rich.markup import escape
        get_console().print(f"\n  [dim]Triggering pipeline:[/dim] [bold]{escape(task)}[/bold]")
    else:
        print(f"[SAGE] Running: {task}")

    import sys
    import subprocess
    cmd = [sys.executable, "-m", "sage.cli.main", "run", task]
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        if use_rich:
            from sage.cli.branding import get_console
            from rich.markup import escape
            get_console().print(f"  [red]Pipeline error:[/red] {escape(str(e))}")
        else:
            print(f"[SAGE] Pipeline error: {e}")


# ── parse_chat_args (used by main.py) ─────────────────────────────────────────

def parse_chat_args(parts: list[str]) -> tuple[bool, bool, str | None]:
    """Parse ``chat …`` argv tail → (force_new, resume, initial_message)."""
    if not parts or parts[0].lower() != "chat":
        return False, False, None
    rest = parts[1:]
    force_new = False
    resume = False
    i = 0
    while i < len(rest):
        t = rest[i].lower()
        if t == "new":
            force_new = True
            i += 1
        elif t == "resume":
            resume = True
            i += 1
        else:
            break
    if force_new and resume:
        resume = False
    initial = " ".join(rest[i:]).strip() or None
    return force_new, resume, initial
