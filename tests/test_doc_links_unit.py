"""Tests for CLI documentation URL helpers."""

from __future__ import annotations


def test_doc_url_uses_env(monkeypatch) -> None:
    from sage.cli import doc_links as dl

    dl.repo_url_effective.cache_clear()
    monkeypatch.setenv("SAGE_REPO_URL", "https://github.com/acme/sage")
    assert dl.repo_url_effective() == "https://github.com/acme/sage"
    assert dl.doc_url_effective("docs/CLI.md").endswith("/blob/main/docs/CLI.md")


def test_doc_url_contains_blob_path(monkeypatch) -> None:
    from sage.cli import doc_links as dl

    dl.repo_url_effective.cache_clear()
    monkeypatch.setenv("SAGE_REPO_URL", "https://github.com/acme/sage")
    u = dl.doc_url_effective("docs/INSTALL.md")
    assert "/blob/main/docs/INSTALL.md" in u
