import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class TestAgentInsightEmission(unittest.TestCase):
    def test_coder_emits_decision_and_observation_on_patch_ready(self):
        from sage.agents.coder import CoderAgent

        insight_sink = MagicMock()

        mock_bandit = MagicMock()
        mock_bandit.select.return_value = "coder:primary:conservative"

        with (
            patch("sage.agents.coder.get_global_bandit", return_value=mock_bandit),
            patch("sage.agents.coder.ollama", object()),
            patch(
                "sage.agents.coder.chat_with_timeout",
                return_value={
                    "message": {
                        "content": (
                            '{"file":"src/app.py","operation":"edit","patch":"print(1)",'
                            '"reason":"ok","epistemic_flags":[]}'
                        )
                    }
                },
            ),
        ):
            out = CoderAgent().run(
                task={"id": "task_1", "description": "do something"},
                memory={"foo": "bar"},
                mode="auto",
                failure_count=0,
                universal_prefix="",
                insight_sink=insight_sink,
            )

        self.assertEqual(out["status"], "patch_ready")

        emitted = [c.args[0] for c in insight_sink.ingest.call_args_list]
        self.assertTrue(any(e.agent == "coder" and e.insight_type == "decision" for e in emitted))
        self.assertTrue(
            any(
                e.agent == "coder"
                and e.insight_type == "observation"
                and "PatchRequest ready" in (e.content or "")
                for e in emitted
            )
        )

    def test_coder_emits_risk_if_ollama_unavailable(self):
        from sage.agents.coder import CoderAgent

        insight_sink = MagicMock()
        mock_bandit = MagicMock()
        mock_bandit.select.return_value = "coder:primary:conservative"

        # Ensure ollama is treated as unavailable in the module.
        with (
            patch("sage.agents.coder.get_global_bandit", return_value=mock_bandit),
            patch(
                "sage.agents.coder.ollama",
                None,
            ),
        ):
            out = CoderAgent().run(
                task={"id": "task_1", "description": "do something"},
                memory={"foo": "bar"},
                mode="auto",
                failure_count=0,
                universal_prefix="",
                insight_sink=insight_sink,
            )

        self.assertEqual(out["status"], "failed")
        emitted = [c.args[0] for c in insight_sink.ingest.call_args_list]
        self.assertTrue(
            any(
                e.agent == "coder"
                and e.insight_type == "risk"
                and e.requires_orchestrator_action is True
                for e in emitted
            )
        )

    def test_reviewer_emits_risk_on_fail_verdict(self):
        from sage.agents.reviewer import ReviewerAgent

        insight_sink = MagicMock()

        # Create a valid python file with >= 3 lines and no syntax error.
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("def x():\n")
                f.write("    return 1\n\n")
                f.write("# trailing comment\n")

            with (
                patch("sage.agents.reviewer.ollama", object()),
                patch(
                    "sage.agents.reviewer.chat_with_timeout",
                    return_value={
                        "message": {
                            "content": (
                                '{"verdict":"FAIL","score":0.9,'
                                '"issues":["bad"],"suggestion":"fix it"}'
                            )
                        }
                    },
                ),
            ):
                out = ReviewerAgent().run(
                    file=path,
                    task={"id": "task_2", "description": "review something"},
                    memory={},
                    failure_count=0,
                    universal_prefix="",
                    insight_sink=insight_sink,
                )

            self.assertFalse(out.passed)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

        emitted = [c.args[0] for c in insight_sink.ingest.call_args_list]
        self.assertTrue(any(e.agent == "reviewer" for e in emitted))
        self.assertTrue(
            any(
                e.agent == "reviewer"
                and e.insight_type == "risk"
                and e.requires_orchestrator_action is True
                for e in emitted
            )
        )


if __name__ == "__main__":
    unittest.main()
