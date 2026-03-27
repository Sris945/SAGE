"""
Retry helpers.

Adapted from the resilient retry/backoff pattern used in the `simialr stuff/`
reference implementations, simplified for SAGE Python usage.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    retries: int = 2,
    initial_delay_s: float = 0.2,
    backoff: float = 2.0,
) -> T:
    """
    Call `fn` with exponential-backoff retries.

    `retries=2` means up to 3 total attempts.
    """
    delay = max(0.0, float(initial_delay_s))
    attempts = max(0, int(retries)) + 1
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # pragma: no cover - behavior validated via tests
            last_exc = e
            if i >= attempts - 1:
                break
            if delay > 0:
                time.sleep(delay)
            delay = delay * max(1.0, float(backoff))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_call failed without exception")
