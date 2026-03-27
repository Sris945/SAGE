import unittest
from unittest.mock import patch


class TestHITLCheckpoints(unittest.TestCase):
    def test_safe_human_confirm_non_interactive_defaults(self):
        from sage.orchestrator.workflow import safe_human_confirm

        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as mocked_input:
            self.assertTrue(safe_human_confirm("Proceed?", default_yes=True))
            mocked_input.assert_not_called()

            self.assertFalse(safe_human_confirm("Proceed?", default_yes=False))
            mocked_input.assert_not_called()

    def test_human_checkpoint_1_post_scan_emits_log(self):
        from sage.orchestrator.workflow import human_checkpoint_1_post_scan

        state = {
            "mode": "research",
            "session_memory": {"codebase_brief": {"foo": "bar"}},
        }

        with (
            patch("sage.orchestrator.workflow.safe_human_confirm", return_value=True),
            patch("sage.observability.structured_logger.log_event") as log_event,
        ):
            human_checkpoint_1_post_scan(state)  # should not raise

            self.assertTrue(log_event.called)
            args, kwargs = log_event.call_args
            self.assertEqual(args[0], "HUMAN_CHECKPOINT_REACHED")
            self.assertEqual(kwargs["payload"]["checkpoint_type"], 1)

    def test_tool_executor_checkpoint4_destructive_emits_log_and_executes(self):
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
                "operation": "delete",
                "patch": "",
                "reason": "unit-test destructive",
            },
            "pending_patch_source": "coder",
            "pending_fix_pattern_context": {},
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
            patch("sage.orchestrator.workflow.safe_human_confirm", return_value=True),
            patch("sage.observability.structured_logger.log_event") as log_event,
            patch(
                "sage.execution.executor.ToolExecutionEngine.execute",
                return_value={"status": "ok", "file": "x.py"},
            ) as mock_execute,
        ):
            out = tool_executor(state)
            self.assertIn("task_dag", out)
            mock_execute.assert_called_once()

            payloads = [
                kwargs["payload"]
                for _, kwargs in log_event.call_args_list
                if kwargs and "payload" in kwargs
            ]
            self.assertTrue(any(p.get("checkpoint_type") == 4 for p in payloads))

    def test_tool_executor_checkpoint4_cancel_aborts(self):
        from sage.orchestrator.workflow import HumanCancelledError, tool_executor

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
                "operation": "run_command",
                "patch": "rm -f x.py",
                "reason": "unit-test destructive",
            },
            "pending_patch_source": "coder",
            "pending_fix_pattern_context": {},
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
            patch("sage.orchestrator.workflow.safe_human_confirm", return_value=False),
            patch("sage.observability.structured_logger.log_event") as log_event,
            patch(
                "sage.execution.executor.ToolExecutionEngine.execute",
                return_value={"status": "ok", "file": "x.py"},
            ) as mock_execute,
        ):
            with self.assertRaises(HumanCancelledError):
                tool_executor(state)

            mock_execute.assert_not_called()
            self.assertTrue(log_event.called)


if __name__ == "__main__":
    unittest.main()
