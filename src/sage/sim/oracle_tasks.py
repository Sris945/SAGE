"""
Deterministic oracle tasks for simulator benchmarks (Phase 6).

Generates N small Python tasks with known pass/fail (pytest assertions).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any


def generate_oracle_tasks(count: int = 1000, *, seed: int = 42) -> list[dict[str, Any]]:
    """
    Produce `count` synthetic tasks. Each task is self-contained source + test snippet.
    """
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for i in range(count):
        a = rng.randint(1, 500)
        b = rng.randint(1, 500)
        expected = a + b
        tid = f"oracle_{i:05d}"
        source = (
            f'"""Auto-generated oracle task {tid}."""\n\n'
            f"def compute() -> int:\n"
            f'    """Return the sum of constants for task {tid}."""\n'
            f"    return {a} + {b}\n"
        )
        test = (
            f'"""Test for {tid}."""\n'
            f"from oracle_module_{i:05d} import compute\n\n"
            f"def test_compute():\n"
            f"    assert compute() == {expected}\n"
        )
        h = hashlib.sha256(f"{tid}:{a}:{b}".encode()).hexdigest()[:12]
        out.append(
            {
                "id": tid,
                "expected_sum": expected,
                "module_body": source,
                "test_body": test,
                "module_name": f"oracle_module_{i:05d}",
                "checksum": h,
            }
        )
    return out


def write_tasks_jsonl(path: Path, count: int = 1000, *, seed: int = 42) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tasks = generate_oracle_tasks(count, seed=seed)
    with path.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return {"path": str(path), "count": len(tasks), "seed": seed}
