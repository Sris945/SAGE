import unittest
from unittest.mock import patch


class TestAgentInsightLogging(unittest.TestCase):
    def test_ingest_logs_every_agent_insight_packet(self):
        from sage.orchestrator.intelligence_feed import OrchestratorIntelligenceFeed
        from sage.protocol.schemas import AgentInsight

        feed = OrchestratorIntelligenceFeed()

        with patch("sage.observability.structured_logger.log_event") as log_event:
            feed.ingest(
                AgentInsight(
                    agent="coder",
                    task_id="t1",
                    insight_type="observation",
                    content="hello world",
                    severity="low",
                    epistemic_flag="",
                    timestamp="",
                    requires_orchestrator_action=False,
                )
            )
            feed.ingest(
                AgentInsight(
                    agent="coder",
                    task_id="t1",
                    insight_type="risk",
                    content="something went wrong",
                    severity="high",
                    epistemic_flag="parsed:unknown",
                    timestamp="",
                    requires_orchestrator_action=True,
                )
            )

            self.assertEqual(log_event.call_count, 3)

            first_call = log_event.call_args_list[0]
            second_call = log_event.call_args_list[1]
            third_call = log_event.call_args_list[2]

            self.assertEqual(first_call.args[0], "AGENT_INSIGHT_EMITTED")
            self.assertEqual(second_call.args[0], "AGENT_INSIGHT_EMITTED")
            self.assertEqual(third_call.args[0], "ORCHESTRATOR_INTERVENTION")

            first_payload = first_call.kwargs["payload"]
            second_payload = second_call.kwargs["payload"]

            self.assertEqual(first_payload["task_id"], "t1")
            self.assertEqual(first_payload["agent"], "coder")
            self.assertEqual(first_payload["insight_type"], "observation")
            self.assertEqual(first_payload["severity"], "low")
            self.assertFalse(first_payload["requires_orchestrator_action"])
            self.assertIn("content_preview", first_payload)

            self.assertEqual(second_payload["insight_type"], "risk")
            self.assertEqual(second_payload["severity"], "high")
            self.assertTrue(second_payload["requires_orchestrator_action"])
            self.assertEqual(second_payload["epistemic_flag"], "parsed:unknown")


if __name__ == "__main__":
    unittest.main()
