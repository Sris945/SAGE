"""Session journal rotation when SAGE_SESSION_LOG_MAX_MB is set."""

from pathlib import Path


def test_append_session_log_rotates_when_over_max(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # ~10 byte cap
    monkeypatch.setenv("SAGE_SESSION_LOG_MAX_MB", "0.00001")

    from sage.memory.manager import MemoryManager

    mm = MemoryManager()
    mm.append_session_log("x" * 30)
    mm.append_session_log("y")

    sessions = Path("memory/sessions")
    assert sessions.is_dir()
    logs = sorted(sessions.glob("*.log"))
    assert len(logs) >= 2
