"""
Compatibility wrapper for repo-root `main.py`.

Canonical FastAPI app lives in `src/main.py`.
"""

from src.main import app  # noqa: F401

__all__ = ["app"]