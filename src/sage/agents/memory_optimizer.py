"""
SAGE Memory Optimizer Agent
----------------------------
Runs at the end of every session (called from save_memory node).

Responsibilities:
  1. Generate .sage-memory.md — a compact project summary that feeds into
     future planner/coder system prompts as cross-session context.
  2. Prune stale fix patterns (unused for 14+ days).
  3. Promote high-success-rate patterns (> 0.8) by sorting them first.
  4. Append today's session summary to memory/sessions/<date>.log.

.sage-memory.md format (≤ 200 lines):
  - Active project + goal
  - Last 5 completed tasks
  - Top 3 fix patterns (by success rate)
  - Open blockers
  - Key decisions made
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

MEMORY_DIR = Path("memory")
STATE_FILE = MEMORY_DIR / "system_state.json"
SESSIONS_DIR = MEMORY_DIR / "sessions"
FIX_PATTERNS_FILE = MEMORY_DIR / "fixes" / "error_patterns.json"
SAGE_MEMORY_FILE = Path(".sage-memory.md")

STALE_DAYS = 14
HIGH_SUCCESS_THRESHOLD = 0.8


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _load_recent_logs(days: int = 7) -> list[str]:
    """Load last N days of session log entries."""
    entries = []
    for i in range(days):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        log = SESSIONS_DIR / f"{day}.log"
        if log.exists():
            entries.extend(log.read_text().splitlines())
    return entries[-50:]  # cap at 50 most recent lines


def _prune_patterns(patterns: list[dict]) -> list[dict]:
    """Remove fix patterns untouched for STALE_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    kept = []
    pruned = 0
    for p in patterns:
        last_seen = p.get("last_seen", "") or p.get("last_used", "")
        try:
            dt = datetime.fromisoformat(last_seen)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > cutoff:
                kept.append(p)
            else:
                pruned += 1
        except (ValueError, TypeError):
            kept.append(p)  # keep if date is unparseable
    if pruned:
        print(f"[MemoryOpt] Pruned {pruned} stale fix pattern(s).")
    # Prefer success_rate (EMA); fall back to times_applied.
    return sorted(
        kept,
        key=lambda p: p.get("success_rate", p.get("times_applied", 0)),
        reverse=True,
    )


def _generate_sage_memory(state: dict, patterns: list[dict], recent_logs: list[str]) -> str:
    """Render .sage-memory.md — compact cross-session context file."""
    now = datetime.now(timezone.utc).isoformat()
    top_patterns = patterns[:3]

    lines = [
        "# SAGE Project Memory",
        f"_Last updated: {now}_",
        "",
        "## Active Project",
        f"- {state.get('active_project', '(no project set)')}",
        f"- Sessions completed: {state.get('session_count', 0)}",
        f"- Last task completed: `{state.get('last_completed_task', 'none')}`",
        f"- Next unblocked task: `{state.get('next_unblocked_task', 'none')}`",
        "",
    ]

    if state.get("open_blockers"):
        lines += ["## Open Blockers"]
        for b in state["open_blockers"]:
            lines.append(f"- {b}")
        lines.append("")

    if top_patterns:
        lines += ["## Top Fix Patterns (auto-learned)"]
        for p in top_patterns:
            cause = p.get("suspected_cause", p.get("error_signature", "unknown"))
            count = p.get("times_applied", 0)
            fix = p.get("fix_file", p.get("fix_operation", p.get("fix_patch", "")))
            sr = p.get("success_rate", 0)
            lines.append(f"- `{cause}` → `{fix}` (used {count}×, success_rate={sr:.2f})")
        lines.append("")

    if recent_logs:
        lines += ["## Recent Session Log (last 10 entries)"]
        for entry in recent_logs[-10:]:
            lines.append(f"  {entry}")
        lines.append("")

    return "\n".join(lines)


class MemoryOptimizerAgent:
    def run(self, memory_dir: str = "memory") -> dict:
        """
        Run the memory optimizer. Returns:
          {"status": "ok", "pruned_patterns": int, "updated_memory_file": str}
        """
        print("\n[MemoryOpt] Running memory optimization...")

        state = _load_json(STATE_FILE, {})
        patterns = _load_json(FIX_PATTERNS_FILE, [])
        recent_logs = _load_recent_logs()

        # 1. Prune + sort fix patterns
        cleaned = _prune_patterns(patterns)
        pruned_count = len(patterns) - len(cleaned)
        if patterns != cleaned:
            FIX_PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
            FIX_PATTERNS_FILE.write_text(json.dumps(cleaned, indent=2))

        # 2. Generate .sage-memory.md
        content = _generate_sage_memory(state, cleaned, recent_logs)
        SAGE_MEMORY_FILE.write_text(content)
        print(f"[MemoryOpt] ✓ .sage-memory.md updated ({len(content.splitlines())} lines)")

        return {
            "status": "ok",
            "pruned_patterns": pruned_count,
            "updated_memory_file": str(SAGE_MEMORY_FILE),
        }


def load_sage_memory() -> str:
    """Load .sage-memory.md for injection into planner/coder prompts."""
    if SAGE_MEMORY_FILE.exists():
        return SAGE_MEMORY_FILE.read_text()
    return ""
