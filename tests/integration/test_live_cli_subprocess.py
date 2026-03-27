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
    assert data.get("tool_policy_source") in ("env", "file", "default")
    assert "policy_file" in data


def test_cli_permissions_set_policy_writes_file(tmp_path):
    (tmp_path / ".sage").mkdir()
    r1 = subprocess.run(
        [sys.executable, "-m", "sage.cli.main", "permissions", "set", "policy", "strict"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r1.returncode == 0, r1.stderr + r1.stdout
    policy = tmp_path / ".sage" / "policy.json"
    assert policy.is_file()
    saved = json.loads(policy.read_text(encoding="utf-8"))
    assert saved.get("tool_policy") == "strict"
    r2 = subprocess.run(
        [sys.executable, "-m", "sage.cli.main", "permissions", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r2.returncode == 0, r2.stderr
    data = json.loads(r2.stdout)
    assert data["tool_policy"] == "strict"
    assert data.get("tool_policy_source") == "file"
