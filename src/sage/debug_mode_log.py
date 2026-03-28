"""Optional NDJSON trace for agent debugging. Disabled unless SAGE_DEBUG_NDJSON is set."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_LOG_PATH_ENV = "SAGE_DEBUG_NDJSON_LOG"


def _env_enabled() -> bool:
    v = os.environ.get("SAGE_DEBUG_NDJSON", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _default_log_path() -> Path:
    # src/sage/debug_mode_log.py -> repo root
    root = Path(__file__).resolve().parent.parent.parent
    d = root / ".cursor"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sage-debug.ndjson"


def _log_path() -> Path:
    raw = os.environ.get(_LOG_PATH_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    return _default_log_path()


def agent_debug_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
    run_id: str = "debug",
) -> None:
    """Append one NDJSON line if SAGE_DEBUG_NDJSON is enabled. Never raises."""
    if not _env_enabled():
        return
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return
