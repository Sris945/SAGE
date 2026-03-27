"""Session log helpers shared by CLI commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def today_session_log_path() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path("memory") / "sessions" / f"{today}.log"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def print_routing_summary_for_session(session_id: str) -> None:
    events = load_jsonl(today_session_log_path())
    rs = [
        e
        for e in events
        if e.get("type") == "MODEL_ROUTING_DECISION"
        and str(e.get("session_id") or "") == session_id
    ]
    if not rs:
        print("[SAGE] explain-routing: no routing decisions captured for this session.")
        return
    print(f"[SAGE] explain-routing: {len(rs)} routing decisions")
    by_role: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in rs:
        role = str(r.get("agent_role") or "unknown")
        src = str(r.get("policy_source") or "yaml")
        by_role[role] = by_role.get(role, 0) + 1
        by_source[src] = by_source.get(src, 0) + 1
    print("  by role:")
    for k in sorted(by_role):
        print(f"    - {k}: {by_role[k]}")
    print("  by policy_source:")
    for k in sorted(by_source):
        print(f"    - {k}: {by_source[k]}")
