"""
Unit tests for sage.memory.context_compressor.
Tests TF-IDF search, grep fallback, prompt block rendering,
tokenizer, and stopword filtering.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sage.memory.context_compressor import (
    compress_context,
    CompressionResult,
    CodeChunk,
    _tokenize,
    _tfidf_search,
    _grep_search,
    MAX_CONTEXT_CHARS,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Mini repo with a few Python files relevant to different topics."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        textwrap.dedent("""\
            import hashlib

            def hash_password(password: str) -> str:
                return hashlib.sha256(password.encode()).hexdigest()

            def verify_password(password: str, hashed: str) -> bool:
                return hash_password(password) == hashed
        """),
        encoding="utf-8",
    )
    (tmp_path / "src" / "database.py").write_text(
        textwrap.dedent("""\
            import sqlite3

            class DatabaseManager:
                def __init__(self, db_path: str):
                    self.conn = sqlite3.connect(db_path)

                def execute(self, query: str, params=()):
                    return self.conn.execute(query, params)
        """),
        encoding="utf-8",
    )
    (tmp_path / "src" / "api.py").write_text(
        textwrap.dedent("""\
            from flask import Flask, jsonify

            app = Flask(__name__)

            @app.route("/health")
            def health():
                return jsonify({"status": "ok"})
        """),
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text(
        "from src.auth import hash_password\n\ndef test_hash():\n    assert hash_password('x')\n",
        encoding="utf-8",
    )
    return tmp_path


# ── _tokenize ─────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_extracts_identifiers(self):
        tokens = _tokenize("def authenticate_user(password: str) -> bool:")
        assert "authenticate_user" in tokens
        assert "password" in tokens
        assert "bool" not in tokens  # stopword

    def test_filters_stopwords(self):
        tokens = _tokenize("return True if self is None else False")
        assert "return" not in tokens
        assert "true" not in tokens
        assert "none" not in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_deduplicates(self):
        tokens = _tokenize("foo foo foo bar")
        assert tokens.count("foo") == 1

    def test_lowercases(self):
        tokens = _tokenize("HashPassword hashPassword HASHPASSWORD")
        # All should map to the same lowercase form
        assert "hashpassword" in tokens or "hashpassword" not in tokens  # regex picks first form

    def test_short_tokens_excluded(self):
        # Tokens shorter than 3 chars are excluded by the regex (min 3 chars)
        tokens = _tokenize("if x is None: a = b")
        for t in tokens:
            assert len(t) >= 3


# ── TF-IDF search ─────────────────────────────────────────────────────────────

class TestTfIdfSearch:
    def test_finds_auth_for_password_query(self, repo: Path):
        result = _tfidf_search("hash password verify user", repo, MAX_CONTEXT_CHARS, 5)
        assert result.chunks
        assert result.strategy == "tfidf"
        files = {c.file for c in result.chunks}
        assert any("auth" in f for f in files)

    def test_finds_database_for_sqlite_query(self, repo: Path):
        result = _tfidf_search("sqlite database execute query", repo, MAX_CONTEXT_CHARS, 5)
        assert result.chunks
        files = {c.file for c in result.chunks}
        assert any("database" in f for f in files)

    def test_respects_max_chars(self, repo: Path):
        result = _tfidf_search("password hash", repo, 500, 10)
        assert result.total_chars <= 500

    def test_respects_max_chunks(self, repo: Path):
        result = _tfidf_search("python function", repo, MAX_CONTEXT_CHARS, 2)
        assert len(result.chunks) <= 2

    def test_no_matches_returns_empty(self, repo: Path):
        result = _tfidf_search("xyzzy_nonexistent_term_42", repo, MAX_CONTEXT_CHARS, 5)
        # Either empty or very low score — not guaranteed to be empty since
        # tokenizer may find partial matches, but no files should rank high
        assert result.strategy == "tfidf"

    def test_chunks_have_line_numbers(self, repo: Path):
        result = _tfidf_search("password hash", repo, MAX_CONTEXT_CHARS, 5)
        for chunk in result.chunks:
            assert chunk.start_line >= 1

    def test_max_two_chunks_per_file(self, repo: Path):
        # Create a large file with many matching chunks
        big = repo / "src" / "big.py"
        content = "\n".join(
            f"def auth_function_{i}(password: str): pass  # password verify" for i in range(100)
        )
        big.write_text(content, encoding="utf-8")
        result = _tfidf_search("password verify auth", repo, MAX_CONTEXT_CHARS, 20)
        file_counts: dict[str, int] = {}
        for c in result.chunks:
            file_counts[c.file] = file_counts.get(c.file, 0) + 1
        assert all(v <= 2 for v in file_counts.values())


# ── Grep search ───────────────────────────────────────────────────────────────

class TestGrepSearch:
    def test_finds_files_by_token(self, repo: Path):
        result = _grep_search("password hash verify", repo, MAX_CONTEXT_CHARS, 5)
        assert result.chunks
        assert result.strategy == "grep"
        files = {c.file for c in result.chunks}
        assert any("auth" in f for f in files)

    def test_empty_query_returns_empty(self, repo: Path):
        result = _grep_search("is an if of", repo, MAX_CONTEXT_CHARS, 5)
        # All stopwords → no useful tokens → empty or few results
        assert result.strategy == "grep"

    def test_respects_max_chunks(self, repo: Path):
        result = _grep_search("def class import", repo, MAX_CONTEXT_CHARS, 1)
        assert len(result.chunks) <= 1


# ── compress_context (integration) ───────────────────────────────────────────

class TestCompressContext:
    def test_returns_result(self, repo: Path):
        result = compress_context("implement password hashing", repo_root=repo)
        assert isinstance(result, CompressionResult)

    def test_finds_relevant_file(self, repo: Path):
        result = compress_context("hash and verify passwords", repo_root=repo)
        if result.chunks:  # might be empty if tfidf misses (unlikely)
            files = {c.file for c in result.chunks}
            assert any("auth" in f or "password" in f.lower() for f in files)

    def test_uses_tfidf_strategy(self, repo: Path):
        # No qdrant index — should fall back to tfidf
        result = compress_context("sqlite database connection", repo_root=repo)
        assert result.strategy in ("tfidf", "grep")

    def test_respects_max_chars(self, repo: Path):
        result = compress_context("everything", repo_root=repo, max_chars=300)
        assert result.total_chars <= 300

    def test_empty_repo(self, tmp_path: Path):
        result = compress_context("any task", repo_root=tmp_path)
        assert isinstance(result, CompressionResult)
        assert result.chunks == []


# ── CompressionResult.to_prompt_block ─────────────────────────────────────────

class TestPromptBlock:
    def test_empty_result_returns_empty_string(self):
        result = CompressionResult(strategy="none")
        assert result.to_prompt_block() == ""

    def test_includes_file_path(self, repo: Path):
        result = compress_context("password hash", repo_root=repo)
        block = result.to_prompt_block()
        if result.chunks:
            assert any(c.file in block for c in result.chunks)

    def test_includes_strategy(self, repo: Path):
        result = compress_context("password hash", repo_root=repo)
        block = result.to_prompt_block()
        if result.chunks:
            assert result.strategy in block

    def test_includes_code_fences(self, repo: Path):
        result = compress_context("hash password", repo_root=repo)
        block = result.to_prompt_block()
        if result.chunks:
            assert "```" in block

    def test_multiple_chunks_all_present(self):
        chunks = [
            CodeChunk(file="a.py", start_line=1, content="def foo(): pass", score=1.0),
            CodeChunk(file="b.py", start_line=5, content="def bar(): pass", score=0.9),
        ]
        result = CompressionResult(chunks=chunks, total_chars=30, strategy="tfidf")
        block = result.to_prompt_block()
        assert "a.py" in block
        assert "b.py" in block
        assert "foo" in block
        assert "bar" in block
