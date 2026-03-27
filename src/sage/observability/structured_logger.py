"""
SAGE Structured Logger (MVP)
------------------------------
Writes JSON-lines into the session journal at `memory/sessions/YYYY-MM-DD.log`.

This is a lightweight stand-in for Phase 4's observability/event logging.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path

from sage.memory.manager import MemoryManager
from sage.observability.redaction import redact_obj


def log_event(event_type: str, payload: dict | None = None, timestamp: str | None = None) -> None:
    payload = redact_obj(payload or {})
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    entry = {"type": event_type, "timestamp": timestamp, **payload}
    session_id = os.environ.get("SAGE_SESSION_ID")
    if session_id:
        entry["session_id"] = session_id
    trace_id = (os.environ.get("SAGE_TRACE_ID") or "").strip()
    if trace_id:
        entry["trace_id"] = trace_id
    line = json.dumps(entry)
    MemoryManager().append_session_log(line)
    extra = (os.environ.get("SAGE_JSON_LOG_EXTRA_PATH") or "").strip()
    if extra:
        p = Path(extra)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
