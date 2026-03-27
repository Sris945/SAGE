"""
Resolved paths for user-level config vs bundled defaults.

Precedence for ``models.yaml``:
  1. ``SAGE_MODELS_YAML`` environment variable
  2. ``$XDG_CONFIG_HOME/sage/models.yaml`` (or ``~/.config/sage/models.yaml``)
  3. Packaged ``src/sage/config/models.yaml``
"""

from __future__ import annotations

import os
from pathlib import Path


def user_config_dir() -> Path:
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return (Path(xdg) / "sage").resolve()
    return (Path.home() / ".config" / "sage").resolve()


def bundled_models_yaml() -> Path:
    return Path(__file__).resolve().parent / "models.yaml"


def resolved_models_yaml_path() -> Path:
    override = (os.environ.get("SAGE_MODELS_YAML") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    user = user_config_dir() / "models.yaml"
    if user.is_file():
        return user.resolve()
    return bundled_models_yaml()
