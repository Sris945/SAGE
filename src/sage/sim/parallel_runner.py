"""
Parallel execution over oracle tasks (Phase 6).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import tempfile
from pathlib import Path
from typing import Any

from sage.sim.oracle_tasks import generate_oracle_tasks


def _run_one_task(task: dict[str, Any], tmp_root: str) -> dict[str, Any]:
    """Materialize module + test in a temp dir and run pytest."""
    import subprocess
    import sys

    root = Path(tmp_root)
    tid = task["id"]
    mod_name = task["module_name"]
    mod_file = root / f"{mod_name}.py"
    mod_file.write_text(task["module_body"], encoding="utf-8")
    test_file = root / f"test_{tid}.py"
    test_file.write_text(task["test_body"], encoding="utf-8")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=no"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = r.returncode == 0
        return {
            "id": tid,
            "passed": ok,
            "returncode": r.returncode,
            "stderr": (r.stderr or "")[:500],
        }
    except Exception as e:
        return {"id": tid, "passed": False, "error": str(e)[:500]}


def _pool_run_task(payload: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    base, task = payload
    d = tempfile.mkdtemp(dir=base)
    return _run_one_task(task, d)


def _pool_run_task_docker(payload: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Same materialization as `_pool_run_task`, but runs pytest inside Docker
    using `sage.sim.docker_runner`.
    """
    base, task = payload
    d = tempfile.mkdtemp(dir=base)

    root = Path(d)
    tid = task["id"]
    mod_name = task["module_name"]
    (root / f"{mod_name}.py").write_text(task["module_body"], encoding="utf-8")
    test_file = root / f"test_{tid}.py"
    test_file.write_text(task["test_body"], encoding="utf-8")

    try:
        from sage.sim.docker_runner import run_command_in_container

        r = run_command_in_container(
            ["python", "-m", "pytest", test_file.name, "-q", "--tb=no"],
            cwd=root,
            timeout=120,
        )
        ok = int(r.get("returncode", -1)) == 0
        return {
            "id": tid,
            "passed": ok,
            "returncode": int(r.get("returncode", -1)),
            "stderr": str(r.get("stderr") or "")[:500],
        }
    except Exception as e:
        return {"id": tid, "passed": False, "error": str(e)[:500]}


def run_suite_from_jsonl(
    path: Path,
    *,
    workers: int = 4,
    limit: int | None = None,
    use_docker: bool = False,
) -> dict[str, Any]:
    """Run pytest for each task in a JSONL manifest (parallel workers)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    tasks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        tasks.append(json.loads(line))
    if limit is not None:
        tasks = tasks[:limit]

    ctx = mp.get_context("spawn")
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as base:
        tmp_base = str(Path(base))
        payloads = [(tmp_base, t) for t in tasks]
        if workers <= 1:
            for p in payloads:
                results.append(_pool_run_task(p) if not use_docker else _pool_run_task_docker(p))
        else:
            with ctx.Pool(processes=min(workers, max(1, len(tasks)))) as pool:
                fn = _pool_run_task if not use_docker else _pool_run_task_docker
                results = pool.map(fn, payloads)

    passed = sum(1 for r in results if r.get("passed"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": (passed / len(results)) if results else 0.0,
        "results": results,
    }


def run_generated_suite(
    *,
    count: int = 100,
    workers: int = 4,
    seed: int = 42,
    use_docker: bool = False,
) -> dict[str, Any]:
    """In-memory oracle tasks without a JSONL file (smoke tests)."""
    tasks = generate_oracle_tasks(count, seed=seed)
    with tempfile.TemporaryDirectory() as base:
        tmp_base = str(Path(base))
        payloads = [(tmp_base, t) for t in tasks]
        ctx = mp.get_context("spawn")
        if workers <= 1:
            results = [
                (_pool_run_task(p) if not use_docker else _pool_run_task_docker(p))
                for p in payloads
            ]
        else:
            with ctx.Pool(processes=min(workers, max(1, len(tasks)))) as pool:
                fn = _pool_run_task if not use_docker else _pool_run_task_docker
                results = pool.map(fn, payloads)

    passed = sum(1 for r in results if r.get("passed"))
    return {
        "total": len(results),
        "passed": passed,
        "pass_rate": (passed / len(results)) if results else 0.0,
    }
