"""Clarification gate (planner Q&A) policy."""

from __future__ import annotations

from sage.cli.clarify import should_offer_clarification


def test_should_offer_clarification_silent_never():
    assert not should_offer_clarification(mode="silent", clarify_flag=True, no_clarify_env=False)


def test_should_offer_respects_flags():
    assert should_offer_clarification(mode="auto", clarify_flag=True, no_clarify_env=False)
    assert not should_offer_clarification(mode="auto", clarify_flag=False, no_clarify_env=False)
    assert not should_offer_clarification(mode="research", clarify_flag=True, no_clarify_env=True)
