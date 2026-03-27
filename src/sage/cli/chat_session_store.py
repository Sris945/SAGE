"""
Persist multi-turn shell chat to JSONL and optionally prepend transcripts to ``sage run``.

Env:
  SAGE_CHAT_SESSION_ID / SAGE_CHAT_SESSION_PATH — set while a chat session is active or after /back
    (path remains so the next NL ``run`` can attach context).
  SAGE_CHAT_ATTACH_TO_RUN — ``1`` (default) prepend transcript; ``0`` to disable.
  SAGE_CHAT_MAX_CONTEXT_CHARS — cap for injected transcript (default 16000).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _workspace_root() -> Path:
    return Path(os.environ.get("SAGE_WORKSPACE_ROOT") or os.getcwd()).resolve()


def _sessions_dir() -> Path:
    p = _workspace_root() / ".sage" / "chat_sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _active_pointer_path() -> Path:
    return _sessions_dir() / "active.json"


def session_file_path(session_id: str) -> Path:
    return _sessions_dir() / f"{session_id}.jsonl"


def clear_chat_session_env() -> None:
    """Drop attach context for the next run (files on disk are not deleted)."""
    for k in ("SAGE_CHAT_SESSION_ID", "SAGE_CHAT_SESSION_PATH"):
        os.environ.pop(k, None)


def begin_chat_session(*, force_new: bool, resume: bool) -> tuple[str, Path]:
    """
    Choose or create a session id and JSONL path; set env for downstream ``run``.

    * ``resume`` — continue last active session if present (append to same JSONL).
    * ``force_new`` — always new id (ignore resume).
    * neither — start a **new** session (Cursor-style new thread).
    """
    if force_new:
        return _create_new_session()
    if resume:
        ap = _active_pointer_path()
        if ap.is_file():
            try:
                data = json.loads(ap.read_text(encoding="utf-8"))
                sid = str(data.get("id") or "").strip()
                if sid:
                    path = session_file_path(sid)
                    if path.is_file():
                        os.environ["SAGE_CHAT_SESSION_ID"] = sid
                        os.environ["SAGE_CHAT_SESSION_PATH"] = str(path)
                        return sid, path
            except (OSError, json.JSONDecodeError):
                pass
    return _create_new_session()


def _create_new_session() -> tuple[str, Path]:
    sid = uuid.uuid4().hex[:16]
    path = session_file_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    _write_active_pointer(sid)
    os.environ["SAGE_CHAT_SESSION_ID"] = sid
    os.environ["SAGE_CHAT_SESSION_PATH"] = str(path)
    return sid, path


def _write_active_pointer(session_id: str) -> None:
    try:
        _active_pointer_path().write_text(
            json.dumps({"id": session_id, "updated": _utc_now()}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_turn(*, role: str, content: str) -> None:
    path = os.environ.get("SAGE_CHAT_SESSION_PATH") or ""
    if not path:
        return
    p = Path(path)
    if not p.parent.is_dir():
        return
    line = json.dumps(
        {"role": role, "content": content, "ts": _utc_now()},
        ensure_ascii=False,
    )
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_transcript_text(*, max_chars: int) -> str:
    path = os.environ.get("SAGE_CHAT_SESSION_PATH") or ""
    if not path:
        return ""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return ""
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines_out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = str(o.get("role") or "?")
        content = str(o.get("content") or "").strip()
        if not content:
            continue
        lines_out.append(f"{role}: {content}")
    text = "\n".join(lines_out)
    if len(text) > max_chars:
        text = "…[truncated]\n" + text[-max_chars:]
    return text


def maybe_prepend_chat_transcript(user_prompt: str) -> str:
    """If a chat session file exists and attach is enabled, prepend to the pipeline prompt."""
    raw = (os.environ.get("SAGE_CHAT_ATTACH_TO_RUN") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return user_prompt
    path = os.environ.get("SAGE_CHAT_SESSION_PATH") or ""
    if not path or not Path(path).is_file():
        return user_prompt
    try:
        max_c = int((os.environ.get("SAGE_CHAT_MAX_CONTEXT_CHARS") or "16000").strip())
    except ValueError:
        max_c = 16000
    max_c = max(2000, min(max_c, 200_000))
    block = load_transcript_text(max_chars=max_c).strip()
    if not block:
        return user_prompt
    sid = (os.environ.get("SAGE_CHAT_SESSION_ID") or "").strip()
    header = f"--- Prior shell chat session (id={sid}) — use this context for the goal below ---\n"
    footer = "\n--- End prior chat ---\n"
    return f"{header}{block}{footer}\n\nCurrent coding goal:\n{user_prompt}"
