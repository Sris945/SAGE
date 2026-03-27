"""Tests for chat session JSONL + run prepend."""

from __future__ import annotations

from sage.cli.chat_session_store import append_turn, begin_chat_session, maybe_prepend_chat_transcript


def test_begin_and_append_and_prepend(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAGE_WORKSPACE_ROOT", str(tmp_path))
    sid, path = begin_chat_session(force_new=True, resume=False)
    assert path.is_file()
    assert path.name == f"{sid}.jsonl"
    append_turn(role="user", content="hello")
    append_turn(role="assistant", content="hi")
    monkeypatch.setenv("SAGE_CHAT_SESSION_PATH", str(path))
    monkeypatch.setenv("SAGE_CHAT_SESSION_ID", sid)
    out = maybe_prepend_chat_transcript("add tests")
    assert "Prior shell chat" in out
    assert "add tests" in out
    assert "user: hello" in out
    assert "assistant: hi" in out


def test_parse_chat_args() -> None:
    from sage.cli.shell_chat import parse_chat_args

    assert parse_chat_args(["chat"]) == (False, False, None)
    assert parse_chat_args(["chat", "new", "hi"]) == (True, False, "hi")
    assert parse_chat_args(["chat", "resume"]) == (False, True, None)
    assert parse_chat_args(["chat", "new", "resume"]) == (True, False, None)  # new wins over resume


def test_prepend_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAGE_CHAT_ATTACH_TO_RUN", "0")
    monkeypatch.setenv("SAGE_CHAT_SESSION_PATH", str(tmp_path / "nope.jsonl"))
    assert maybe_prepend_chat_transcript("x") == "x"
