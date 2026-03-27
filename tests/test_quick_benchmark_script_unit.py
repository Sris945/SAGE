import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestQuickBenchmarkScript(unittest.TestCase):
    def test_quick_benchmark_invokes_bench_and_reads_out(self):
        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "quick_bench.json"
            out_payload = {"status": "ok"}
            out_path.write_text(json.dumps(out_payload), encoding="utf-8")

            def fake_run(cmd, capture_output=True, text=True):  # noqa: ARG001
                # Do nothing: the script will read the pre-created out file.
                class R:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return R()

            with patch("subprocess.run", side_effect=fake_run):
                with patch(
                    "sys.argv",
                    [
                        "quick_benchmark.py",
                        "--out",
                        str(out_path),
                    ],
                ):
                    with patch("sys.stdout", new=io.StringIO()) as out:
                        runpy.run_path("scripts/quick_benchmark.py", run_name="__main__")
                        txt = out.getvalue()
                        self.assertIn("status=ok", txt)


if __name__ == "__main__":
    unittest.main()
