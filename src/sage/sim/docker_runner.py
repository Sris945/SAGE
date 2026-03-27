"""
Run commands in an optional Docker sandbox (Phase 6 POC).

Set ``SAGE_DOCKER_TOOLS=1`` to route ``run_command`` tool ops through Docker
(see ``sage.execution.executor.ToolExecutionEngine``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_IMAGE = os.environ.get("SAGE_DOCKER_IMAGE", "sage-sim:latest")


def run_command_in_container(
    argv: list[str],
    *,
    cwd: Path | None = None,
    image: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """
    ``docker run --rm`` with workspace bind-mount. Requires Docker daemon.
    """
    image = image or DEFAULT_IMAGE
    work = Path(cwd or Path.cwd()).resolve()
    work.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{work}:/work",
        "-w",
        "/work",
        image,
        *argv,
    ]
    try:
        r = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        return {
            "status": "ok" if r.returncode == 0 else "error",
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "returncode": -1,
            "stdout": "",
            "stderr": "docker CLI not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "returncode": -1,
            "stdout": "",
            "stderr": f"docker timeout after {timeout}s",
        }


def docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False
