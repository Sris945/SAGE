import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestBenchArtifactsCLI(unittest.TestCase):
    def test_bench_writes_out_artifact(self):
        import sage.cli.main as cli

        fake_results = {"status": "ok", "benchmarks": []}
        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "bench.json"

            with patch("sage.benchmarks.runner.run_benchmarks", return_value=fake_results):
                with patch("sys.argv", ["sage", "bench", "--out", str(out_path)]):
                    cli.main()

            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "ok")
            self.assertIn("benchmarks", payload)

    def test_bench_compare_policy_writes_out_artifact(self):
        import sage.cli.main as cli

        fake_results = {
            "status": "ok",
            "compare_mode": True,
            "compare": {"summary": {}},
            "benchmarks": [],
        }
        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "bench_compare.json"

            with patch("sage.benchmarks.runner.run_benchmarks", return_value=fake_results):
                with patch(
                    "sys.argv", ["sage", "bench", "--compare-policy", "--out", str(out_path)]
                ):
                    cli.main()

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(payload.get("compare_mode", False))

    def test_bench_run_pack_writes_manifest_and_result(self):
        import sage.cli.main as cli

        fake_results = {"status": "ok", "compare_mode": False, "benchmarks": [{"name": "x"}]}
        with tempfile.TemporaryDirectory() as d:
            pack_dir = Path(d) / "pack"
            with patch("sage.benchmarks.runner.run_benchmarks", return_value=fake_results):
                with patch("sys.argv", ["sage", "bench", "--run-pack-dir", str(pack_dir)]):
                    cli.main()

            result_file = pack_dir / "bench_result.json"
            manifest_file = pack_dir / "manifest.json"
            self.assertTrue(result_file.exists())
            self.assertTrue(manifest_file.exists())

            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("schema_version"), "bench_run_pack_v1")
            self.assertEqual(manifest.get("summary", {}).get("status"), "ok")
            self.assertEqual(manifest.get("summary", {}).get("benchmark_count"), 1)


if __name__ == "__main__":
    unittest.main()
