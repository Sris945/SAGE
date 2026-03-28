"""``sage run`` implementation.

Environment (see also ``docs/TRUST_AND_SCALE.md``):

- ``SAGE_MODEL_PROFILE=test`` — force one small local Ollama model for all roles (laptop / CI).
- ``SAGE_FORCE_LOCAL_MODEL=<tag>`` — same, but set the tag explicitly.
- ``SAGE_TRACE_ID`` — optional correlation id for structured JSON logs.
- ``SAGE_NO_CLARIFY=1`` — skip interactive planner clarifying questions (same as ``--no-clarify``).

Flags:

- ``--fresh`` — do not resume from ``memory/handoff.json``.
- ``--plan-only`` — print planner DAG and exit (no tools).
- ``--dry-run`` — skip applying patches (verification may fail).
- ``--include GLOB`` — repeatable scope hints for the planner.
"""

from __future__ import annotations

import os
import signal
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sage.cli.log_utils import print_routing_summary_for_session
from sage.version import get_version


def _install_interrupt_handler(state_ref: list, session_manager) -> None:
    """Install SIGINT/SIGTERM handler that writes handoff.json before exit."""

    def _handler(signum, frame):
        print("\n[SAGE] Interrupted — writing handoff snapshot...")
        try:
            current_state = state_ref[0] if state_ref else {}
            if current_state:
                session_manager.write_handoff_from_state(
                    current_state, reason="manual_interrupt"
                )
                print("[SAGE] Handoff saved. Resume with: sage run --resume")
        except Exception as e:
            print(f"[SAGE] Handoff write failed: {e}")
        raise SystemExit(1)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _print_run_header(*, mode: str, prompt: str, clarify: bool = True) -> None:
    try:
        from rich.panel import Panel
        from rich.rule import Rule

        from sage.cli.branding import get_console

        v = get_version()
        prompt_display = prompt[:500] + ("…" if len(prompt) > 500 else "")
        cwd = str(Path.cwd().resolve())
        if len(cwd) > 72:
            cwd = "…" + cwd[-69:]
        flow = (
            "[muted]flow[/muted]  [brand_dim]planner[/brand_dim] [muted]→[/muted] "
            "[brand_dim]code[/brand_dim] [muted]·[/muted] [brand_dim]docs[/brand_dim] [muted]→[/muted] "
            "[brand_dim]review[/brand_dim] [muted]→[/muted] [brand_dim]tests[/brand_dim] [muted]→[/muted] "
            "[brand_dim]verify[/brand_dim] [muted]→[/muted] [brand_dim]memory[/brand_dim]"
        )
        sep = "[muted]" + "─" * 42 + "[/muted]"
        clar = (
            "[muted]clarify[/muted]  [brand_dim]on[/brand_dim] — planner may ask questions (TTY)"
            if clarify
            else "[muted]clarify[/muted]  [brand_dim]off[/brand_dim]"
        )
        inner = (
            f"[brand]run[/brand]  [muted]v{v}[/muted]  [accent]{mode}[/accent]\n"
            f"[muted]{prompt_display}[/muted]\n"
            f"{sep}\n"
            f"{flow}\n"
            f"{clar}\n"
            f"[muted]workspace[/muted]  {cwd}"
        )
        c = get_console()
        c.print()
        c.print(
            Panel.fit(
                inner,
                border_style="#0d9488",
                title="[accent]SAGE[/accent] · [muted]autonomous run[/muted]",
                padding=(0, 1),
            )
        )
        c.print(Rule(style="rule", characters="─"))
        c.print()
        try:
            from sage.cli.branding import print_run_trust_strip

            print_run_trust_strip()
            c.print()
        except Exception:
            pass
    except Exception:
        print(f"\n[SAGE] v{get_version()} — starting (mode={mode})")
        print(f"[SAGE] Prompt: {prompt}\n")


def _print_run_summary(state: dict) -> None:
    """Structured narrative report: goal, plan, files, outcome (see ``SAGE_RUN_OUTPUT``)."""
    from sage.cli.run_output import build_run_report, print_run_report

    print_run_report(build_run_report(state if isinstance(state, dict) else {}))


