"""
SAGE Memory Manager
-------------------
Central interface for all memory reads/writes.
Agents never access memory directly — everything routes through here.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path("memory")
STATE_FILE = MEMORY_DIR / "system_state.json"
SESSIONS_DIR = MEMORY_DIR / "sessions"
FIXES_FILE = MEMORY_DIR / "fixes" / "error_patterns.json"
LEGACY_FIXES_FILE = MEMORY_DIR / "fix_patterns.json"


class MemoryManager:
    def _log_memory_event(self, event_type: str, payload: dict) -> None:
        try:
            from sage.observability.structured_logger import log_event

            log_event(event_type, payload=payload)
        except Exception:
            # Best-effort only.
            pass

    def load_state(self) -> dict:
        """Layer 1: Load system_state.json. Returns empty dict if missing."""
        if STATE_FILE.exists() and STATE_FILE.stat().st_size > 0:
            with open(STATE_FILE) as f:
                data = json.load(f)
            self._log_memory_event(
                "MEMORY_READ",
                payload={"key": str(STATE_FILE), "bytes": int(STATE_FILE.stat().st_size)},
            )
            return data
        return {}

    def save_state(self, state: dict) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        try:
            self._log_memory_event(
                "MEMORY_WRITE",
                payload={"key": str(STATE_FILE), "bytes": int(STATE_FILE.stat().st_size)},
            )
        except Exception:
            pass

    def append_session_log(self, entry: str) -> None:
        """Layer 2: Append-only session journal.

        When ``SAGE_SESSION_LOG_MAX_MB`` is set to a positive number, rotate the
        current day's log if it would exceed that size (best-effort rename).
        """
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = SESSIONS_DIR / f"{today}.log"
        raw = (os.environ.get("SAGE_SESSION_LOG_MAX_MB") or "").strip()
        if raw:
            try:
                max_mb = float(raw)
            except ValueError:
                max_mb = 0.0
            if max_mb > 0 and log_file.exists():
                max_bytes = int(max_mb * 1024 * 1024)
                next_len = (
                    log_file.stat().st_size + len(entry.encode("utf-8", errors="replace")) + 1
                )
                if next_len > max_bytes:
                    for i in range(1, 1000):
                        rotated = SESSIONS_DIR / f"{today}.{i}.log"
                        if not rotated.exists():
                            try:
                                log_file.rename(rotated)
                            except OSError:
                                pass
                            break

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

    def load_fix_patterns(self) -> list[dict]:
        """Layer 4: Load self-learned fix patterns."""
        if FIXES_FILE.exists() and FIXES_FILE.stat().st_size > 0:
            with open(FIXES_FILE) as f:
                data = json.load(f)
            self._log_memory_event(
                "MEMORY_READ",
                payload={"key": str(FIXES_FILE), "bytes": int(FIXES_FILE.stat().st_size)},
            )
            return data

        # Backward-compatible migration: convert legacy schema to normalized schema.
        if LEGACY_FIXES_FILE.exists() and LEGACY_FIXES_FILE.stat().st_size > 0:
            try:
                legacy_patterns = json.loads(LEGACY_FIXES_FILE.read_text())
            except Exception:
                legacy_patterns = []

            migrated: list[dict] = []
            for p in legacy_patterns or []:
                # Legacy schema doesn't include patch content; keep fix_patch empty.
                migrated.append(
                    {
                        "error_signature": p.get("error_fingerprint")
                        or p.get("error_signature", ""),
                        "suspected_cause": p.get("suspected_cause", ""),
                        "fix_operation": p.get("fix_operation", ""),
                        "fix_file": p.get("fix_file", ""),
                        "fix_patch": p.get("fix_patch", ""),  # may be empty
                        "success_rate": 1.0 if p.get("success_count", 0) else 0.0,
                        "times_applied": int(p.get("success_count", 0) or 0),
                        "last_used": (
                            (p.get("last_seen") or "").split("T")[0] if p.get("last_seen") else ""
                        ),
                        "source": "legacy_migration",
                    }
                )

            FIXES_FILE.parent.mkdir(parents=True, exist_ok=True)
            FIXES_FILE.write_text(json.dumps(migrated, indent=2))
            self._log_memory_event(
                "MEMORY_MIGRATION",
                payload={"from": str(LEGACY_FIXES_FILE), "to": str(FIXES_FILE)},
            )
            return migrated

        return []

    def save_fix_pattern(self, pattern: dict) -> None:
        """Append or update a fix pattern with EMA success_rate tracking."""
        FIXES_FILE.parent.mkdir(parents=True, exist_ok=True)
        patterns = self.load_fix_patterns()
        sig = pattern["error_signature"]
        existing = next((p for p in patterns if p["error_signature"] == sig), None)
        if existing:
            # Exponential moving average α=0.2
            alpha = 0.2
            existing["success_rate"] = (
                alpha * pattern.get("success_rate", 1.0) + (1 - alpha) * existing["success_rate"]
            )
            existing["times_applied"] = existing.get("times_applied", 0) + 1
            existing["last_used"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        else:
            patterns.append(pattern)
        with open(FIXES_FILE, "w") as f:
            json.dump(patterns, f, indent=2)
        self._log_memory_event(
            "MEMORY_WRITE",
            payload={"key": str(FIXES_FILE), "patterns_total": len(patterns)},
        )

    def find_fix_pattern(self, error_signature: str) -> dict | None:
        """Exact match first. Semantic fallback is Phase 3 (Qdrant)."""
        patterns = self.load_fix_patterns()
        return next((p for p in patterns if p["error_signature"] == error_signature), None)
