"""Tests for interactive shell helpers."""

from sage.cli.shell_support import suggest_commands, skill_id_from_path


def test_suggest_commands_fuzzy():
    assert "prep" in suggest_commands("pep", limit=8)
    assert "doctor" in suggest_commands("docter", limit=8)


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
