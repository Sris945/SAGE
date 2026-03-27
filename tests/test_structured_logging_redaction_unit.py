"""Structured JSON logs redact obvious secrets."""

from unittest.mock import patch


def test_log_event_redacts_api_like_strings():
    from sage.observability.structured_logger import log_event

    captured: list[str] = []

    def fake_append(line: str) -> None:
        captured.append(line)

    with patch("sage.observability.structured_logger.MemoryManager") as mm:
        mm.return_value.append_session_log.side_effect = fake_append
        log_event(
            "TEST",
            payload={"note": "token sk-abcdefghijklmnopqrstuvwxyz0123456789 here"},
        )

    assert captured, "expected one log line"
    line = captured[0]
    assert "[REDACTED]" in line
