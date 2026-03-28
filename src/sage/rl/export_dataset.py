"""
Export session JSONL logs into versioned routing training JSONL (Phase 5).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from sage.orchestrator.model_router import ModelRouter
from sage.rl.reward import DEFAULT_REWARD_VERSION, composite_reward
from sage.rl.schema import ROUTING_SCHEMA_VERSION, RoutingTrainingRow

ROUTER_ROLES = frozenset(
    {
        "planner",
        "architect",
        "coder",
        "debugger",
        "reviewer",
        "test_engineer",
        "documentation",
        "memory_optimizer",
    }
)

MIN_ROWS_RECOMMENDED = 500


def iter_session_log_lines(log_path: Path) -> Iterator[dict[str, Any]]:
    if not log_path.exists():
        return
    try:
        for line in log_path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    except OSError:
        return


def load_all_events(log_paths: list[Path]) -> list[tuple[str, dict[str, Any]]]:
    """Return (session_id, event) pairs in file order."""
    out: list[tuple[str, dict[str, Any]]] = []
    for lp in log_paths:
        for ev in iter_session_log_lines(lp):
            sid = str(ev.get("session_id") or lp.stem)
            out.append((sid, ev))
    return out


def _aggregate_task_context(events: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """
    Per task_id: last terminal flags, max trajectory reward, verification hints.
    """
    by_task: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "terminal_reward": None,
            "last_terminal": False,
            "verification_passed": None,
            "failed_reason": None,
        }
    )
    for _sid, ev in events:
        if ev.get("type") != "TRAJECTORY_STEP":
            continue
        tid = str(ev.get("task_id") or "")
        if not tid:
            continue
        st = by_task[tid]
        tr = float(ev.get("reward", 0.0))
        term = bool(ev.get("terminal", False))
        state = ev.get("state") if isinstance(ev.get("state"), dict) else {}
        if "verification_passed" in state:
            st["verification_passed"] = bool(state.get("verification_passed"))
        if "failed_reason" in state:
            st["failed_reason"] = str(state.get("failed_reason") or "")
        if term:
            st["last_terminal"] = True
            st["terminal_reward"] = tr
        else:
            st["terminal_reward"] = (
                st["terminal_reward"] if st["terminal_reward"] is not None else tr
            )
    return dict(by_task)


def _action_fallback_label(model_chosen: str, primary: str, fallback: str) -> int:
    mc = (model_chosen or "").strip()
    if mc == fallback:
        return 1
    return 0


def export_routing_rows(
    events: list[tuple[str, dict[str, Any]]],
    *,
    router: ModelRouter | None = None,
    reward_version: str = DEFAULT_REWARD_VERSION,
) -> list[RoutingTrainingRow]:
    router = router or ModelRouter()
    task_ctx = _aggregate_task_context(events)
    rows: list[RoutingTrainingRow] = []

    for session_id, ev in events:
        if ev.get("type") != "TRAJECTORY_STEP":
            continue
        agent = str(ev.get("agent") or "")
        if agent not in ROUTER_ROLES:
            continue
        tid = str(ev.get("task_id") or "")
        if not tid:
            continue
        action = ev.get("action")
        if not isinstance(action, dict):
            continue
        model_chosen = str(action.get("model_chosen") or "")
        if not model_chosen:
            continue

        primary, fallback = router.get_primary_fallback(agent)
        af = _action_fallback_label(model_chosen, primary, fallback)

        state = ev.get("state") if isinstance(ev.get("state"), dict) else {}
        extra = ev.get("extra") if isinstance(ev.get("extra"), dict) else {}
        data_source = "synthetic" if bool(extra.get("synthetic")) else "real"
        tcs = float(state.get("task_complexity_score", 0.0) or 0.0)
        pfc = int(state.get("primary_failure_count", state.get("failure_count", 0)) or 0)

        ctx = task_ctx.get(tid, {})
        tc = composite_reward(
            trajectory_reward=float(ev.get("reward", 0.0)),
            verification_passed=ctx.get("verification_passed"),
            terminal=bool(ev.get("terminal", False)),
            failed_reason=str(ctx.get("failed_reason") or ""),
            reward_version=reward_version,
        )

        rows.append(
            RoutingTrainingRow(
                schema_version=ROUTING_SCHEMA_VERSION,
                session_id=session_id,
                task_id=tid,
                agent_role=agent,
                timestamp=str(ev.get("timestamp") or ""),
                task_complexity_score=tcs,
                primary_failure_count=pfc,
                action_fallback=af,
                primary_model=primary,
                fallback_model=fallback,
                model_chosen=model_chosen,
                reward=tc,
                terminal=bool(ev.get("terminal", False)),
                reward_version=reward_version,
                data_source=data_source,
                state=dict(state),
            )
        )
    return rows


def export_logs_to_jsonl(
    *,
    log_dir: Path,
    output_path: Path,
    reward_version: str = DEFAULT_REWARD_VERSION,
    from_date: str | None = None,
    to_date: str | None = None,
    session_id: str | None = None,
    data_source: str = "all",
) -> dict[str, Any]:
    log_dir = Path(log_dir)
    output_path = Path(output_path)
    paths = sorted(log_dir.glob("*.log"))

    if from_date:
        paths = [p for p in paths if str(p.stem) >= str(from_date)]
    if to_date:
        paths = [p for p in paths if str(p.stem) <= str(to_date)]

    events = load_all_events(paths)
    if session_id:
        events = [(sid, ev) for sid, ev in events if sid == str(session_id)]

    rows = export_routing_rows(events, reward_version=reward_version)
    ds = str(data_source or "all").strip().lower()
    if ds in {"real", "synthetic"}:
        rows = [r for r in rows if r.data_source == ds]
    elif ds != "all":
        raise ValueError("data_source must be one of: all, real, synthetic")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r.to_json_dict(), ensure_ascii=False) + "\n")

    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r.data_source] = by_source.get(r.data_source, 0) + 1

    meta = {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "reward_version": reward_version,
        "row_count": len(rows),
        "row_count_by_source": by_source,
        "source_logs": [str(p) for p in paths],
        "from_date": from_date,
        "to_date": to_date,
        "session_id_filter": session_id,
        "data_source_filter": ds,
        "min_rows_recommended": MIN_ROWS_RECOMMENDED,
        "below_recommended": len(rows) < MIN_ROWS_RECOMMENDED,
    }
    meta_path = output_path.with_suffix(output_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load_routing_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
