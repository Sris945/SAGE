"""Golden trace: fixture validation + live ordering (MODEL_ROUTING → CONTEXT_CLAMPED → TOKEN_USAGE)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "golden_trace_minimal.jsonl"

EXPECTED_PREFIX = ["MODEL_ROUTING_DECISION", "CONTEXT_CLAMPED", "TOKEN_USAGE"]


def test_golden_fixture_parses_and_matches_expected_order():
    from sage.observability.trace_compare import load_event_types, ordered_prefix_matches

    types = load_event_types(FIXTURE)
    assert ordered_prefix_matches(types, EXPECTED_PREFIX)


def test_routing_then_clamp_then_token_order_with_mocked_ollama(monkeypatch):
    """
    With SAGE_MODEL_PROFILE=test and a tiny prompt cap, a select() call then
    chat_with_timeout() emits events in stable order (no real Ollama server).
    """
    monkeypatch.setenv("SAGE_MODEL_PROFILE", "test")
    monkeypatch.setenv("SAGE_MAX_PROMPT_CHARS_TOTAL", "80")

    events: list[str] = []

    def _capture(event_type: str, payload: dict | None = None, timestamp: str | None = None):
        events.append(event_type)

    with patch("sage.observability.structured_logger.log_event", side_effect=_capture):
        from sage.orchestrator.model_router import ModelRouter
        from sage.llm.ollama_safe import chat_with_timeout

        mr = ModelRouter()
        mr.select("planner", task_complexity_score=0.1, failure_count=0)

        fake = MagicMock()
        fake.chat.return_value = {
            "message": {"content": "ok"},
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
        with patch("sage.llm.ollama_safe.ollama", fake):
            chat_with_timeout(
                model="qwen2.5-coder:1.5b",
                messages=[
                    {"role": "system", "content": "s" * 200},
                    {"role": "user", "content": "u" * 200},
                ],
                timeout_s=5.0,
            )

    assert "MODEL_ROUTING_DECISION" in events
    idx_r = events.index("MODEL_ROUTING_DECISION")
    assert "CONTEXT_CLAMPED" in events
    idx_c = events.index("CONTEXT_CLAMPED")
    assert "TOKEN_USAGE" in events
    idx_t = events.index("TOKEN_USAGE")
    assert idx_r < idx_c < idx_t, f"bad order: {events}"


def test_trace_find_subsequence():
    from sage.observability.trace_compare import find_subsequence

    assert find_subsequence(["A", "B", "C", "D"], ["B", "C"]) == 1
    assert find_subsequence(["A", "A"], ["A", "A"]) == 0
    assert find_subsequence(["X"], ["Y"]) is None
