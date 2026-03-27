"""
SAGE Session Manager
--------------------
Handles handoff write/read and session resume logic.

On sage run:
  1. Check for memory/handoff.json
  2. If present → SESSION_RESUMED mode
  3. If absent  → fresh session

On clean SESSION_END → delete handoff.json
On SESSION_INTERRUPTED → write handoff.json with full snapshot
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HANDOFF_PATH = Path("memory/handoff.json")


class SessionManager:
    def check_handoff(self) -> dict | None:
        """Returns handoff data if an interrupted session exists, else None."""
        if HANDOFF_PATH.exists():
            with open(HANDOFF_PATH) as f:
                return json.load(f)
        return None

    def write_handoff(
        self,
        reason: str,
        active_task_id: str,
        dag_snapshot: dict,
        last_file: str = "",
        last_command: str = "",
        fix_patterns_applied: list[str] | None = None,
        resume_instruction: str = "",
    ) -> None:
        handoff = {
            "interrupted_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "active_task_id": active_task_id,
            "dag_snapshot": dag_snapshot,
            "last_file_written": last_file,
            "last_command_run": last_command,
            "open_file_handles": [],
            "fix_patterns_applied": fix_patterns_applied or [],
            "resume_instruction": resume_instruction,
        }
        HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HANDOFF_PATH, "w") as f:
            json.dump(handoff, f, indent=2)

    def clear_handoff(self) -> None:
        """Called on clean SESSION_END."""
        if HANDOFF_PATH.exists():
            HANDOFF_PATH.unlink()
