"""
Unit tests for improved chat subsystem:
  - @file injection
  - /clear command resets history
  - _compress_history trims large contexts
  - _build_system_prompt includes workspace context
  - stream_chat integration point
  - print_assistant_block / stream_assistant_block render correctly
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── @file injection ───────────────────────────────────────────────────────────

class TestAtFileInjection:
    def test_injects_existing_file(self, tmp_path: Path):
        from sage.cli.shell_chat import _inject_at_files

        (tmp_path / "main.py").write_text("def hello(): pass\n")
        line = "explain @main.py please"
        augmented, injected = _inject_at_files(line, tmp_path)

        assert "main.py" in injected
        assert "def hello(): pass" in augmented
        assert "explain @main.py please" in augmented

    def test_skips_nonexistent_file(self, tmp_path: Path):
        from sage.cli.shell_chat import _inject_at_files

        line = "what is @ghost.py"
        augmented, injected = _inject_at_files(line, tmp_path)
        assert injected == []
        assert augmented == line

    def test_blocks_path_traversal(self, tmp_path: Path):
        from sage.cli.shell_chat import _inject_at_files

        # @../etc/passwd should be rejected (outside cwd)
        line = "look at @../outside.txt"
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("secret")
        augmented, injected = _inject_at_files(line, tmp_path)
        assert injected == []
        assert "secret" not in augmented

    def test_multiple_files(self, tmp_path: Path):
        from sage.cli.shell_chat import _inject_at_files

        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        line = "compare @a.py and @b.py"
        augmented, injected = _inject_at_files(line, tmp_path)
        assert len(injected) == 2
        assert "x = 1" in augmented
        assert "y = 2" in augmented

    def test_no_at_mentions_unchanged(self, tmp_path: Path):
        from sage.cli.shell_chat import _inject_at_files

        line = "just a plain question"
        augmented, injected = _inject_at_files(line, tmp_path)
        assert augmented == line
        assert injected == []


# ── Context compression ───────────────────────────────────────────────────────

class TestCompressHistory:
    def test_short_history_unchanged(self):
        from sage.cli.shell_chat import _compress_history

        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _compress_history(msgs)
        assert len(result) == 3

    def test_large_history_trimmed(self):
        from sage.cli.shell_chat import _compress_history, _MAX_HISTORY_CHARS

        big = "x" * (_MAX_HISTORY_CHARS // 4)
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": big},
            {"role": "assistant", "content": big},
            {"role": "user", "content": big},
            {"role": "assistant", "content": big},
            {"role": "user", "content": "latest"},
        ]
        result = _compress_history(msgs)
        total = sum(len(str(m.get("content", ""))) for m in result)
        # System prompt always kept
        assert result[0]["role"] == "system"
        # Latest message preserved
        assert any(m["content"] == "latest" for m in result)
        assert total <= _MAX_HISTORY_CHARS + len("latest")

    def test_system_message_always_preserved(self):
        from sage.cli.shell_chat import _compress_history, _MAX_HISTORY_CHARS

        big = "a" * _MAX_HISTORY_CHARS
        msgs = [
            {"role": "system", "content": "SYSTEM_PROMPT"},
            {"role": "user", "content": big},
        ]
        result = _compress_history(msgs)
        assert result[0]["content"] == "SYSTEM_PROMPT"


# ── System prompt ─────────────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_contains_required_sections(self, tmp_path: Path, monkeypatch):
        from sage.cli import shell_chat

        monkeypatch.chdir(tmp_path)
        prompt = shell_chat._build_system_prompt()

        assert "WORKSPACE CONTEXT" in prompt
        assert "CAPABILITIES" in prompt
        assert "STYLE" in prompt
        assert "Markdown" in prompt

    def test_includes_cwd(self, tmp_path: Path, monkeypatch):
        from sage.cli import shell_chat

        monkeypatch.chdir(tmp_path)
        prompt = shell_chat._build_system_prompt()
        assert str(tmp_path) in prompt


# ── stream_chat in ollama_safe ────────────────────────────────────────────────

class TestStreamChat:
    def test_stream_chat_yields_chunks(self):
        from sage.llm.ollama_safe import stream_chat

        fake_chunk = MagicMock()
        fake_chunk.message.content = "hello "
        fake_chunk2 = MagicMock()
        fake_chunk2.message.content = "world"

        with patch("sage.llm.ollama_safe.ollama") as mock_ollama:
            mock_ollama.chat.return_value = iter([fake_chunk, fake_chunk2])
            chunks = list(stream_chat(model="m", messages=[{"role": "user", "content": "hi"}]))

        assert chunks == ["hello ", "world"]

    def test_stream_chat_raises_on_no_ollama(self):
        from sage.llm.ollama_safe import stream_chat

        with patch("sage.llm.ollama_safe.ollama", None):
            with pytest.raises(RuntimeError, match="not installed"):
                list(stream_chat(model="m", messages=[]))

    def test_stream_chat_handles_dict_chunks(self):
        from sage.llm.ollama_safe import stream_chat

        # Old ollama client returns dicts, not typed objects
        chunk1 = {"message": {"content": "foo"}}
        chunk2 = {"message": {"content": "bar"}}

        with patch("sage.llm.ollama_safe.ollama") as mock_ollama:
            def _side_effect(**kwargs):
                for c in [chunk1, chunk2]:
                    yield c
            mock_ollama.chat.side_effect = _side_effect
            chunks = list(stream_chat(model="m", messages=[{"role": "user", "content": "hi"}]))

        assert "foo" in chunks
        assert "bar" in chunks


# ── chat_ui rendering (non-rich path) ─────────────────────────────────────────

class TestChatUiNonRich:
    def test_print_assistant_block_plain(self, capsys):
        from sage.cli.chat_ui import print_assistant_block

        print_assistant_block(body="Hello **world**", use_rich=False, model="test-model")
        out = capsys.readouterr().out
        assert "Hello **world**" in out
        assert "SAGE" in out

    def test_stream_assistant_block_plain(self, capsys):
        from sage.cli.chat_ui import stream_assistant_block

        def chunks():
            yield "Hello "
            yield "world"

        result = stream_assistant_block(chunks=chunks(), use_rich=False, model="m")
        out = capsys.readouterr().out
        assert result == "Hello world"
        assert "Hello " in out or "Hello world" in out

    def test_print_user_line_plain(self, capsys):
        from sage.cli.chat_ui import print_user_line

        print_user_line(text="test message", use_rich=False)
        out = capsys.readouterr().out
        assert "test message" in out
        assert "You" in out

    def test_banner_plain(self, capsys):
        from sage.cli.chat_ui import print_chat_enter_banner

        print_chat_enter_banner(use_rich=False, session_id="abc123")
        out = capsys.readouterr().out
        assert "/back" in out
        assert "/clear" in out


# ── parse_chat_args ───────────────────────────────────────────────────────────

class TestParseChatArgs:
    def test_plain_chat(self):
        from sage.cli.shell_chat import parse_chat_args
        force_new, resume, msg = parse_chat_args(["chat"])
        assert force_new is False
        assert resume is False
        assert msg is None

    def test_chat_new(self):
        from sage.cli.shell_chat import parse_chat_args
        force_new, resume, msg = parse_chat_args(["chat", "new"])
        assert force_new is True
        assert resume is False

    def test_chat_resume(self):
        from sage.cli.shell_chat import parse_chat_args
        _, resume, _ = parse_chat_args(["chat", "resume"])
        assert resume is True

    def test_chat_with_initial_message(self):
        from sage.cli.shell_chat import parse_chat_args
        _, _, msg = parse_chat_args(["chat", "explain", "the", "code"])
        assert msg == "explain the code"

    def test_empty_parts(self):
        from sage.cli.shell_chat import parse_chat_args
        force_new, resume, msg = parse_chat_args([])
        assert force_new is False
        assert resume is False
        assert msg is None
