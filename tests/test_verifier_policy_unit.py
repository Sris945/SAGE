"""Verification commands use the same policy as tool execution."""

import pytest

from sage.execution.verifier import VerificationEngine, VerificationError


def test_verifier_blocks_denied_substring():
    with pytest.raises(VerificationError, match="Blocked"):
        VerificationEngine().run("sudo apt update")


def test_verifier_runs_safe_command(tmp_path):
    r = VerificationEngine().run("echo ok", cwd=str(tmp_path))
    assert r["passed"] is True
    assert "ok" in (r.get("stdout") or "")
