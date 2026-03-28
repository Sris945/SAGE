"""
Human-readable run reports for ``sage run`` (plan, artifacts, outcome).

Verbosity: ``SAGE_RUN_OUTPUT`` = ``summary`` (default) | ``full`` | ``debug``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def run_output_level() -> str:
    """``summary`` — narrative report; minimal live verify noise. ``full`` — short verify labels. ``debug`` — raw verify lines."""
    raw = (os.environ.get("SAGE_RUN_OUTPUT") or "summary").strip().lower()
    if raw in ("debug", "full", "summary"):
        return raw
    return "summary"


@dataclass
class RunReport:
    goal: str
    plan_only: bool
    dry_run: bool
    tasks: list[dict] = field(default_factory=list)
    """Each: id, status, description, assigned_agent."""
    artifacts: list[tuple[str, str]] = field(default_factory=list)
    """(task_id, relative path)."""
    last_error: str = ""
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    how_to_run_hint: str = ""
    metrics_path: str = ""
    """Path to ``.sage/last_run_metrics.json`` when present."""
    orchestrator_interventions: int | None = None
    human_checkpoints_reached: int | None = None


def _truncate(s: str, max_len: int = 160) -> str:
    t = (s or "").replace("\n", " ").strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _how_to_run_guess(state: dict) -> str:
    arts = state.get("artifacts_by_task") or {}
    paths = [str(p).replace("\\", "/").lower() for p in arts.values() if p]
    if any("src/app.py" in p or p.endswith("/app.py") for p in paths):
        return (
            "Typical run: [accent]PYTHONPATH=src uvicorn app:app --reload[/accent] "
            "[muted](from project root)[/muted]"
        )
    if any("README" in str(p) for p in arts.values()):
        return "See [accent]README.md[/accent] in the project for install and run commands."
    return ""


def build_run_report(state: dict) -> RunReport:
    """Build a report from post-run workflow state."""
    if not isinstance(state, dict):
        state = {}
    goal = _truncate(
        str(state.get("enhanced_prompt") or state.get("user_prompt") or "").strip(),
        600,
    )
    dag = state.get("task_dag") or {}
    nodes = dag.get("nodes") or []
    tasks: list[dict] = []
    completed = failed = blocked = 0
    for n in nodes:
        if not isinstance(n, dict):
            continue
        st = str(n.get("status") or "pending")
        if st == "completed":
            completed += 1
        elif st == "failed":
            failed += 1
        elif st == "blocked":
            blocked += 1
        tasks.append(
            {
                "id": str(n.get("id", "")),
                "status": st,
                "description": _truncate(str(n.get("description", "")), 200),
                "assigned_agent": str(n.get("assigned_agent", "")),
            }
        )
    artifacts: list[tuple[str, str]] = []
    ab = state.get("artifacts_by_task") or {}
    if isinstance(ab, dict):
        for tid, path in sorted(ab.items()):
            if path:
                artifacts.append((str(tid), str(path)))
    err = (state.get("last_error") or "").strip()
    hint = _how_to_run_guess(state)

    metrics_path = ""
    orch_iv = None
    chk_n = None
    try:
        mp = Path.cwd() / ".sage" / "last_run_metrics.json"
        if mp.is_file():
            metrics_path = str(mp.resolve())
            data = json.loads(mp.read_text(encoding="utf-8"))
            orch_iv = data.get("orchestrator_interventions")
            chk_n = data.get("human_checkpoints_reached")
    except Exception:
        pass

    return RunReport(
        goal=goal or "[muted](no goal text in state)[/muted]",
        plan_only=bool(state.get("plan_only")),
        dry_run=bool(state.get("dry_run")),
        tasks=tasks,
        artifacts=artifacts,
        last_error=err,
        completed=completed,
        failed=failed,
        blocked=blocked,
        how_to_run_hint=hint,
        metrics_path=metrics_path,
        orchestrator_interventions=orch_iv,
        human_checkpoints_reached=chk_n,
    )


def humanize_verify_command(command: str) -> str:
    """Short label for ``full`` mode (not full argv)."""
    c = (command or "").strip()
    if not c:
        return "check"
    low = c.lower()
    m = re.search(r"py_compile\s+(\S+)", low)
    if m:
        return f"Compile {m.group(1)}"
    if "pytest" in low:
        return "Run pytest"
    if "pip install" in low or "pip install" in c:
        return "pip install (requirements)"
    if "import app" in low or "import app" in c:
        return "Import app module"
    if "readme" in low or "path(" in low:
        return "Documentation check"
    if "requirements" in low:
        return "Requirements check"
    if " -c " in c or ' -c"' in c:
        return "Python one-liner check"
    return "Verification step"


def print_run_report(report: RunReport, *, level: str | None = None) -> None:
    """Rich panels: goal, plan table, files, hints, outcome."""
    level = level or run_output_level()
    try:
        from rich import box
        from rich.markup import escape
        from rich.panel import Panel
        from rich.table import Table

        from sage.cli.branding import get_console

        c = get_console()
        c.print()

        if report.plan_only:
            c.print("[accent]Plan only[/accent] [muted]— no execution ran.[/muted]\n")
        if report.dry_run:
            c.print("[accent]Dry run[/accent] [muted]— patches were not applied.[/muted]\n")

        # Goal
        c.print(
            Panel.fit(
                f"[white]{escape(report.goal)}[/white]",
                title="[brand]Goal[/brand]",
                border_style="#0d9488",
                padding=(0, 1),
            )
        )
        c.print()

        # Plan / tasks
        if report.tasks:
            table = Table(
                show_header=True,
                header_style="bold #5eead4",
                border_style="#334155",
                box=box.SIMPLE,
            )
            table.add_column("Task", style="#94a3b8", no_wrap=True)
            table.add_column("Status", no_wrap=True)
            table.add_column("Agent", style="dim", no_wrap=True)
            table.add_column("Description", width=48)
            for t in report.tasks:
                st = t.get("status", "")
                if st == "completed":
                    st_cell = "[bold green]" + escape(st) + "[/]"
                elif st == "failed":
                    st_cell = "[bold red]" + escape(st) + "[/]"
                else:
                    st_cell = "[dim]" + escape(st) + "[/]"
                table.add_row(
                    escape(str(t.get("id", ""))),
                    st_cell,
                    escape(str(t.get("assigned_agent", ""))),
                    escape(_truncate(t.get("description", ""), 120)),
                )
            c.print(Panel(table, title="[brand]Plan[/brand]", border_style="#0f766e"))
            c.print()

        # Files
        if report.artifacts:
            lines = ["[bold]•[/bold] " + p for _, p in report.artifacts]
            body = "\n".join(lines[:40])
            if len(report.artifacts) > 40:
                body += f"\n[dim]… +{len(report.artifacts) - 40} more[/dim]"
            c.print(
                Panel.fit(
                    body,
                    title="[brand]Files touched[/brand]",
                    border_style="#0f766e",
                    padding=(0, 1),
                )
            )
            c.print()

        if report.how_to_run_hint:
            c.print(
                Panel.fit(
                    report.how_to_run_hint,
                    title="[brand]How to run[/brand]",
                    border_style="#0f766e",
                    padding=(0, 1),
                )
            )
            c.print()

        # Outcome
        bits = [
            f"[muted]completed[/muted] [brand]{report.completed}[/brand]",
            f"[muted]failed[/muted] [accent]{report.failed}[/accent]",
            f"[muted]blocked[/muted] {report.blocked}",
        ]
        foot = "  ·  ".join(bits)
        if report.last_error:
            foot += (
                f"\n[accent]Error[/accent]\n[muted]{escape(report.last_error[:900])}"
                f"{'…' if len(report.last_error) > 900 else ''}[/muted]"
            )
        handoff = Path("memory") / "handoff.json"
        if handoff.is_file():
            foot += f"\n[muted]handoff[/muted] {handoff.resolve()} [muted](resume next run unless --fresh)[/muted]"
        if level == "full" and report.metrics_path:
            foot += f"\n[muted]metrics[/muted] {report.metrics_path}"
            if report.human_checkpoints_reached is not None:
                foot += f"\n[muted]human checkpoints[/muted] {report.human_checkpoints_reached}"
            if report.orchestrator_interventions is not None:
                foot += f"  [muted]orchestrator interventions[/muted] {report.orchestrator_interventions}"
        if level == "debug":
            foot += "\n[dim]SAGE_RUN_OUTPUT=debug — full verify lines were printed above.[/dim]"

        c.print(
            Panel.fit(
                foot,
                title="[brand]Outcome[/brand]",
                border_style="#0f766e" if report.failed == 0 else "#b45309",
                padding=(0, 1),
            )
        )
        c.print()
    except Exception:
        _print_run_report_plain(report)


def _print_run_report_plain(report: RunReport) -> None:
    print("\n--- Goal ---")
    print(report.goal)
    print("\n--- Plan ---")
    for t in report.tasks:
        print(
            f"  {t.get('id')} [{t.get('status')}] {t.get('assigned_agent')}: {t.get('description')}"
        )
    if report.artifacts:
        print("\n--- Files ---")
        for _, p in report.artifacts:
            print(f"  {p}")
    print("\n--- Outcome ---")
    print(f"  completed={report.completed} failed={report.failed} blocked={report.blocked}")
    if report.last_error:
        print(f"  error: {report.last_error[:500]}")
