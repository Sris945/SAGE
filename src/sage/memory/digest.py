"""
Weekly-style memory digest (spec §16) — aggregates session logs and fix patterns.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sessions_dir() -> Path:
    return Path("memory") / "sessions"


def _recent_session_lines(*, max_files: int = 14) -> list[str]:
    d = _sessions_dir()
    if not d.is_dir():
        return []
    logs = sorted(d.glob("*.log"), key=lambda p: p.name, reverse=True)[:max_files]
    lines: list[str] = []
    for p in logs:
        try:
            lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    return lines


def _parse_jsonl_lines(lines: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def build_digest_markdown(*, title: str | None = None) -> str:
    """Build a markdown digest from recent session JSONL + fix patterns."""
    title = title or "SAGE memory digest"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = _recent_session_lines()
    events = _parse_jsonl_lines(lines)
    types = Counter(str(e.get("type") or "") for e in events)
    err_sigs: list[str] = []
    for e in events:
        if e.get("type") == "FIX_PATTERN_APPLIED":
            pl = e.get("payload") or {}
            sig = str(pl.get("error_signature") or "").strip()
            if sig:
                err_sigs.append(sig)

    fixes_path = Path("memory") / "fixes" / "error_patterns.json"
    fix_count = 0
    if fixes_path.is_file():
        try:
            data = json.loads(fixes_path.read_text(encoding="utf-8"))
            fix_count = len(data) if isinstance(data, list) else len(data.keys())
        except Exception:
            fix_count = 0

    parts = [
        f"# {title}",
        "",
        f"_Generated {now}_",
        "",
        "## Session telemetry (recent logs)",
        "",
        f"- Structured JSON lines parsed: **{len(events)}**",
        f"- Distinct event types: **{len(types)}**",
    ]
    if types:
        parts.append("")
        parts.append("Top event types:")
        for t, n in types.most_common(12):
            if t:
                parts.append(f"- `{t}`: {n}")
    parts.extend(
        [
            "",
            "## Fix patterns",
            "",
            f"- Entries in `memory/fixes/error_patterns.json`: **{fix_count}**",
        ]
    )
    if err_sigs:
        parts.extend(["", "Recent error signatures seen in logs (sample):", ""])
        for s in err_sigs[-10:]:
            parts.append(f"- `{s[:200]}`")

    parts.extend(
        [
            "",
            "## Next steps",
            "",
            "- Review open tasks in `memory/system_state.json` and `memory/handoff.json` (if present).",
            "- Keep session logs under `memory/sessions/` for observability exports.",
        ]
    )
    return "\n".join(parts) + "\n"


def write_digest(out_path: Path | None = None) -> Path:
    """Write digest markdown and return the path."""
    path = out_path or (Path("memory") / "weekly_digest.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_digest_markdown(), encoding="utf-8")
    return path


def maybe_auto_digest() -> bool:
    """
    Auto-generate weekly digest if the existing one is ≥7 days old or missing.
    Returns True if digest was written, False if skipped.
    """
    try:
        import time

        digest_path = Path("memory") / "weekly_digest.md"
        _seven_days_s = 7 * 24 * 60 * 60

        if digest_path.exists():
            mtime = digest_path.stat().st_mtime
            age_s = time.time() - mtime
            if age_s < _seven_days_s:
                return False

        write_digest(digest_path)
        print("[SAGE] Weekly digest updated.")
        return True
    except Exception:
        return False
