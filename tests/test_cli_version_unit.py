"""CLI exposes package version."""

import subprocess
import sys


def test_cli_version_flag():
    r = subprocess.run(
        [sys.executable, "-m", "sage.cli.main", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    out = (r.stdout or r.stderr).strip()
    assert out.startswith("sage ")
