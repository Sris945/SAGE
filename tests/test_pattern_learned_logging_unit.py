import unittest
from unittest.mock import patch


class TestPatternLearnedLogging(unittest.TestCase):
    def test_tool_executor_emits_pattern_learned_on_successful_save(self):
        from sage.orchestrator.workflow import tool_executor

        task_dag = {
            "nodes": [
                {
                    "id": "task_001",
                    "description": "test",
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

        state = {
            "mode": "research",
            "task_dag": task_dag,
            "current_task_id": "task_001",
            "pending_patch_request": {
                "file": "x.py",
                "operation": "edit",
                "patch": "print('hi')",
                "reason": "unit-test",
                "epistemic_flags": [],
            },
            "pending_patch_source": "coder",
            "pending_fix_pattern_context": {
                "error_signature": "errsig",
                "suspected_cause": "cause",
                "fix_operation": "edit",
                "fix_file": "x.py",
                "fix_patch": "print('hi')",
                "success_rate": 1.0,
                "times_applied": 1,
                "last_used": "2026-01-01",
                "source": "test",
            },
            "artifacts_by_task": {},
            "execution_result": {},
            "last_error": "",
            "verification_needs_tool_apply": False,
            "fix_pattern_hit": False,
            "fix_pattern_applied": False,
            "max_retries": 3,
            "debug_attempts": 0,
            "session_memory": {},
            "architect_blueprints_by_task": {},
            "human_checkpoint_done": False,
            "task_updates": [],
            "events": [],
            "current_task": {},
            "agent_output": {},
            "orchestrator_escalation": False,
            "resume_from_handoff": False,
        }

        with (
            patch(
                "sage.execution.executor.ToolExecutionEngine.execute",
                return_value={"status": "ok", "file": "x.py"},
            ),
            patch("sage.memory.manager.MemoryManager.save_fix_pattern") as save_fix_pattern,
            patch("sage.observability.structured_logger.log_event") as log_event,
        ):
            _ = tool_executor(state)

            self.assertTrue(save_fix_pattern.called)

            # Must emit PATTERN_LEARNED after a successful save.
            found = False
            for call in log_event.call_args_list:
                args, kwargs = call
                if args and args[0] == "PATTERN_LEARNED":
                    found = True
                    payload = kwargs.get("payload", {})
                    self.assertEqual(payload.get("task_id"), "task_001")
                    self.assertEqual(payload.get("error_signature"), "errsig")
                    self.assertEqual(payload.get("fix_file"), "x.py")
                    self.assertEqual(payload.get("fix_operation"), "edit")
            self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
