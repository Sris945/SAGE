"""Natural-language shell routing → pipeline."""

from __future__ import annotations

from unittest.mock import patch

from sage.cli.shell_support import SHELL_TOP_LEVEL_COMMANDS


def test_top_level_includes_run_not_arbitrary_english():
    assert "run" in SHELL_TOP_LEVEL_COMMANDS
    assert "hello" not in SHELL_TOP_LEVEL_COMMANDS


def test_shell_natural_language_enabled_env(monkeypatch):
    import sage.cli.shell_nl as sn

    monkeypatch.setenv("SAGE_SHELL_NO_NL", "1")
    assert not sn.shell_natural_language_enabled()
    monkeypatch.delenv("SAGE_SHELL_NO_NL", raising=False)
    assert sn.shell_natural_language_enabled()


@patch("sage.cli.run_cmd.cmd_run")
def test_run_shell_natural_language_goal_invokes_cmd_run(mock_cmd_run):
    from sage.cli.shell_nl import run_shell_natural_language_goal

    run_shell_natural_language_goal("hello there speak to me", use_rich=False)
    mock_cmd_run.assert_called_once()
    args = mock_cmd_run.call_args[0][0]
    assert args.prompt == "hello there speak to me"
    assert args.auto is False


@patch("sage.cli.run_cmd.cmd_run")
def test_run_shell_natural_language_goal_auto_env(mock_cmd_run, monkeypatch):
    from sage.cli.shell_nl import run_shell_natural_language_goal

    monkeypatch.setenv("SAGE_SHELL_NL_AUTO", "1")
    run_shell_natural_language_goal("go", use_rich=False)
    args = mock_cmd_run.call_args[0][0]
    assert args.auto is True
