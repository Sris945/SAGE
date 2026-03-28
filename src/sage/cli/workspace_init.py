"""Scaffold `.sage/` and `memory/` in a project directory."""

from __future__ import annotations

from pathlib import Path

_DEFAULT_RULES = """# Project rules for SAGE

# Optional: agent-specific files — `.sage/rules.planner.md`, `.sage/rules.coder.md`,
# `.sage/rules.documentation.md`, …
# Global user rules may also live in `~/.sage/rules.md`.

- Prefer small, reviewable changes.
- Match existing style in this repository.
"""


def init_workspace(root: Path, *, force: bool) -> dict[str, object]:
    """
    Create `.sage/rules.md` (unless present), ensure `memory/`, append SAGE stanza to `.gitignore`.
    Returns a summary dict for CLI output.
    """
    root = root.resolve()
    sage_dir = root / ".sage"
    rules_file = sage_dir / "rules.md"
    memory_dir = root / "memory"
    created: list[str] = []
    updated: list[str] = []

    if not sage_dir.exists():
        sage_dir.mkdir(parents=True, exist_ok=True)
        created.append(str(sage_dir))
    else:
        sage_dir.mkdir(parents=True, exist_ok=True)

    if not rules_file.exists():
        rules_file.write_text(_DEFAULT_RULES.strip() + "\n", encoding="utf-8")
        created.append(str(rules_file))
    elif force:
        rules_file.write_text(_DEFAULT_RULES.strip() + "\n", encoding="utf-8")
        updated.append(str(rules_file))

    mem_new = not memory_dir.exists()
    memory_dir.mkdir(parents=True, exist_ok=True)
    if mem_new:
        created.append(str(memory_dir))

    gitignore = root / ".gitignore"
    stanza = "\n# SAGE — session state (keep local)\nmemory/\n"
    if gitignore.exists():
        body = gitignore.read_text(encoding="utf-8", errors="ignore")
        if "memory/" not in body and "# SAGE" not in body:
            gitignore.write_text(body.rstrip() + stanza, encoding="utf-8")
            updated.append(str(gitignore))
    else:
        gitignore.write_text(stanza.lstrip(), encoding="utf-8")
        created.append(str(gitignore))

    pytest_ini = root / "pytest.ini"
    if not pytest_ini.exists():
        pytest_ini.write_text(
            "[pytest]\n"
            "# Greenfield layout: tests can `import app` when code lives under src/\n"
            "pythonpath = src\n"
            "testpaths = tests\n",
            encoding="utf-8",
        )
        created.append(str(pytest_ini))

    return {
        "root": str(root),
        "created": created,
        "updated": updated,
    }
