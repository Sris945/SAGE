"""Verification commands use the same policy as tool execution."""

import sys

import pytest

from sage.execution.verifier import VerificationEngine, VerificationError


def test_verifier_blocks_denied_substring():
    with pytest.raises(VerificationError, match="Blocked"):
        VerificationEngine().run("sudo apt update")


def test_verifier_runs_safe_command(tmp_path):
    r = VerificationEngine().run("echo ok", cwd=str(tmp_path))
    assert r["passed"] is True
    assert "ok" in (r.get("stdout") or "")


def test_verifier_chained_commands(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 42\n", encoding="utf-8")
    cmd = (
        "python -m py_compile src/app.py && python -c "
        "\"import sys; sys.path.insert(0, 'src'); import app; assert app.x == 42\""
    )
    r = VerificationEngine().run(cmd, cwd=str(tmp_path))
    assert r["passed"] is True


def test_verifier_pytest_gets_src_on_path(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import sys\nsys.path.insert(0, 'src')\nimport app\n\ndef test_f():\n    assert app.f() == 1\n",
        encoding="utf-8",
    )
    r = VerificationEngine().run(
        f"{sys.executable} -m pytest tests/test_x.py -q", cwd=str(tmp_path)
    )
    assert r["passed"] is True
