"""
Composite reward for routing rows (Phase 5). Pure functions for reproducibility.
"""

from __future__ import annotations

DEFAULT_REWARD_VERSION = "reward_v1"


def composite_reward(
    *,
    trajectory_reward: float,
    verification_passed: bool | None,
    terminal: bool,
    retry_penalty: float = 0.05,
    timeout_penalty: float = 1.0,
    failed_reason: str | None = None,
    reward_version: str = DEFAULT_REWARD_VERSION,
) -> float:
    """
    Combine logged signals into a scalar reward for routing offline RL.

    reward_v1:
      - Base: trajectory_reward (often reviewer score 0..1)
      - +0.25 if verification_passed is True
      - -retry_penalty * implicit_retries (from failed_reason hints)
      - -timeout_penalty if failed_reason == 'timeout'
    """
    if reward_version != DEFAULT_REWARD_VERSION:
        # Forward-compatible: unknown versions fall back to trajectory only.
        return float(trajectory_reward)

    r = float(trajectory_reward)
    if verification_passed is True:
        r += 0.25
    if verification_passed is False:
        r -= 0.15

    fr = (failed_reason or "").lower()
    if "timeout" in fr:
        r -= timeout_penalty
    if "retry" in fr or fr == "retry_limit":
        r -= retry_penalty * 2.0

    if terminal and "fail" in fr:
        r -= 0.2

    return max(-2.0, min(2.0, r))
