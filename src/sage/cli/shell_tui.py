"""
OpenClaw-style shell chrome: multi-line status for the prompt_toolkit bottom toolbar.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_last_model: str | None = None
_last_usage: dict[str, Any] | None = None


def set_last_model_usage(*, model: str, usage: dict[str, Any] | None) -> None:
    """Updated after local Ollama chat turns (shell chat / classifier)."""
    global _last_model, _last_usage
    _last_model = model
    _last_usage = usage


def clear_last_model_usage() -> None:
    global _last_model, _last_usage
    _last_model = None
    _last_usage = None


def _ollama_status_line() -> str:
    try:
        import ollama  # type: ignore

        ollama.list()
        return "ollama connected | idle"
    except Exception as e:
        msg = str(e).replace("\n", " ")[:48]
        return f"ollama offline | {msg}"


def _session_line() -> str:
    from sage.execution.tool_policy import tool_policy_mode

    sid = (os.environ.get("SAGE_SESSION_ID") or "").strip()
    if not sid:
        sid_disp = "none"
    elif len(sid) <= 10:
        sid_disp = sid
    else:
        sid_disp = f"{sid[:8]}…"

    mode = (os.environ.get("SAGE_SHELL_MODE") or "shell").strip() or "shell"
    ui = (os.environ.get("SAGE_UI_MODE") or "agent").strip() or "agent"
    policy = tool_policy_mode()

    state_path = Path("memory") / "system_state.json"
    if state_path.is_file() and state_path.stat().st_size > 0:
        state_hint = "saved"
    else:
        state_hint = "fresh"

    cwd = Path.cwd()
    cwd_str = str(cwd)
    if len(cwd_str) > 36:
        cwd_str = "…" + cwd_str[-33:]

    return (
        f"agent main | session {sid_disp} (sage) | mode {mode} | ui {ui} | policy {policy} | "
        f"state {state_hint} | {cwd_str}"
    )


def _model_usage_line() -> str:
    from sage.orchestrator.model_router import ModelRouter

    mode = (os.environ.get("SAGE_SHELL_MODE") or "shell").strip() or "shell"
    role = "planner" if mode == "run" else "shell_chat"
    router = ModelRouter()
    fallback = router.select(role, task_complexity_score=0.0, failure_count=0)
    display_model = _last_model or fallback

    u = _last_usage or {}
    pt = u.get("prompt_tokens")
    ct = u.get("completion_tokens")
    tt = u.get("total_tokens")
    if pt is not None and ct is not None:
        tok = f"tokens {pt}+{ct}"
    elif tt is not None:
        tok = f"tokens {tt}"
    else:
        tok = "tokens —/—"
    return f"{display_model} | {tok} | / menu · permissions: sage permissions set …"


def format_shell_bottom_toolbar():
    """
    Three-line status: connection, session block, model/tokens (+ slash hint).
    """
    try:
        from prompt_toolkit.formatted_text import FormattedText
    except ImportError:
        return ""

    line1 = _ollama_status_line()
    line2 = _session_line()
    line3 = _model_usage_line()

    return FormattedText(
        [
            ("class:shell.muted", line1),
            ("\n", ""),
            ("class:shell.muted", line2),
            ("\n", ""),
            ("class:shell.muted", line3),
        ]
    )