def cmd_run(args) -> None:
    from sage.orchestrator import workflow as wf
    from sage.orchestrator.workflow import (
        HumanCancelledError,
        PlanEditRequestedError,
        PlanRejectedError,
    )

    app = wf.app
    repo_path = args.repo or ""
    if repo_path:
        os.chdir(repo_path)

    os.environ["SAGE_WORKSPACE_ROOT"] = str(Path.cwd().resolve())

    prompt_in = getattr(args, "prompt", "") or ""
    if isinstance(prompt_in, str) and prompt_in:
        from sage.cli.chat_session_store import maybe_prepend_chat_transcript

        prompt_in = maybe_prepend_chat_transcript(prompt_in)

    mode = "auto" if args.auto else ("silent" if args.silent else "research")
    clarify = not getattr(args, "no_clarify", False)
    if args.silent:
        clarify = False
    prev_session_id = os.environ.get("SAGE_SESSION_ID")
    new_session_id = uuid.uuid4().hex
    os.environ["SAGE_SESSION_ID"] = new_session_id
    initial_state = {
        "user_prompt": prompt_in,
        "enhanced_prompt": "",
        "task_dag": {},
        "current_task": {},
        "current_task_id": "",
        "agent_output": {},
        "execution_result": {},
        "debug_attempts": 0,
        "session_memory": {
            "run_started_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "pending_patch_request": {},
        "pending_patch_source": "",
        "pending_fix_pattern_context": {},
        "artifacts_by_task": {},
        "architect_blueprints_by_task": {},
        "verification_passed": False,
        "verification_needs_tool_apply": False,
        "orchestrator_escalation": False,
        "task_updates": [],
        "repo_path": repo_path,
        "repo_mode": "greenfield",
        "last_error": "",
        "fix_pattern_hit": False,
        "fix_pattern_applied": False,
        "max_retries": 5,
        "events": [],
        "mode": mode,
        "resume_from_handoff": False,
        "skip_handoff": bool(getattr(args, "fresh", False)),
        "plan_only": bool(getattr(args, "plan_only", False)),
        "dry_run": bool(getattr(args, "dry_run", False)),
        "cli_scope_globs": list(getattr(args, "include_globs", None) or []),
        "_test_emit_guard": {},
        "clarify": clarify,
    }
    _print_run_header(mode=mode, prompt=args.prompt, clarify=clarify)
    prev_shell_mode: str | None = None
    if os.environ.get("SAGE_INSIDE_SHELL"):
        prev_shell_mode = os.environ.get("SAGE_SHELL_MODE")
        os.environ["SAGE_SHELL_MODE"] = "run"
    last_tick: dict = dict(initial_state)
    # Mutable ref so signal handler can always access the latest state
    state_ref: list[dict] = [last_tick]
    try:
        from sage.orchestrator.session_manager import SessionManager

        _install_interrupt_handler(state_ref, SessionManager())
    except Exception:
        pass
    try:
        if wf._HAS_LANGGRAPH:
            for update in app.stream(initial_state, stream_mode="values"):
                last_tick = update
                state_ref[0] = last_tick
        else:
            last_tick = app.invoke(initial_state)
            state_ref[0] = last_tick
            sticky = getattr(app, "_last_graph_state", None)
            if isinstance(sticky, dict):
                last_tick = sticky
                state_ref[0] = last_tick
        if getattr(args, "explain_routing", False):
            print_routing_summary_for_session(new_session_id)
        _print_run_summary(last_tick if isinstance(last_tick, dict) else {})
    except PlanEditRequestedError as e:
        try:
            from sage.cli.branding import get_console

            get_console().print(f"  [muted]{e}[/muted]")
        except Exception:
            print(str(e))
        return
    except PlanRejectedError as e:
        try:
            from sage.cli.branding import get_console

            get_console().print(f"  [accent]{e}[/accent]")
        except Exception:
            print(str(e))
        raise SystemExit(3) from None
    except HumanCancelledError as e:
        try:
            from sage.cli.branding import get_console

            get_console().print(f"  [muted]{e}[/muted]")
        except Exception:
            print(str(e))
        raise SystemExit(3) from None
    except KeyboardInterrupt:
        try:
            from sage.orchestrator.handoff_payload import persist_interrupt_handoff

            persist_interrupt_handoff(last_tick, reason="keyboard_interrupt")
        except Exception:
            pass
        try:
            from sage.cli.branding import get_console

            get_console().print(
                "  [muted]Interrupted — handoff written to memory/handoff.json (if writable).[/muted]"
            )
        except Exception:
            print("\n[SAGE] Interrupted — handoff saved when possible (memory/handoff.json).")
        if os.environ.get("SAGE_INSIDE_SHELL"):
            return
        raise SystemExit(130) from None
    finally:
        try:
            from sage.observability.run_metrics import write_run_metrics_json

            lt = last_tick if isinstance(last_tick, dict) else {}
            p = write_run_metrics_json(lt, base_dir=Path.cwd())
            if p and (os.environ.get("SAGE_RUN_OUTPUT") or "").strip().lower() == "debug":
                try:
                    from sage.cli.branding import get_console

                    get_console().print(f"  [muted]metrics[/muted] {p.resolve()}")
                except Exception:
                    print(f"[SAGE] metrics written: {p}")
        except Exception:
            pass
        if prev_session_id is None:
            os.environ.pop("SAGE_SESSION_ID", None)
        else:
            os.environ["SAGE_SESSION_ID"] = prev_session_id
        if os.environ.get("SAGE_INSIDE_SHELL"):
            if prev_shell_mode is not None:
                os.environ["SAGE_SHELL_MODE"] = prev_shell_mode
            else:
                os.environ["SAGE_SHELL_MODE"] = "shell"
