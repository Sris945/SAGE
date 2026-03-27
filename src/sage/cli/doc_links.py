"""
Configurable GitHub / docs URLs for in-CLI hints.

Override the default placeholder with:

  export SAGE_REPO_URL=https://github.com/your-org/your-sage-fork

Paths are resolved as ``{repo}/blob/main/{path}`` (GitHub-style).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache


def repo_url() -> str:
    raw = (os.environ.get("SAGE_REPO_URL") or "").strip()
    if raw:
        return raw.rstrip("/")
    return "https://github.com/example/sage"


def doc_url(relative_path: str) -> str:
    """``relative_path`` e.g. ``docs/CLI.md`` (no leading slash)."""
    rel = relative_path.lstrip("/")
    return f"{repo_url()}/blob/main/{rel}"


def _git_origin_https() -> str | None:
    root = os.environ.get("SAGE_WORKSPACE_ROOT") or os.getcwd()
    git = shutil.which("git")
    if not git:
        return None
    try:
        out = subprocess.run(
            [git, "-C", root, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        u = out.stdout.strip()
        if u.startswith("git@github.com:"):
            rest = u.replace("git@github.com:", "", 1).removesuffix(".git")
            return f"https://github.com/{rest}"
        if u.startswith("https://") or u.startswith("http://"):
            return u.removesuffix(".git")
    except OSError:
        return None
    return None


@lru_cache(maxsize=1)
def repo_url_effective() -> str:
    """``SAGE_REPO_URL`` or ``git remote origin`` (https) or placeholder."""
    explicit = (os.environ.get("SAGE_REPO_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    g = _git_origin_https()
    if g:
        return g.rstrip("/")
    return repo_url()


def doc_url_effective(relative_path: str) -> str:
    rel = relative_path.lstrip("/")
    return f"{repo_url_effective()}/blob/main/{rel}"


def print_docs_links_footer() -> None:
    """Muted Rich lines after ``/commands`` / help (repo + doc deep links)."""
    from sage.cli.branding import get_console

    r = repo_url_effective()
    c = get_console()
    c.print()
    c.print("  [muted]Documentation — set[/muted] [accent]SAGE_REPO_URL[/accent] [muted]if links should point at your fork.[/muted]")
    c.print(f"  [muted]Repository[/muted]  [link={r}]{r}[/link]")
    for label, path in (
        ("CLI (slash commands, prompt_toolkit)", "docs/CLI.md"),
        ("Install & startup scripts", "docs/INSTALL.md"),
        ("Getting started", "docs/getting_started.md"),
        ("Architecture", "docs/architecture.md"),
    ):
        u = doc_url_effective(path)
        c.print(f"  [muted]{label}[/muted]")
        c.print(f"    [link={u}]{u}[/link]")
