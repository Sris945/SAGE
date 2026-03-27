"""Workspace bootstrap (`sage init`)."""


def test_init_workspace_creates_sage_and_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sage.cli.workspace_init import init_workspace

    summary = init_workspace(tmp_path, force=False)
    assert (tmp_path / ".sage" / "rules.md").is_file()
    assert (tmp_path / "memory").is_dir()
    assert summary["root"] == str(tmp_path.resolve())
    assert any(".sage" in str(p) for p in summary["created"])


def test_init_idempotent_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sage.cli.workspace_init import init_workspace

    init_workspace(tmp_path, force=False)
    first = (tmp_path / ".sage" / "rules.md").read_text()
    init_workspace(tmp_path, force=False)
    second = (tmp_path / ".sage" / "rules.md").read_text()
    assert first == second


def test_init_force_overwrites_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sage.cli.workspace_init import init_workspace

    init_workspace(tmp_path, force=False)
    (tmp_path / ".sage" / "rules.md").write_text("custom", encoding="utf-8")
    init_workspace(tmp_path, force=True)
    body = (tmp_path / ".sage" / "rules.md").read_text()
    assert "custom" not in body
    assert "Project rules" in body
