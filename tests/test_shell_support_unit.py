"""Tests for interactive shell helpers."""

from sage.cli.shell_support import suggest_commands, skill_id_from_path


def test_strip_mistaken_sage_prefix():
    from sage.cli.main import _strip_mistaken_sage_cli_prefix

    assert _strip_mistaken_sage_cli_prefix('sage run "x" --auto') == 'run "x" --auto'
    assert _strip_mistaken_sage_cli_prefix(": sage status") == "status"
    assert _strip_mistaken_sage_cli_prefix("  sage  ") == ""


def test_suggest_commands_fuzzy():
    assert "prep" in suggest_commands("pep", limit=8)
    assert "doctor" in suggest_commands("docter", limit=8)


def test_sage_slash_completer_matches_slash_prefix():
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    from sage.cli.shell_input import _SageSlashCompleter, _completion_words_and_meta

    words, meta = _completion_words_and_meta()
    c = _SageSlashCompleter(words, meta)
    doc = Document("/p", cursor_position=2)
    comps = list(c.get_completions(doc, CompleteEvent(text_inserted=True)))
    texts = [x.text for x in comps]
    assert any(t.startswith("/prep") or t == "prep" for t in texts)


def test_sage_slash_completer_tab_on_empty_line():
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    from sage.cli.shell_input import _SageSlashCompleter, _completion_words_and_meta

    words, meta = _completion_words_and_meta()
    c = _SageSlashCompleter(words, meta)
    doc = Document("", cursor_position=0)
    comps = list(c.get_completions(doc, CompleteEvent(completion_requested=True)))
    assert len(comps) >= 5
    texts = {x.text for x in comps}
    assert "help" in texts or "/help" in texts


def test_shell_input_simple_mode(monkeypatch):
    """read_shell_line uses plain input when SAGE_SHELL_SIMPLE_INPUT is set."""
    monkeypatch.setenv("SAGE_SHELL_SIMPLE_INPUT", "1")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "exit")
    from sage.cli.shell_input import read_shell_line

    assert read_shell_line(use_rich=False).strip() == "exit"


def test_skill_id_from_path(monkeypatch, tmp_path):
    root = tmp_path / "skills"
    (root / "workflow" / "tdd").mkdir(parents=True)
    p = root / "workflow" / "tdd" / "SKILL.md"
    p.write_text("x", encoding="utf-8")

    from sage.prompt_engine import skill_injector as si

    monkeypatch.setattr(si, "bundled_skills_root", lambda: root)

    from sage.cli import shell_support as ss

    monkeypatch.setattr(ss, "_bundled_skills_dir", lambda: root)

    assert skill_id_from_path(p) == "workflow/tdd"
