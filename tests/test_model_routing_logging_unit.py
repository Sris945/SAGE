import unittest
from unittest.mock import patch


class TestModelRoutingLogging(unittest.TestCase):
    def test_model_router_logs_routing_decision(self):
        from sage.orchestrator.model_router import ModelRouter

        with patch("sage.observability.structured_logger.log_event") as log_event:
            mr = ModelRouter()
            # For debugger: failure_count >= 2 triggers fallback via YAML.
            _ = mr.select("debugger", task_complexity_score=0.1, failure_count=2)

            self.assertTrue(log_event.called)
            # Find our routing decision call.
            routing_calls = [
                c
                for c in log_event.call_args_list
                if c.args and c.args[0] == "MODEL_ROUTING_DECISION"
            ]
            self.assertTrue(len(routing_calls) >= 1)

            _call = routing_calls[-1]
            payload = _call.kwargs.get("payload", {})
            self.assertEqual(payload.get("agent_role"), "debugger")
            self.assertEqual(payload.get("primary_failure_count"), 2)
            self.assertIn("selected_model", payload)
            self.assertIn("matched_fallback_triggers", payload)
            self.assertEqual(payload.get("policy_source"), "yaml")

    def test_model_router_logs_policy_error_and_falls_back_yaml(self):
        from sage.orchestrator.model_router import ModelRouter

        with patch.dict("os.environ", {"SAGE_RL_POLICY": "1"}, clear=False):
            with patch("sage.rl.policy.get_routing_policy", side_effect=RuntimeError("boom")):
                with patch("sage.observability.structured_logger.log_event") as log_event:
                    mr = ModelRouter()
                    _ = mr.select("coder", task_complexity_score=0.1, failure_count=0)

                    event_names = [c.args[0] for c in log_event.call_args_list if c.args]
                    self.assertIn("ROUTING_POLICY_ERROR", event_names)
                    self.assertIn("MODEL_ROUTING_DECISION", event_names)


if __name__ == "__main__":
    unittest.main()
