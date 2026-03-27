"""Tests for shell NL intent routing."""

from __future__ import annotations

def test_classify_off_is_always_code(monkeypatch) -> None:
    from sage.cli.shell_intent import ShellIntentKind, classify_shell_line_ex

    monkeypatch.setenv("SAGE_SHELL_INTENT", "off")
    k, heur = classify_shell_line_ex("hey there")
    assert k == ShellIntentKind.CODE
    assert heur is False


def test_heuristic_greeting_is_chat(monkeypatch) -> None:
    from sage.cli.shell_intent import ShellIntentKind, classify_shell_line_ex

    monkeypatch.setenv("SAGE_SHELL_INTENT", "heuristic")
    k, heur = classify_shell_line_ex("hey")
    assert k == ShellIntentKind.CHAT
    assert heur is True


def test_heuristic_ambiguous_defaults_to_code(monkeypatch) -> None:
    from sage.cli.shell_intent import ShellIntentKind, classify_shell_line_ex

    monkeypatch.setenv("SAGE_SHELL_INTENT", "heuristic")
    k, heur = classify_shell_line_ex("add JWT authentication to the API")
    assert k == ShellIntentKind.CODE
    assert heur is False


def test_conversational_favor_and_rhetorical_question_are_chat(monkeypatch) -> None:
    from sage.cli.shell_intent import ShellIntentKind, classify_shell_line_ex

    monkeypatch.setenv("SAGE_SHELL_INTENT", "heuristic")
    for line in ("very well do me a favor", "do i look stupid?"):
        k, heur = classify_shell_line_ex(line)
        assert k == ShellIntentKind.CHAT, line
        assert heur is True


def test_parse_json_object_extracts_braces() -> None:
    from sage.cli.shell_intent import _parse_json_object

    assert _parse_json_object('Sure.\n{"intent":"code","confidence":0.9}') == {
        "intent": "code",
        "confidence": 0.9,
    }
