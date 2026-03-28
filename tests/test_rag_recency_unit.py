"""Smoke tests for recency-weighted retrieval (Feature 4) and conflict detection (Feature 5)."""

from __future__ import annotations

from datetime import date, timedelta

from sage.memory.rag_retriever import _recency_weight
from sage.cli.rules_cmd import _detect_conflicts


# ---------------------------------------------------------------------------
# _recency_weight tests
# ---------------------------------------------------------------------------


def test_recency_weight_today() -> None:
    today_str = date.today().isoformat()
    w = _recency_weight(today_str)
    assert abs(w - 1.0) < 1e-9, f"Expected ~1.0 for today, got {w}"


def test_recency_weight_30_days() -> None:
    thirty_ago = (date.today() - timedelta(days=30)).isoformat()
    w = _recency_weight(thirty_ago)
    # 1 / (1 + 30/30) = 0.5
    assert abs(w - 0.5) < 1e-9, f"Expected 0.5 for 30 days ago, got {w}"


def test_recency_weight_empty_string() -> None:
    w = _recency_weight("")
    assert w == 0.5, f"Expected 0.5 for empty string, got {w}"


def test_recency_weight_none_like() -> None:
    # None passed as string
    w = _recency_weight(None)  # type: ignore[arg-type]
    assert w == 0.5, f"Expected 0.5 for None-like, got {w}"


def test_recency_weight_invalid_date() -> None:
    w = _recency_weight("not-a-date")
    assert w == 0.5, f"Expected 0.5 for invalid date, got {w}"


def test_recency_weight_old_date_near_zero() -> None:
    old = (date.today() - timedelta(days=3650)).isoformat()  # ~10 years
    w = _recency_weight(old)
    assert w < 0.01, f"Expected near-zero for very old date, got {w}"


def test_recency_weight_decreases_with_age() -> None:
    today = date.today()
    w1 = _recency_weight(today.isoformat())
    w7 = _recency_weight((today - timedelta(days=7)).isoformat())
    w30 = _recency_weight((today - timedelta(days=30)).isoformat())
    assert w1 > w7 > w30


# ---------------------------------------------------------------------------
# _detect_conflicts tests
# ---------------------------------------------------------------------------


def test_detect_always_never_contradiction() -> None:
    rules = [
        "Always use ruff for linting",
        "Never use ruff in this project",
    ]
    conflicts = _detect_conflicts(rules)
    assert any("always" in c.lower() and "never" in c.lower() for c in conflicts), (
        f"Expected always/never conflict, got: {conflicts}"
    )


def test_detect_no_conflict_clean_rules() -> None:
    rules = [
        "Always run tests before merging",
        "Use black for code formatting",
        "Keep functions under 50 lines",
    ]
    conflicts = _detect_conflicts(rules)
    # These should produce no conflicts
    assert len(conflicts) == 0, f"Unexpected conflicts: {conflicts}"


def test_detect_duplicate_rules() -> None:
    rules = [
        "Always run tests before merging pull requests",
        "Always run tests before merging pull requests",
    ]
    conflicts = _detect_conflicts(rules)
    assert any("near-identical" in c or "CONFLICT" in c for c in conflicts), (
        f"Expected duplicate detection, got: {conflicts}"
    )


def test_detect_negation_pair_use() -> None:
    rules = [
        "Use httpx for HTTP requests",
        "Do not use httpx anywhere",
    ]
    conflicts = _detect_conflicts(rules)
    assert any("CONFLICT" in c for c in conflicts), (
        f"Expected negation conflict for 'use'/'do not use', got: {conflicts}"
    )


def test_detect_numeric_conflict() -> None:
    rules = [
        "timeout: 10",
        "timeout: 120",
    ]
    conflicts = _detect_conflicts(rules)
    assert any("timeout" in c for c in conflicts), (
        f"Expected numeric conflict for timeout, got: {conflicts}"
    )


def test_detect_no_numeric_conflict_same_value() -> None:
    rules = [
        "retries: 3",
        "retries: 3",
    ]
    # Same value — no numeric conflict (might flag as duplicate though)
    conflicts = _detect_conflicts(rules)
    numeric_conflicts = [
        c for c in conflicts if "incompatible" in c.lower() and "retries" in c.lower()
    ]
    assert len(numeric_conflicts) == 0, f"Same numeric value should not be a conflict: {conflicts}"


def test_detect_empty_rules() -> None:
    assert _detect_conflicts([]) == []


def test_detect_single_rule() -> None:
    assert _detect_conflicts(["Always use ruff"]) == []
