"""OrchestratorIntelligenceFeed: unclear threshold + intervention records."""

from __future__ import annotations

from sage.orchestrator.intelligence_feed import OrchestratorIntelligenceFeed
from sage.protocol.schemas import AgentInsight


def test_unclear_threshold_escalates_once_per_task() -> None:
    feed = OrchestratorIntelligenceFeed(uncertainty_count=3)
    base = dict(
        agent="planner",
        task_id="t1",
        insight_type="uncertainty",
        content="?",
        severity="low",
        epistemic_flag="",
    )
    for i in range(3):
        feed.ingest(AgentInsight(**{**base, "content": f"q{i}"}))
    assert feed.should_escalate("t1")
    assert any(it.get("insight_type") == "unclear_threshold" for it in feed.interventions)
    n_interventions = len(feed.interventions)
    feed.ingest(AgentInsight(**{**base, "content": "extra"}))
    assert len(feed.interventions) == n_interventions
