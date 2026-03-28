"""Tests for interactive shell status bar."""

from __future__ import annotations

from sage.cli.shell_tui import format_shell_bottom_toolbar


def test_bottom_toolbar_includes_policy_and_session(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAGE_SESSION_ID", "abcd1234")  # <=10 chars shown in full
    monkeypatch.setenv("SAGE_TOOL_POLICY", "standard")

    ft = format_shell_bottom_toolbar()
    text = "".join(fragment[1] for fragment in ft)

    assert "std" in text
    assert "abcd1234" in text
    assert "fresh" in text
    assert "ui" in text
    assert "policy" in text or "std" in text
    assert "\n" not in text


def test_bottom_toolbar_saved_when_state_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "system_state.json").write_text('{"k": 1}')
    monkeypatch.delenv("SAGE_SESSION_ID", raising=False)

    ft = format_shell_bottom_toolbar()
    text = "".join(fragment[1] for fragment in ft)

    assert "saved" in text
    assert "sess —" in text or "—" in text  # no session id
