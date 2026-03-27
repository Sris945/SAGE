import unittest


class TestAgentInsightInjection(unittest.TestCase):
    def test_low_severity_insight_is_included_in_injected_context(self):
        from sage.orchestrator.intelligence_feed import OrchestratorIntelligenceFeed
        from sage.protocol.schemas import AgentInsight

        feed = OrchestratorIntelligenceFeed()
        feed.insights = []
        feed.interventions = []

        feed.ingest(
            AgentInsight(
                agent="coder",
                task_id="t1",
                insight_type="observation",
                content="this is a low severity note",
                severity="low",
                epistemic_flag="",
                timestamp="",
                requires_orchestrator_action=False,
            )
        )

        ctx = feed.get_injected_context("t1")
        self.assertIn("ORCHESTRATOR_NOTE", ctx)
        self.assertIn("this is a low severity note", ctx)


if __name__ == "__main__":
    unittest.main()
