"""Real Ollama HTTP chat (minimal; requires pulled model)."""

import subprocess

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.ollama]


def _ollama_ok() -> bool:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, timeout=8, text=True)
        return r.returncode == 0
    except Exception:
        return False


def test_chat_with_timeout_real_roundtrip(monkeypatch):
    if not _ollama_ok():
        pytest.skip("ollama not available")

    monkeypatch.setenv("SAGE_MODEL_PROFILE", "test")

    from sage.llm.ollama_safe import chat_with_timeout

    resp = chat_with_timeout(
        model="qwen2.5-coder:1.5b",
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        timeout_s=60.0,
    )
    assert isinstance(resp, dict)
    assert "message" in resp
    content = (resp.get("message") or {}).get("content") or ""
    assert len(content) > 0
