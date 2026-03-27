"""Execution-layer exceptions."""


class SafetyViolation(Exception):
    """Blocked filesystem or command operation."""
