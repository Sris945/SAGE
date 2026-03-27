"""
Optional routing overrides for local testing and CI on modest hardware.

Env:
  SAGE_MODEL_PROFILE=test — force every role to use the same small local model
    (default: qwen2.5-coder:1.5b). Disables fallback triggers so routing stays
    deterministic on a laptop.
  SAGE_FORCE_LOCAL_MODEL=<tag> — same as ``test`` profile but with an explicit
    Ollama tag (overrides the default model name).
"""

from __future__ import annotations

import copy
import os
from typing import Any

DEFAULT_TEST_MODEL = "qwen2.5-coder:1.5b"


def maybe_apply_test_profile(config: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied config with test overrides, or the original shape if inactive."""
    force = (os.environ.get("SAGE_FORCE_LOCAL_MODEL") or "").strip()
    profile = (os.environ.get("SAGE_MODEL_PROFILE") or "").strip().lower()
    if profile != "test" and not force:
        return config

    cfg = copy.deepcopy(config)
    model = force if force else DEFAULT_TEST_MODEL
    routing = cfg.setdefault("routing", {})
    if not isinstance(routing, dict):
        return cfg

    for _role, rc in list(routing.items()):
        if not isinstance(rc, dict):
            continue
        rc["primary"] = model
        rc["fallback"] = model
        rc["fallback_triggers"] = []

    return cfg
