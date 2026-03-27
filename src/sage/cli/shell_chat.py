"""Interactive `/chat` loop and one-shot NL chat replies (local Ollama)."""

from __future__ import annotations

import os
from typing import Any, Literal

from sage.cli.chat_ui import (
    print_assistant_block,
    print_chat_enter_banner,
    print_conversation_info_box,
    print_user_line,
)
_MAX_TURNS = 24

SAGE_CHAT_SYSTEM = (
    "You are a helpful assistant inside SAGE (Self-improving Autonomous Generation Engine), "
    "a terminal coding agent. Keep answers concise. For repository work, users should describe "
    "goals in plain English or use `run \"…\"`. You do not have direct tool access in this chat mode."
)


def parse_chat_args(parts: list[str]) -> tuple[bool, bool, str | None]:
    """
    Parse ``chat …`` or ``start chat …`` argv tail.

    Returns ``(force_new, resume, initial_message)``. Flags ``new`` / ``resume`` are
    consumed from the front; the rest is the optional first user message.
    """
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


def _router_model() -> str:
    from sage.orchestrator.model_router import ModelRouter

    return ModelRouter().select("shell_chat", task_complexity_score=0.0, failure_count=0)


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
    usage = None
    if isinstance(resp, dict):
        usage = resp.get("usage")
    shell_tui.set_last_model_usage(model=model, usage=usage if isinstance(usage, dict) else None)
    return content, usage if isinstance(usage, dict) else None


def _canned_greeting_reply() -> str:
    return (
        "Hey — I'm SAGE chat. For code changes in your repo, describe what you want in plain English "
        "at the shell prompt (that runs the planner → agents pipeline), or use "
        '`run "…"` with flags like `--auto`. Type /chat to stay here, /commands to see verbs, /back to exit chat.'
    )


def respond_nl_chat(
    line: str,
    *,
    use_rich: bool,
    used_heuristic: bool,
) -> None:
    """Handle CHAT intent from NL routing (not the interactive /chat loop)."""
    if used_heuristic:
        print_assistant_block(body=_canned_greeting_reply(), use_rich=use_rich)
        return

    messages = [
        {"role": "system", "content": SAGE_CHAT_SYSTEM},
        {"role": "user", "content": line},
    ]
    try:
        body, _ = run_shell_chat_turn(messages)
    except Exception as e:
        print_assistant_block(body=f"(chat unavailable: {e})\n{_canned_greeting_reply()}", use_rich=use_rich)
        return
    print_assistant_block(body=body, use_rich=use_rich)


def run_shell_chat_loop(
    *,
    use_rich: bool,
    session: Any,
    initial_message: str | None,
    force_new: bool = False,
    resume: bool = False,
) -> Literal["continue", "exit_shell"]:
    """
    Multi-turn chat until /back or /exit.
    Returns ``exit_shell`` when user quits SAGE entirely.
    """
    from sage.cli.chat_session_store import append_turn, begin_chat_session
    from sage.cli.chat_ui import new_message_id
    from sage.cli.shell_input import read_shell_line

    os.environ["SAGE_SHELL_MODE"] = "chat"
    os.environ["SAGE_UI_MODE"] = "chat"
    sid, _path = begin_chat_session(force_new=force_new, resume=resume)
    print_chat_enter_banner(use_rich=use_rich, session_id=sid)
    mid = new_message_id()
    print_conversation_info_box(
        {
            "message_id": mid,
            "mode": "shell_chat",
            "session_id": (os.environ.get("SAGE_SESSION_ID") or "")[:16] or None,
            "chat_session_id": sid,
            "chat_log": str(_path),
        },
        use_rich=use_rich,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SAGE_CHAT_SYSTEM},
    ]
    if initial_message and initial_message.strip():
        print_user_line(text=initial_message.strip(), use_rich=use_rich)
        append_turn(role="user", content=initial_message.strip())
        messages.append({"role": "user", "content": initial_message.strip()})
        try:
            body, _ = run_shell_chat_turn(messages)
        except Exception as e:
            body = f"(ollama error: {e})"
        print_assistant_block(body=body, use_rich=use_rich)
        append_turn(role="assistant", content=body)
        messages.append({"role": "assistant", "content": body})

    while True:
        try:
            line = read_shell_line(use_rich=use_rich, session=session).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in {"/exit", "/quit", "exit", "quit"}:
            os.environ["SAGE_SHELL_MODE"] = "shell"
            os.environ["SAGE_UI_MODE"] = "agent"
            return "exit_shell"
        if line in {"/back", "/pipeline", "/agent"}:
            os.environ["SAGE_SHELL_MODE"] = "shell"
            os.environ["SAGE_UI_MODE"] = "agent"
            if use_rich:
                from sage.cli.branding import get_console

                get_console().print(
                    "  [muted]Agent mode — NL runs the build pipeline; prior chat (if any) is attached to "
                    "the next run.[/muted] [accent]agent clear[/accent] [muted]drops attach context.[/muted]"
                )
            else:
                print("[SAGE] Agent mode — chat transcript attaches to the next pipeline run.")
            return "continue"
        if line == "/":
            from sage.cli.shell_support import print_commands_table

            print_commands_table()
            continue
        if line in ("/commands", "commands"):
            from sage.cli.shell_support import print_commands_table

            print_commands_table()
            continue
        if line == "/info":
            print_conversation_info_box(
                {
                    "message_id": new_message_id(),
                    "mode": "shell_chat",
                    "session_id": (os.environ.get("SAGE_SESSION_ID") or "")[:24] or None,
                    "turns": len(messages) // 2,
                },
                use_rich=use_rich,
            )
            continue
        if line.startswith("/"):
            if use_rich:
                from sage.cli.branding import get_console

                get_console().print(
                    "  [muted]Unknown slash in chat — use[/muted] [accent]/back[/accent] [muted]for shell commands.[/muted]"
                )
            else:
                print("[SAGE] Use /back to run shell commands.")
            continue

        if len(messages) >= _MAX_TURNS * 2 + 1:
            tail = messages[:1] + messages[-(_MAX_TURNS * 2) :]
            messages = tail

        print_user_line(text=line, use_rich=use_rich)
        append_turn(role="user", content=line)
        messages.append({"role": "user", "content": line})
        try:
            body, _ = run_shell_chat_turn(messages)
        except Exception as e:
            body = f"(ollama error: {e})"
        print_assistant_block(body=body, use_rich=use_rich)
        append_turn(role="assistant", content=body)
        messages.append({"role": "assistant", "content": body})

    os.environ["SAGE_SHELL_MODE"] = "shell"
    os.environ["SAGE_UI_MODE"] = "agent"
    return "continue"
