import tempfile
import unittest
from pathlib import Path


class TestDeltaMerging(unittest.TestCase):
    def test_merge_task_updates_applies_task_status_artifacts_and_blueprints(self):
        from sage.orchestrator.task_graph import TaskGraph
        from sage.orchestrator.workflow import merge_task_updates
        from sage.protocol.schemas import TaskNode

        tg = TaskGraph()
        tg.add_node(
            TaskNode(
                id="task1",
                description="d1",
                dependencies=[],
                assigned_agent="coder",
                status="pending",
                retry_count=0,
                model_used="",
                verification="",
                epistemic_flags=[],
            )
        )

        updated_node = TaskNode(
            id="task1",
            description="d1",
            dependencies=[],
            assigned_agent="coder",
            status="completed",
            retry_count=1,
            model_used="m",
            verification="python -c 'print(1)'",
            epistemic_flags=["[UNVERIFIED]"],
        )

        state = {
            "task_dag": tg.to_dict(),
            "artifacts_by_task": {"task1": "src/app_old.py"},
            "architect_blueprints_by_task": {"task1": {"old": True}},
            "task_updates": [
                {
                    "task_id": "task1",
                    "task_node": vars(updated_node),
                    "artifact_file": "src/app_new.py",
                    "architect_blueprint": {"new": True},
                    "last_error": "",
                }
            ],
            "last_error": "",
        }

        out = merge_task_updates(state)  # direct call (unit test)

        nodes = out["task_dag"]["nodes"]
        task1 = next(n for n in nodes if n["id"] == "task1")
        self.assertEqual(task1["status"], "completed")
        self.assertEqual(out["artifacts_by_task"]["task1"], "src/app_new.py")
        self.assertEqual(out["architect_blueprints_by_task"]["task1"], {"new": True})


class TestFileLocks(unittest.TestCase):
    def test_tool_execution_engine_returns_blocked_when_file_lock_busy(self):
        from sage.execution.executor import ToolExecutionEngine
        from sage.execution import executor as executor_mod
        from sage.protocol.schemas import PatchRequest

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "lock_target.txt"

            # Speed up the test.
            old_timeout = ToolExecutionEngine.LOCK_TIMEOUT_SECONDS
            ToolExecutionEngine.LOCK_TIMEOUT_SECONDS = 0.05

            try:
                lock = executor_mod._get_lock_for_path(p)
                acquired = lock.acquire(timeout=1.0)
                self.assertTrue(acquired)

                engine = ToolExecutionEngine(workspace_roots=[Path(tmp)])
                req = PatchRequest(
                    file=str(p),
                    operation="edit",
                    patch="hello",
                    reason="unit test",
                    epistemic_flags=[],
                )

                result = engine.execute(req)
                self.assertEqual(result.get("status"), "blocked")
                self.assertIn("reason", result)
            finally:
                try:
                    lock.release()
                except Exception:
                    pass
                ToolExecutionEngine.LOCK_TIMEOUT_SECONDS = old_timeout


class TestArchitectBlueprintIsolation(unittest.TestCase):
    def test_merge_does_not_overwrite_other_task_blueprints(self):
        from sage.orchestrator.task_graph import TaskGraph
        from sage.orchestrator.workflow import merge_task_updates
        from sage.protocol.schemas import TaskNode

        tg = TaskGraph()
        tg.add_node(
            TaskNode(
                id="taskA",
                description="a",
                dependencies=[],
                assigned_agent="architect",
                status="completed",
                retry_count=0,
                model_used="",
                verification="",
                epistemic_flags=[],
            )
        )
        tg.add_node(
            TaskNode(
                id="taskB",
                description="b",
                dependencies=[],
                assigned_agent="architect",
                status="pending",
                retry_count=0,
                model_used="",
                verification="",
                epistemic_flags=[],
            )
        )

        state = {
            "task_dag": tg.to_dict(),
            "artifacts_by_task": {},
            "architect_blueprints_by_task": {"taskA": {"keep": True}},
            "task_updates": [
                {
                    "task_id": "taskB",
                    "task_node": vars(
                        TaskNode(
                            id="taskB",
                            description="b",
                            dependencies=[],
                            assigned_agent="architect",
                            status="completed",
                            retry_count=1,
                            model_used="m",
                            verification="",
                            epistemic_flags=[],
                        )
                    ),
                    "artifact_file": "",
                    "architect_blueprint": {"set": True},
                    "last_error": "",
                }
            ],
            "last_error": "",
        }

        out = merge_task_updates(state)
        self.assertEqual(out["architect_blueprints_by_task"]["taskA"], {"keep": True})
        self.assertEqual(out["architect_blueprints_by_task"]["taskB"], {"set": True})


if __name__ == "__main__":
    unittest.main()
