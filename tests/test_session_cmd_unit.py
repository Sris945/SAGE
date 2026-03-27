"""Unit tests for ``sage session`` helpers."""

from __future__ import annotations

import os

from sage.cli.session_cmd import cmd_session_refresh, cmd_session_reset


def test_session_reset_removes_state_and_sets_env(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()
    state = tmp_path / "memory" / "system_state.json"
    state.write_text("{}")
    monkeypatch.delenv("SAGE_SESSION_ID", raising=False)

    cmd_session_reset(None)

    assert not state.exists()
    assert os.environ.get("SAGE_SESSION_ID")


def test_session_refresh_invokes_status(monkeypatch) -> None:
    called: list[bool] = []

    def fake_status(_args) -> None:
        called.append(True)

    monkeypatch.setattr("sage.cli.main.cmd_status", fake_status)
    cmd_session_refresh(None)
    assert called == [True]
