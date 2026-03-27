"""
SAGE Project Initializer (Phase 1/3)
------------------------------------
Ensures `.sage/` directory + rules artifacts exist so the agents always have
project-specific guidance (especially in greenfield mode).

Creates both:
  - `.sage/rules.md` (spec-aligned)
  - `.sage-rules.md` (legacy compatibility with current coder agent)
"""

from __future__ import annotations

from pathlib import Path


def ensure_sage_project_artifacts(*, cwd: str | Path = ".") -> None:
    root = Path(cwd)
    sage_dir = root / ".sage"
    sage_dir.mkdir(parents=True, exist_ok=True)

    project_json = sage_dir / "project.json"
    if not project_json.exists():
        project_json.write_text(
            '{"mode":"greenfield","frameworks":[],"entry_points":[]}', errors="ignore"
        )

    conventions_md = sage_dir / "conventions.md"
    if not conventions_md.exists():
        conventions_md.write_text(
            "## Conventions\n\n- Not detected yet (placeholder).\n", errors="ignore"
        )

    # Spec-aligned rules.
    rules_md = sage_dir / "rules.md"
    if not rules_md.exists():
        rules_md.write_text(
            "\n".join(
                [
                    "## SAGE Project Rules (baseline)",
                    "",
                    "### Testing discipline",
                    "- Always write/ensure tests before claiming the change is correct.",
                    "- Prefer minimal, deterministic tests that fail first.",
                    "",
                    "### Tool & safety constraints",
                    "- Never execute destructive commands without HITL confirmation in `--research` mode.",
                    "- Respect tool permissions provided via `TOOL PERMISSIONS`.",
                    "",
                    "### Output discipline",
                    "- Return structured JSON outputs when requested by agent templates.",
                ]
            )
            + "\n",
            errors="ignore",
        )

    rules_coder_md = sage_dir / "rules.coder.md"
    if not rules_coder_md.exists():
        rules_coder_md.write_text(
            "\n".join(
                [
                    "## Coder Agent Rules (baseline)",
                    "",
                    "- Match existing file style and import patterns when editing.",
                    "- Prefer small diffs and avoid unrelated refactors.",
                    "- If tests are missing, generate them in the same task lifecycle.",
                ]
            )
            + "\n",
            errors="ignore",
        )

    # Legacy compatibility file used by current CoderAgent.
    legacy_rules = root / ".sage-rules.md"
    merged = ""
    if rules_md.exists():
        merged += rules_md.read_text(errors="ignore").strip() + "\n\n"
    if rules_coder_md.exists():
        merged += rules_coder_md.read_text(errors="ignore").strip() + "\n"
    merged = merged.strip()
    if merged and (not legacy_rules.exists()):
        legacy_rules.write_text(merged + "\n", errors="ignore")
