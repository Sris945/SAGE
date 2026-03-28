"""
SAGE Verification Engine
------------------------
Runs the verification command from a TaskNode after CoderAgent writes a file.
Feeds real stdout/stderr back into the retry loop.

Verification commands come from the planner's `verification` field, e.g.:
  "python -c 'import app'"
  "pytest tests/test_app.py -q"
  "python app.py --help"

Multiple checks: join with `` && `` (space-ampersand-space); each fragment runs
sequentially with ``shell=False`` (no real shell — we split and run in-process).

Workspace: if ``<cwd>/src`` exists, ``PYTHONPATH`` is prefixed with that path so
``import app`` works for ``src/app.py`` layouts (matches Claude-style greenfield).

Safety: ``check_run_command_policy`` (same rules as ``run_command``). Never shell=True.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from sage.cli.run_output import humanize_verify_command, run_output_level
from sage.execution.exceptions import SafetyViolation
from sage.execution.tool_policy import check_run_command_policy, parse_command_argv


def _max_verify_seconds() -> float | None:
    """
    Per-check subprocess timeout for planner verification commands.

    **Unset or empty** → no timeout (slow disks / CI with long suites — set explicitly if you
    need a cap). ``SAGE_VERIFY_TIMEOUT_S=0`` or negative → unlimited. Positive → seconds.
    """
    raw = (os.environ.get("SAGE_VERIFY_TIMEOUT_S") or "").strip()
    if raw == "":
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


def _rewrite_py_compile_off_requirements_manifest(cmd: str) -> str | None:
    """
    Planners sometimes emit ``python -m py_compile path/requirements.txt``, which makes
    Python parse pip pins as source and fail with SyntaxError. Replace with a pathlib check.
    """
    c = (cmd or "").strip()
    if "py_compile" not in c:
        return None
    low = c.lower()
    if "requirements" not in low and not any(
        x in low for x in ("constraints.txt", "constraints", "pipfile.lock")
    ):
        return None
    try:
        parts = shlex.split(c)
    except ValueError:
        return None
    for p in parts:
        if str(p).lower().endswith("requirements.txt"):
            return (
                'python -c "from pathlib import Path; '
                "c=[Path('requirements.txt'),Path('src/requirements.txt')]; "
                "ok=next((x for x in c if x.is_file() and x.read_text(errors='ignore').strip()), None); "
                "assert ok is not None, 'missing or empty requirements.txt'\""
            )
    return None


def normalize_verification_command_line(command: str) -> str:
    """
    Fix common planner/LLM mistakes before ``subprocess.run`` (no shell).

    Models sometimes emit ``py_compile`` as argv0; the real entrypoint is
    ``python -m py_compile``.
    """
    cmd = (command or "").strip()
    if not cmd:
        return cmd
    rewritten = _rewrite_py_compile_off_requirements_manifest(cmd)
    if rewritten:
        return rewritten
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    if not parts:
        return cmd
    if parts[0] == "py_compile":
        rest = parts[1:]
        fixed = ["python", "-m", "py_compile", *rest]
        return " ".join(shlex.quote(x) for x in fixed)
    return cmd


_CHAIN_SEP = " && "


def _verify_log_level() -> str:
    return run_output_level()


def _verify_print_running(command: str) -> None:
    lvl = _verify_log_level()
    if lvl == "debug":
        print(f"[Verify] Running: {command}")
    elif lvl == "full":
        print(f"[Verify] {humanize_verify_command(command)}")


def _verify_print_pass(rc: int, *, chained: bool = False, n_chunks: int = 0) -> None:
    lvl = _verify_log_level()
    if lvl == "debug":
        if chained and n_chunks > 1:
            print(f"[Verify] ✓ passed ({n_chunks} chained checks, rc={rc})")
        else:
            print(f"[Verify] ✓ passed (rc={rc})")
    elif lvl == "full":
        if chained and n_chunks > 1:
            print(f"[Verify] ✓ all {n_chunks} checks passed (rc={rc})")
        else:
            print(f"[Verify] ✓ ok (rc={rc})")


def _verify_print_fail(rc: int, stderr: str | None) -> None:
    print(f"[Verify] ✗ failed (rc={rc})")
    if stderr:
        print(f"[Verify] stderr: {stderr[:300]}")


class VerificationError(Exception):
    pass


def _verification_environ(cwd: Path) -> dict[str, str]:
    """Prefix PYTHONPATH with ./src when present so pytest/imports resolve."""
    env = os.environ.copy()
    src = cwd / "src"
    if src.is_dir():
        extra = str(src.resolve())
        prev = env.get("PYTHONPATH", "").strip()
        if prev:
            env["PYTHONPATH"] = f"{extra}{os.pathsep}{prev}"
        else:
            env["PYTHONPATH"] = extra
    return env


class VerificationEngine:
    def check_importable(self, file_path: str, cwd: str = ".") -> dict:
        """Phase 0: Check the Python file can be imported without errors."""
        fp = Path(file_path)
        if not fp.exists():
            return {"passed": False, "error": f"File not found: {file_path}"}
        # Convert file path to module name: strip .py, replace path separators
        try:
            rel = fp.with_suffix("")
            module = str(rel).replace("/", ".").replace("\\", ".").lstrip(".")
        except Exception as e:
            return {"passed": False, "error": f"Could not determine module name: {e}"}
        try:
            result = subprocess.run(
                [
                    "python",
                    "-c",
                    f"import sys; sys.path.insert(0, '{cwd}'); import {module}",
                ],
                timeout=8,
                capture_output=True,
                text=True,
                shell=False,
                cwd=str(cwd),
            )
            if result.returncode == 0:
                return {"passed": True, "error": None}
            return {
                "passed": False,
                "error": (result.stderr or result.stdout or "import failed").strip(),
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "error": f"Import check timed out after 8s for {module}"}
        except FileNotFoundError:
            return {"passed": False, "error": "python interpreter not found"}

    def check_ruff(self, file_path: str) -> dict:
        """Phase 0b: Run ruff on the file. Returns {passed, issues: [str]}."""
        try:
            result = subprocess.run(
                ["ruff", "check", file_path, "--output-format", "text", "--quiet"],
                timeout=15,
                capture_output=True,
                text=True,
                shell=False,
            )
            raw_output = (result.stdout or "").strip()
            issues = [line for line in raw_output.splitlines() if line.strip()]
            passed = result.returncode == 0
            return {"passed": passed, "issues": issues, "error_count": len(issues)}
        except FileNotFoundError:
            return {
                "passed": True,
                "issues": ["[ruff not installed — skipped]"],
                "error_count": 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": True,
                "issues": ["[ruff timed out after 15s — skipped]"],
                "error_count": 0,
            }

    def run(self, command: str, cwd: str | None = None) -> dict:
        """
        Run a verification command (or chained commands separated by `` && ``).

        Returns:
          {
            "passed": bool,
            "stdout": str,
            "stderr": str,
            "returncode": int,
            "command": str,
            "import_checked": bool,
            "ruff_issues": list[str],
          }
        """
        if not command or not command.strip():
            return {
                "passed": True,
                "stdout": "",
                "stderr": "",
                "returncode": 0,
                "command": command,
                "import_checked": False,
                "ruff_issues": [],
            }

        root = Path(cwd or Path.cwd()).resolve()
        import_checked = False
        ruff_issues: list[str] = []

        # Phase 0: import pre-check for Python files.
        # Skip for chained commands (&&) — the individual steps may not be
        # importable standalone and we'd falsely abort before running any step.
        cmd_stripped = command.strip()
        candidate_file: str | None = None
        if _CHAIN_SEP in cmd_stripped:
            pass  # chained command — skip import pre-check
        elif cmd_stripped.endswith(".py"):
            candidate_file = cmd_stripped
        elif cmd_stripped.startswith("python"):
            parts = cmd_stripped.split()
            # Look for a .py argument (not a flag)
            for part in parts[1:]:
                if part.endswith(".py") and not part.startswith("-"):
                    candidate_file = part
                    break

        if candidate_file:
            fp = Path(candidate_file)
            if not fp.is_absolute():
                fp = root / candidate_file
            if fp.exists():
                import_checked = True
                import_result = self.check_importable(str(fp), cwd=str(root))
                if not import_result["passed"]:
                    err_msg = import_result.get("error") or "import pre-check failed"
                    return {
                        "passed": False,
                        "stdout": "",
                        "stderr": f"[import pre-check] {err_msg}",
                        "returncode": 1,
                        "command": command,
                        "import_checked": True,
                        "ruff_issues": [],
                    }
                # Also run ruff while we have the file
                ruff_result = self.check_ruff(str(fp))
                ruff_issues = ruff_result.get("issues") or []

        chunks = [
            normalize_verification_command_line(c.strip())
            for c in command.split(_CHAIN_SEP)
            if c.strip()
        ]
        if len(chunks) == 1:
            result = self._run_one(chunks[0], root)
            result["import_checked"] = import_checked
            result["ruff_issues"] = ruff_issues
            return result

        out_stdout: list[str] = []
        out_stderr: list[str] = []
        last_rc = 0
        for i, chunk in enumerate(chunks):
            result = self._run_one(chunk, root)
            out_stdout.append(result.get("stdout") or "")
            out_stderr.append(result.get("stderr") or "")
            last_rc = int(result.get("returncode", -1))
            if not result["passed"]:
                print(f"[Verify] ✗ chain step {i + 1}/{len(chunks)} failed (rc={last_rc})")
                return {
                    "passed": False,
                    "stdout": "\n".join(out_stdout),
                    "stderr": "\n".join(out_stderr),
                    "returncode": last_rc,
                    "command": command,
                    "import_checked": import_checked,
                    "ruff_issues": ruff_issues,
                }
        _verify_print_pass(last_rc, chained=True, n_chunks=len(chunks))
        return {
            "passed": True,
            "stdout": "\n".join(out_stdout),
            "stderr": "\n".join(out_stderr),
            "returncode": last_rc,
            "command": command,
            "import_checked": import_checked,
            "ruff_issues": ruff_issues,
        }

    def _run_one(self, command: str, cwd: Path) -> dict:
        try:
            check_run_command_policy(command)
        except SafetyViolation as e:
            raise VerificationError(str(e)) from e

        command = normalize_verification_command_line(command)
        _verify_print_running(command)

        env = _verification_environ(cwd)
        timeout_s = _max_verify_seconds()
        try:
            result = subprocess.run(
                parse_command_argv(command),
                timeout=timeout_s,
                capture_output=True,
                text=True,
                shell=False,
                cwd=str(cwd),
                env=env,
            )
        except subprocess.TimeoutExpired:
            lim = f"{timeout_s}s" if timeout_s is not None else "?"
            return {
                "passed": False,
                "stdout": "",
                "stderr": f"Verification timed out after {lim} (set SAGE_VERIFY_TIMEOUT_S=0 for unlimited)",
                "returncode": -1,
                "command": command,
            }
        except FileNotFoundError as e:
            return {
                "passed": False,
                "stdout": "",
                "stderr": f"Command not found: {e}",
                "returncode": -1,
                "command": command,
            }

        passed = result.returncode == 0
        if passed:
            _verify_print_pass(result.returncode, chained=False)
        else:
            _verify_print_fail(result.returncode, result.stderr)

        return {
            "passed": passed,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": command,
        }
