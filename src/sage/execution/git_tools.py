"""
SAGE Git Tools
--------------
Safe, subprocess-based git operations for the tool executor.
All operations are scoped to a workspace root and use shell=False.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _validate_repo(repo_path: str) -> tuple[bool, str]:
    """Return (ok, error_message). Checks path exists and is a git repo."""
    p = Path(repo_path)
    if not p.exists():
        return False, f"repo_path does not exist: {repo_path}"
    if not (p / ".git").exists():
        return False, f"not a git repository (no .git/): {repo_path}"
    return True, ""


def _run(args: list[str], *, cwd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def git_commit(repo_path: str, message: str, files: list[str] | None = None) -> dict:
    """Stage specified files (or all) and commit.

    Returns {status, stdout, stderr}.
    """
    ok, err = _validate_repo(repo_path)
    if not ok:
        return {"status": "error", "stdout": "", "stderr": err}
    try:
        if files:
            add_args = ["git", "add", "--"] + files
        else:
            add_args = ["git", "add", "-A"]
        add = _run(add_args, cwd=repo_path)
        if add.returncode != 0:
            return {"status": "error", "stdout": add.stdout, "stderr": add.stderr}
        commit = _run(["git", "commit", "-m", message], cwd=repo_path)
        return {
            "status": "ok" if commit.returncode == 0 else "error",
            "stdout": commit.stdout,
            "stderr": commit.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "stdout": "", "stderr": "git commit timed out"}
    except OSError as e:
        return {"status": "error", "stdout": "", "stderr": str(e)}


def git_diff(repo_path: str, file: str | None = None, staged: bool = False) -> dict:
    """Get diff output.

    Returns {status, diff: str}.
    """
    ok, err = _validate_repo(repo_path)
    if not ok:
        return {"status": "error", "diff": err}
    try:
        args = ["git", "diff"]
        if staged:
            args.append("--cached")
        if file:
            args += ["--", file]
        result = _run(args, cwd=repo_path)
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "diff": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "diff": "", "stderr": "git diff timed out"}
    except OSError as e:
        return {"status": "error", "diff": "", "stderr": str(e)}


def git_log(repo_path: str, n: int = 10, file: str | None = None) -> dict:
    """Get last n commits.

    Returns {status, entries: [{"hash": str, "message": str, "date": str}]}.
    """
    ok, err = _validate_repo(repo_path)
    if not ok:
        return {"status": "error", "entries": [], "stderr": err}
    try:
        sep = "\x1f"  # unit separator — safe delimiter
        fmt = f"%H{sep}%s{sep}%ai"
        args = ["git", "log", f"-{n}", f"--pretty=format:{fmt}"]
        if file:
            args += ["--", file]
        result = _run(args, cwd=repo_path)
        entries: list[dict] = []
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split(sep)
                if len(parts) >= 3:
                    entries.append(
                        {"hash": parts[0], "message": parts[1], "date": parts[2]}
                    )
                elif len(parts) == 2:
                    entries.append({"hash": parts[0], "message": parts[1], "date": ""})
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "entries": entries,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "entries": [], "stderr": "git log timed out"}
    except OSError as e:
        return {"status": "error", "entries": [], "stderr": str(e)}


def git_branch(repo_path: str, name: str | None = None, create: bool = False) -> dict:
    """List branches or create one.

    Returns {status, current: str, branches: [str]}.
    """
    ok, err = _validate_repo(repo_path)
    if not ok:
        return {"status": "error", "current": "", "branches": [], "stderr": err}
    try:
        if create and name:
            result = _run(["git", "checkout", "-b", name], cwd=repo_path)
            if result.returncode != 0:
                return {
                    "status": "error",
                    "current": "",
                    "branches": [],
                    "stderr": result.stderr,
                }
        # List branches
        result = _run(["git", "branch", "--list"], cwd=repo_path)
        current = ""
        branches: list[str] = []
        for line in (result.stdout or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("* "):
                current = stripped[2:].strip()
                branches.append(current)
            elif stripped:
                branches.append(stripped)
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "current": current,
            "branches": branches,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "current": "", "branches": [], "stderr": "git branch timed out"}
    except OSError as e:
        return {"status": "error", "current": "", "branches": [], "stderr": str(e)}


def git_status(repo_path: str) -> dict:
    """Get working tree status.

    Returns {status, modified: [str], untracked: [str], staged: [str]}.
    """
    ok, err = _validate_repo(repo_path)
    if not ok:
        return {"status": "error", "modified": [], "untracked": [], "staged": [], "stderr": err}
    try:
        result = _run(["git", "status", "--porcelain"], cwd=repo_path)
        modified: list[str] = []
        untracked: list[str] = []
        staged: list[str] = []
        for line in (result.stdout or "").splitlines():
            if len(line) < 3:
                continue
            xy = line[:2]
            path = line[3:].strip()
            x, y = xy[0], xy[1]
            # x = index (staged), y = worktree (unstaged)
            if x == "?" and y == "?":
                untracked.append(path)
            else:
                if x not in (" ", "?"):
                    staged.append(path)
                if y not in (" ", "?"):
                    modified.append(path)
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "modified": modified,
            "untracked": untracked,
            "staged": staged,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "modified": [],
            "untracked": [],
            "staged": [],
            "stderr": "git status timed out",
        }
    except OSError as e:
        return {"status": "error", "modified": [], "untracked": [], "staged": [], "stderr": str(e)}
