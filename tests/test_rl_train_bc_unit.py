import json
import tempfile
import unittest
from pathlib import Path

from sage.rl.schema import ROUTING_SCHEMA_VERSION
from sage.rl.train_bc import train_bc_joblib


class TestTrainBC(unittest.TestCase):
    def test_train_bc_joblib_smoke(self):
        rows = []
        for i in range(24):
            rows.append(
                {
                    "schema_version": ROUTING_SCHEMA_VERSION,
                    "agent_role": "planner",
                    "task_complexity_score": (i % 10) / 10.0,
                    "primary_failure_count": i % 3,
                    "action_fallback": i % 2,
                }
            )
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "d.jsonl"
            with data.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            out = Path(d) / "policy_bc.joblib"
            report = train_bc_joblib(data, out)
            self.assertIn("planner", report.get("roles_trained", []))
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
