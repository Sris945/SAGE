"""
Single-line bottom status for the prompt_toolkit toolbar (no wrap; clipped to terminal width).

Uses ``class:bottom-toolbar.text`` so the whole row shares the same background as
``bottom-toolbar`` in :mod:`sage.cli.shell_input` (avoids striped / wrong fill on multi-line text).
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


def _term_cols() -> int:
    try:
        import shutil

        return max(24, shutil.get_terminal_size().columns)
    except Exception:
        return 80


def _clip_line(text: str, cols: int) -> str:
    """One physical line; ellipsis if wider than the terminal."""
    one = " ".join((text or "").split())
    if len(one) <= cols:
        return one
    if cols <= 2:
        return one[:cols]
    return one[: cols - 1] + "…"


def _ollama_token() -> str:
    try:
        import ollama  # type: ignore

        ollama.list()
        return "ollama ok"
    except Exception:
        return "ollama ×"


def _policy_short(policy: str) -> str:
    p = (policy or "").strip().lower()
    if p == "standard":
        return "std"
    if p == "strict":
        return "strict"
    return p[:8] if p else "?"


def _short_model(name: str, max_len: int) -> str:
    n = (name or "").strip()
    if len(n) <= max_len:
        return n
    if "/" in n:
        tail = n.split("/")[-1]
        if len(tail) <= max_len:
            return tail
        return "…" + n[-(max_len - 1) :]
    return n[: max_len - 1] + "…"


def _single_status_line(cols: int) -> str:
    """All status fields joined with middle dots — one line, then clipped."""
    from sage.execution.tool_policy import tool_policy_mode
    from sage.orchestrator.model_router import ModelRouter

    oll = _ollama_token()

    sid = (os.environ.get("SAGE_SESSION_ID") or "").strip()
    if not sid:
        sid_disp = "—"
    elif len(sid) <= 8:
        sid_disp = sid
    else:
        sid_disp = sid[:7] + "…"

    mode = (os.environ.get("SAGE_SHELL_MODE") or "shell").strip() or "shell"
    ui = (os.environ.get("SAGE_UI_MODE") or "agent").strip() or "agent"
    policy = _policy_short(tool_policy_mode())

    state_path = Path("memory") / "system_state.json"
    state_hint = "saved" if state_path.is_file() and state_path.stat().st_size > 0 else "fresh"

    m_mode = (os.environ.get("SAGE_SHELL_MODE") or "shell").strip() or "shell"
    role = "planner" if m_mode == "run" else "shell_chat"
    router = ModelRouter()
    fallback = router.select(role, task_complexity_score=0.0, failure_count=0)
    display_model = _last_model or fallback

    u = _last_usage or {}
    pt = u.get("prompt_tokens")
    ct = u.get("completion_tokens")
    tt = u.get("total_tokens")
    if pt is not None and ct is not None:
        tok = f"{pt}+{ct}"
    elif tt is not None:
        tok = str(tt)
    else:
        tok = "—/—"

    cwd = Path.cwd()
    cwd_str = str(cwd)
    # Reserve space for other segments; cwd is often the longest.
    max_cwd = max(8, min(28, cols // 3))
    if len(cwd_str) > max_cwd:
        cwd_str = "…" + cwd_str[-(max_cwd - 1) :]

    model_max = max(10, min(32, cols // 3))
    m = _short_model(str(display_model), model_max)

    # Compact, single row (IDE / Claude Code–style status).
    raw = (
        f"{oll} · sess {sid_disp} · {mode} · ui {ui} · {policy} · {state_hint} · "
        f"{m} · tok {tok} · {cwd_str} · /menu"
    )
    return _clip_line(raw, cols)


def format_shell_bottom_toolbar():
    """
    Return a **single** styled line (no newlines) so the bar does not wrap and the
    background stays uniform.
    """
    try:
        from prompt_toolkit.formatted_text import FormattedText
    except ImportError:
        return ""

    try:
        cols = _term_cols()
        line = _single_status_line(cols)
        # Match PromptSession bottom toolbar window (see shell_input Style).
        return FormattedText([("class:bottom-toolbar.text", line)])
    except Exception:
        return FormattedText([("class:bottom-toolbar.text", "SAGE · status unavailable")])
