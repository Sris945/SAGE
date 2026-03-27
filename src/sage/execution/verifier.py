"""
SAGE Verification Engine
------------------------
Runs the verification command from a TaskNode after CoderAgent writes a file.
Feeds real stdout/stderr back into the retry loop.

Verification commands come from the planner's `verification` field, e.g.:
  "python -c 'import app'"
  "pytest tests/test_app.py -x -q"
  "python app.py --help"

Safety: ``check_run_command_policy`` (same rules as ``run_command``). Never shell=True.
"""

import subprocess
from pathlib import Path

from sage.execution.exceptions import SafetyViolation
from sage.execution.tool_policy import check_run_command_policy, parse_command_argv

MAX_VERIFY_TIME = 30  # seconds


class VerificationError(Exception):
    pass


class VerificationEngine:
    def run(self, command: str, cwd: str | None = None) -> dict:
        """
        Run a verification command.

        Returns:
          {
            "passed": bool,
            "stdout": str,
            "stderr": str,
            "returncode": int,
            "command": str,
          }
        """
        if not command or not command.strip():
            return {"passed": True, "stdout": "", "stderr": "", "returncode": 0, "command": command}

        try:
            check_run_command_policy(command)
        except SafetyViolation as e:
            raise VerificationError(str(e)) from e

        print(f"[Verify] Running: {command}")

        try:
            result = subprocess.run(
                parse_command_argv(command),
                timeout=MAX_VERIFY_TIME,
                capture_output=True,
                text=True,
                shell=False,  # NEVER shell=True
                cwd=cwd or str(Path.cwd()),
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "stdout": "",
                "stderr": f"Verification timed out after {MAX_VERIFY_TIME}s",
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
            print(f"[Verify] ✓ passed (rc={result.returncode})")
        else:
            print(f"[Verify] ✗ failed (rc={result.returncode})")
            if result.stderr:
                print(f"[Verify] stderr: {result.stderr[:300]}")

        return {
            "passed": passed,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": command,
        }
