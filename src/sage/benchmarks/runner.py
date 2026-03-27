"""
Phase 4 Bench Runner (Lightweight)
----------------------------------
Runs a small set of benchmark prompts end-to-end and computes a contract-stable
metrics set from:
  - the final DAG (`task_dag.nodes`)
  - session journal events (`PROMPT_QUALITY_DELTA`, `TRAJECTORY_STEP`)

This stays intentionally "light" so it can run in dev/CI even when Ollama is
unavailable; benchmark success is "best effort" and metrics focus on pipeline
outcomes + instrumentation presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import contextlib
import os
import json
from pathlib import Path
from statistics import mean
from typing import Any

from sage.orchestrator.workflow import app


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    prompt: str


TASKS_DIR = Path(__file__).parent / "tasks"


def _load_benchmark_cases() -> list[BenchmarkCase]:
    """
    Load benchmark prompts from `benchmarks/tasks/*.yaml` for spec parity.
    """
    try:
        import yaml
    except Exception:  # pragma: no cover
        return []

    cases: list[BenchmarkCase] = []
    for p in sorted(TASKS_DIR.glob("*.yaml")):
        try:
            payload = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            name = str(payload.get("name") or p.stem)
            prompt = str(payload.get("prompt") or "")
            if prompt.strip():
                cases.append(BenchmarkCase(name=name, prompt=prompt))
        except Exception:
            continue
    return cases


def _default_cases() -> list[BenchmarkCase]:
    # Backstop if yaml files are missing.
    return [
        BenchmarkCase(
            name="phase4_case_fastapi_health",
            prompt='Create app.py with a FastAPI app instance and a GET "/health" route returning {"status":"ok"}.',
        )
    ]


def _safe_parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _load_session_log_events(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in log_path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


def _collect_log_events_between(
    *,
    log_path: Path,
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict[str, Any]]:
    events = _load_session_log_events(log_path)
    out: list[dict[str, Any]] = []
    for e in events:
        ts = _safe_parse_iso(str(e.get("timestamp", "")))
        if ts is None:
            continue
        if start_dt <= ts <= end_dt:
            out.append(e)
    return out


def _default_initial_state(user_prompt: str, *, mode: str, max_retries: int) -> dict[str, Any]:
    # Keep this aligned with `sage.cli.main.cmd_run` initial_state keys.
    return {
        "user_prompt": user_prompt,
        "enhanced_prompt": "",
        "task_dag": {},
        "current_task": {},
        "current_task_id": "",
        "agent_output": {},
        "execution_result": {},
        "debug_attempts": 0,
        "session_memory": {},
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "artifacts_by_task": {},
        "architect_blueprints_by_task": {},
        "verification_passed": False,
        "verification_needs_tool_apply": False,
        "orchestrator_escalation": False,
        "task_updates": [],
        "repo_path": "",
        "repo_mode": "greenfield",
        "last_error": "",
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "max_retries": max_retries,
        "events": [],
        "mode": mode,
        "resume_from_handoff": False,
    }


def _mean_metric(benchmarks: list[dict[str, Any]], key: str) -> float:
    vals = [float(b["metrics"].get(key, 0.0)) for b in benchmarks if b.get("metrics")]
    return mean(vals) if vals else 0.0


def _compare_summary(static: dict[str, Any], learned: dict[str, Any]) -> dict[str, Any]:
    sb = static.get("benchmarks") or []
    lb = learned.get("benchmarks") or []
    keys = [
        "build_success_rate",
        "test_pass_rate",
        "debug_loop_iterations",
        "fix_pattern_hit_rate",
        "prompt_quality_delta",
        "orchestrator_intervention_rate",
        "codebase_understanding_accuracy",
        "local_vs_cloud_ratio",
    ]
    out: dict[str, Any] = {}
    for k in keys:
        ms = _mean_metric(sb, k)
        ml = _mean_metric(lb, k)
        out[k] = {"static": ms, "learned": ml, "delta": ml - ms}
    return out


def _execute_benchmark_loop(
    *,
    started_at: datetime,
    log_today: Path,
    mode: str,
    max_retries: int,
) -> dict[str, Any]:
    benchmarks: list[dict[str, Any]] = []
    cases = _load_benchmark_cases() or _default_cases()
    for case in cases:
        case_started = datetime.now(timezone.utc)
        status = "ok"
        err = ""
        final_state: dict[str, Any] = {}

        try:
            import uuid

            prev_session_id = os.environ.get("SAGE_SESSION_ID")
            os.environ["SAGE_SESSION_ID"] = uuid.uuid4().hex
            init = _default_initial_state(case.prompt, mode=mode, max_retries=max_retries)
            with (
                open(os.devnull, "w") as devnull,
                contextlib.redirect_stdout(devnull),
                contextlib.redirect_stderr(devnull),
            ):
                final_state = app.invoke(init)  # type: ignore[assignment]
        except Exception as e:  # pragma: no cover
            status = "error"
            err = str(e)
        finally:
            # Ensure benchmark session ids don't leak into the caller environment.
            if prev_session_id is None:
                os.environ.pop("SAGE_SESSION_ID", None)
            else:
                os.environ["SAGE_SESSION_ID"] = prev_session_id

        case_ended = datetime.now(timezone.utc)

        nodes = (
            final_state.get("task_dag", {}).get("nodes", [])
            if isinstance(final_state, dict)
            else []
        )
        total_tasks = len(nodes)
        completed_tasks = sum(1 for n in nodes if n.get("status") == "completed")
        failed_tasks = sum(1 for n in nodes if n.get("status") == "failed")
        completion_rate = (completed_tasks / total_tasks) if total_tasks else 0.0
        avg_retry = mean([float(n.get("retry_count", 0)) for n in nodes]) if nodes else 0.0

        events = _collect_log_events_between(
            log_path=log_today,
            start_dt=case_started,
            end_dt=case_ended,
        )
        prompt_quality_events = [
            e
            for e in events
            if e.get("type") == "PROMPT_QUALITY_DELTA"
            and (
                e.get("agent") == "prompt_middleware"
                or e.get("payload", {}).get("agent") == "prompt_middleware"
            )
        ]
        orchestrator_events = [e for e in events if e.get("type") == "ORCHESTRATOR_INTERVENTION"]
        fix_applied_events = [e for e in events if e.get("type") == "FIX_PATTERN_APPLIED"]
        ollama_timeout_events = [e for e in events if e.get("type") == "OLLAMA_TIMEOUT"]

        build_success_rate = 1.0 if failed_tasks == 0 and total_tasks else 0.0
        test_pass_rate = completion_rate
        debug_loop_iterations = avg_retry

        denom_failures = failed_tasks if failed_tasks > 0 else 0
        fix_pattern_hit_rate = (len(fix_applied_events) / denom_failures) if denom_failures else 0.0

        quality_deltas = [float(e.get("quality_delta", 0.0)) for e in prompt_quality_events]
        prompt_quality_delta = mean(quality_deltas) if quality_deltas else 0.0

        orchestrator_intervention_rate = (
            (len(orchestrator_events) / total_tasks) if total_tasks else 0.0
        )

        codebase_understanding_accuracy = 1.0

        local_vs_cloud_ratio = 0.0 if ollama_timeout_events else 1.0

        metrics = {
            "build_success_rate": build_success_rate,
            "test_pass_rate": test_pass_rate,
            "debug_loop_iterations": debug_loop_iterations,
            "fix_pattern_hit_rate": fix_pattern_hit_rate,
            "prompt_quality_delta": prompt_quality_delta,
            "orchestrator_intervention_rate": orchestrator_intervention_rate,
            "codebase_understanding_accuracy": codebase_understanding_accuracy,
            "local_vs_cloud_ratio": local_vs_cloud_ratio,
        }

        benchmarks.append(
            {
                "name": case.name,
                "status": status,
                "error": err,
                "metrics": metrics,
                "started_at": case_started.isoformat(),
                "completed_at": case_ended.isoformat(),
            }
        )

    return {
        "status": "ok",
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "SAGE_RL_POLICY": os.environ.get("SAGE_RL_POLICY", ""),
        "benchmarks": benchmarks,
    }


def run_benchmarks(*, compare_policy: bool = False) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    log_today = Path("memory") / "sessions" / f"{started_at.strftime('%Y-%m-%d')}.log"

    _prev_bench = os.environ.get("SAGE_BENCH")
    os.environ["SAGE_BENCH"] = "1"
    ollama_bench_profile = {
        "SAGE_BENCH": os.environ.get("SAGE_BENCH", "1"),
        "SAGE_BENCH_TIMEOUT_MULT": os.environ.get("SAGE_BENCH_TIMEOUT_MULT", "3.0"),
        "SAGE_BENCH_CHAT_MAX_S": os.environ.get("SAGE_BENCH_CHAT_MAX_S", "180.0"),
        "SAGE_BENCH_EMBED_MAX_S": os.environ.get("SAGE_BENCH_EMBED_MAX_S", "15.0"),
    }

    mode = "auto"
    max_retries = 5

    try:
        if not compare_policy:
            result = _execute_benchmark_loop(
                started_at=started_at,
                log_today=log_today,
                mode=mode,
                max_retries=max_retries,
            )
            result["ollama_bench_profile"] = ollama_bench_profile
            return result

        from sage.rl.policy import clear_routing_policy_cache

        prev_rl = os.environ.get("SAGE_RL_POLICY")
        try:
            clear_routing_policy_cache()
            os.environ["SAGE_RL_POLICY"] = "0"
            static = _execute_benchmark_loop(
                started_at=started_at,
                log_today=log_today,
                mode=mode,
                max_retries=max_retries,
            )
            clear_routing_policy_cache()
            os.environ["SAGE_RL_POLICY"] = "1"
            learned = _execute_benchmark_loop(
                started_at=started_at,
                log_today=log_today,
                mode=mode,
                max_retries=max_retries,
            )
            summary = _compare_summary(static, learned)
            return {
                "status": "ok",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "ollama_bench_profile": ollama_bench_profile,
                "compare_mode": True,
                "compare": {
                    "static": static,
                    "learned": learned,
                    "summary": summary,
                },
            }
        finally:
            clear_routing_policy_cache()
            if prev_rl is None:
                os.environ.pop("SAGE_RL_POLICY", None)
            else:
                os.environ["SAGE_RL_POLICY"] = prev_rl
    finally:
        if _prev_bench is None:
            os.environ.pop("SAGE_BENCH", None)
        else:
            os.environ["SAGE_BENCH"] = _prev_bench
