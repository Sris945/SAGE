"""
Git hook utilities (Phase 1)
----------------------------
Ensures the repo has a `post-commit` hook that continuously appends commit
context into `.sage-memory.md`.
"""

from __future__ import annotations

from pathlib import Path


def ensure_post_commit_hook(*, repo_dir: str | Path) -> None:
    repo = Path(repo_dir).resolve()
    if not (repo / ".git").exists():
        return

    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    target = hooks_dir / "post-commit"
    if target.exists() and target.stat().st_size > 0:
        # Don't override an existing hook.
        return

    src = Path(__file__).parent / "post-commit.sh"
    if not src.exists():
        return

    try:
        target.write_text(src.read_text(errors="ignore"))
        target.chmod(0o755)
    except Exception:
        # Best-effort only.
        return


def ensure_sage_memory_file(*, repo_dir: str | Path) -> None:
    repo = Path(repo_dir).resolve()
    f = repo / ".sage-memory.md"
    if not f.exists():
        try:
            f.write_text("# SAGE Memory\n\n", errors="ignore")
        except Exception:
            return
