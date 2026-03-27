"""Real subprocess CLI invocations (no LLM)."""

import json
import subprocess
import sys


def test_cli_prep_json_returns_json():
    r = subprocess.run(
        [sys.executable, "-m", "sage.cli.main", "prep", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "hardware" in data or "suggestion" in data


def test_cli_doctor_json_returns_json():
    r = subprocess.run(
        [sys.executable, "-m", "sage.cli.main", "doctor", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "python" in data


def test_cli_permissions_json_returns_json():
    r = subprocess.run(
        [sys.executable, "-m", "sage.cli.main", "permissions", "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "workspace_roots" in data
