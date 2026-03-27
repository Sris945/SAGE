import subprocess
import unittest
from pathlib import Path


class TestPrepareReleaseScript(unittest.TestCase):
    def test_prepare_release_dry_run(self):
        script = Path("scripts/prepare_release.sh")
        self.assertTrue(script.exists())
        proc = subprocess.run(
            ["bash", str(script), "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertIn("release preflight passed", proc.stdout)


if __name__ == "__main__":
    unittest.main()
