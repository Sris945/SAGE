import unittest
from unittest.mock import patch


class TestFixPatternMissInstrumentation(unittest.TestCase):
    def _base_state(self) -> dict:
        task_dag = {
            "nodes": [
                {
                    "id": "task_001",
                    "description": "test task",
                    "dependencies": [],
                    "assigned_agent": "coder",
                    "status": "running",
                    "retry_count": 0,
                    "model_used": "",
                    "strategy_key": "",
                    "verification": "",
                    "epistemic_flags": [],
                }
            ]
        }
        return {
            "task_dag": task_dag,
            "current_task_id": "task_001",
            "last_error": "some error text for hashing",
            "execution_result": {},
        }

    def test_check_fix_patterns_emits_miss_when_no_pattern(self):
        from sage.orchestrator.workflow import check_fix_patterns

        state = self._base_state()
        with (
            patch("sage.memory.manager.MemoryManager") as mock_mm,
            patch("sage.observability.structured_logger.log_event") as log_event,
        ):
            mock_mm.return_value.find_fix_pattern.return_value = None

            out = check_fix_patterns(state)

            self.assertFalse(out["fix_pattern_hit"])
            self.assertFalse(out["fix_pattern_applied"])
            self.assertTrue(log_event.called)
            args, kwargs = log_event.call_args
            self.assertEqual(args[0], "FIX_PATTERN_MISS")
            self.assertEqual(kwargs["payload"]["task_id"], "task_001")
            self.assertEqual(kwargs["payload"]["reason"], "no_pattern_match")
            self.assertIn("error_signature", kwargs["payload"])

    def test_check_fix_patterns_emits_miss_when_pattern_has_no_patch(self):
        from sage.orchestrator.workflow import check_fix_patterns

        state = self._base_state()
        with (
            patch("sage.memory.manager.MemoryManager") as mock_mm,
            patch("sage.observability.structured_logger.log_event") as log_event,
        ):
            mock_mm.return_value.find_fix_pattern.return_value = {
                "fix_file": "x.py",
                "fix_operation": "edit|something_else",
                "fix_patch": None,  # falsy => triggers the miss path
            }

            out = check_fix_patterns(state)

            self.assertTrue(out["fix_pattern_hit"])
            self.assertFalse(out["fix_pattern_applied"])
            self.assertTrue(log_event.called)
            args, kwargs = log_event.call_args
            self.assertEqual(args[0], "FIX_PATTERN_MISS")
            self.assertEqual(kwargs["payload"]["task_id"], "task_001")
            self.assertEqual(kwargs["payload"]["reason"], "pattern_missing_fix_patch")
            self.assertEqual(kwargs["payload"]["fix_file"], "x.py")
            # ensure we normalize fix_operation before emitting
            self.assertEqual(kwargs["payload"]["fix_operation"], "edit")


if __name__ == "__main__":
    unittest.main()
