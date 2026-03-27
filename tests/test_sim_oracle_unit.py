import unittest

from sage.sim.oracle_tasks import generate_oracle_tasks, write_tasks_jsonl
from sage.sim.parallel_runner import run_generated_suite


class TestSimOracle(unittest.TestCase):
    def test_generate_1000(self):
        tasks = generate_oracle_tasks(1000, seed=1)
        self.assertEqual(len(tasks), 1000)
        self.assertEqual(tasks[0]["id"], "oracle_00000")

    def test_parallel_smoke(self):
        r = run_generated_suite(count=8, workers=1, seed=2)
        self.assertEqual(r["total"], 8)
        self.assertEqual(r["passed"], 8)

    def test_write_jsonl(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            meta = write_tasks_jsonl(p, count=10, seed=3)
            self.assertEqual(meta["count"], 10)
            self.assertTrue(p.exists())


if __name__ == "__main__":
    unittest.main()
