#!/usr/bin/env python3
"""
SAGE CLI Entry Point
--------------------
Usage:
  sage                          # TTY: interactive shell (activation); else help
  sage commands                 # full command catalog (same as /commands in shell)
  sage init                     # scaffold .sage/ + memory/ in this folder
  sage run "your prompt"        # run pipeline
  sage run "prompt" --auto      # no human checkpoints except circuit breaker
  sage run "prompt" --silent    # fully autonomous, skip failed tasks
  sage status                   # show current session state
  sage memory                   # inspect memory layers
  sage permissions              # show policy; `permissions set …` persists in .sage/policy.json
  sage bench                    # run benchmark suite (Phase 4)
  sage bench --compare-policy   # static vs learned routing (Phase 5)
  sage rl export / train-bc     # offline RL dataset + BC (Phase 5)
  sage sim generate / run       # oracle tasks + parallel pytest (Phase 6)

Interactive shell: ``/help``, ``/commands``, ``/skill``, ``/model``, ``/context``, ``/clear``.
Commands run in-process (no subprocess per line).

Non-interactive / CI: set SAGE_NON_INTERACTIVE=1 so bare ``sage`` prints help instead of the shell.
"""

import argparse
from argparse import ArgumentError
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import yaml

from sage.utils.retry import retry_call
from sage.version import get_version

from sage.cli.exit_codes import EX_USAGE
from sage.cli.permissions_cmd import cmd_permissions
from sage.cli.run_cmd import cmd_run


def _write_bench_artifact(results: dict, out_arg: str | None) -> Path | None:
    if not out_arg:
        return None
    out_path = Path(out_arg)
    if out_path.exists() and out_path.is_dir():
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        out_path = out_path / f"bench_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return out_path


def _write_bench_run_pack(
    *,
    results: dict,
    compare_policy: bool,
    run_pack_dir: str,
    bench_artifact_path: Path | None,
) -> Path:
    """
    Write a reproducible benchmark run-pack directory:
      - bench_result.json
      - manifest.json
    """
    pack_dir = Path(run_pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    result_file = pack_dir / "bench_result.json"
    result_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "bench_run_pack_v1",
        "created_at": created_at,
        "compare_policy": bool(compare_policy),
        "command": ("sage bench --compare-policy" if compare_policy else "sage bench"),
        "result_file": str(result_file),
        "external_out_file": str(bench_artifact_path) if bench_artifact_path else None,
        "summary": {
            "status": results.get("status"),
            "compare_mode": bool(results.get("compare_mode", False)),
            "benchmark_count": len(results.get("benchmarks") or []),
        },
        "ollama_bench_profile": results.get("ollama_bench_profile", {}),
    }
    manifest_path = pack_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return pack_dir


def _load_models_config(path: Path | None = None) -> dict:
    from sage.config.paths import resolved_models_yaml_path

    p = path if path is not None else resolved_models_yaml_path()
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("models.yaml must parse into a mapping")
    return data


def _models_config_path() -> Path:
    from sage.config.paths import resolved_models_yaml_path

    return resolved_models_yaml_path()


def _save_models_config(data: dict, path: Path | None = None) -> None:
    if path is not None:
        p = path
    else:
        from sage.config.paths import user_config_dir

        override = (os.environ.get("SAGE_MODELS_YAML") or "").strip()
        if override:
            p = Path(override).expanduser().resolve()
        else:
            p = user_config_dir() / "models.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def _configured_model_names(cfg: dict) -> list[str]:
    routing = cfg.get("routing", {})
    if not isinstance(routing, dict):
        return []
    names: set[str] = set()
    for role_cfg in routing.values():
        if not isinstance(role_cfg, dict):
            continue
        for key in ("primary", "fallback"):
            val = str(role_cfg.get(key, "")).strip()
            if val:
                names.add(val)
    return sorted(names)


def _parse_ollama_models(ollama_list_output: str) -> set[str]:
    models: set[str] = set()
    for line in (ollama_list_output or "").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        first = parts[0]
        if first.upper() == "NAME":
            continue
        models.add(first)
    return models


def _is_external_model_alias(name: str) -> bool:
    n = (name or "").strip().lower()
    return (
        n.startswith("claude")
        or n.startswith("gpt-")
        or n.startswith("o1")
        or n.startswith("o3")
        or n.startswith("openai:")
        or n.startswith("anthropic:")
    )


def _validate_models_config(data: dict) -> list[str]:
    errs: list[str] = []
    routing = data.get("routing")
    if not isinstance(routing, dict) or not routing:
        errs.append("routing must be a non-empty mapping")
        return errs
    for role, cfg in routing.items():
        if not isinstance(cfg, dict):
            errs.append(f"routing.{role} must be a mapping")
            continue
        if not str(cfg.get("primary", "")).strip():
            errs.append(f"routing.{role}.primary missing/empty")
        if not str(cfg.get("fallback", "")).strip():
            errs.append(f"routing.{role}.fallback missing/empty")
        triggers = cfg.get("fallback_triggers", [])
        if triggers is not None and not isinstance(triggers, list):
            errs.append(f"routing.{role}.fallback_triggers must be a list")
    return errs


def _health_score_from_checks(checks: dict[str, dict]) -> dict:
    """
    Convert doctor check results into a simple readiness score.

    Inspired by health-style checkers: critical failures -> unhealthy,
    only optional failures -> degraded, otherwise healthy.
    """
    critical = [
        "python",
        "venv",
        "memory_dir_writable",
        "models_yaml",
    ]
    optional = [
        "ollama",
        "docker",
        "configured_models_present",
    ]

    critical_failed = [k for k in critical if not checks.get(k, {}).get("ok", False)]
    optional_failed = [k for k in optional if not checks.get(k, {}).get("ok", False)]

    if critical_failed:
        status = "unhealthy"
    elif optional_failed:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "critical_failed": sorted(critical_failed),
        "optional_failed": sorted(optional_failed),
    }


def cmd_init(args) -> None:
    """Bootstrap `.sage/` and `memory/` under ``--path``."""
    from sage.cli.branding import get_console
    from sage.cli.workspace_init import init_workspace

    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    force = bool(getattr(args, "force", False))
    summary = init_workspace(root, force=force)
    c = get_console()
    c.print("  [accent]Workspace[/accent] [muted]— SAGE project files[/muted]")
    for p in summary.get("created") or []:
        c.print(f"  [brand_dim]+[/brand_dim] {p}")
    for p in summary.get("updated") or []:
        c.print(f"  [accent]~[/accent] {p}")
    c.print(f"  [muted]Root:[/muted] {summary.get('root')}")
    c.print()


def cmd_doctor(args) -> None:
    checks: dict[str, dict] = {}

    if not getattr(args, "json", False):
        from sage.cli.branding import print_banner

        print_banner(tagline=False)

    checks["python"] = {"ok": sys.version_info >= (3, 10), "detail": sys.version.split()[0]}
    checks["venv"] = {"ok": Path(".venv").exists(), "detail": str(Path(".venv").resolve())}
    checks["memory_dir_writable"] = {"ok": True, "detail": "memory/"}
    try:
        Path("memory").mkdir(parents=True, exist_ok=True)
        probe = Path("memory/.doctor_probe")
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as e:
        checks["memory_dir_writable"] = {"ok": False, "detail": str(e)}

    # models.yaml validity
    try:
        models = _load_models_config()
        errs = _validate_models_config(models)
        checks["models_yaml"] = {"ok": len(errs) == 0, "detail": "ok" if not errs else errs}
    except Exception as e:
        checks["models_yaml"] = {"ok": False, "detail": str(e)}

    # optional external dependencies
    def _cmd_ok(cmd: list[str]) -> tuple[bool, str]:
        try:
            r = retry_call(
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=5),
                retries=2,
                initial_delay_s=0.1,
                backoff=2.0,
            )
            return (r.returncode == 0), (r.stdout.strip() or r.stderr.strip())
        except Exception as e:  # pragma: no cover
            return False, str(e)

    ok_ollama, out_ollama = _cmd_ok(["ollama", "list"])
    checks["ollama"] = {"ok": ok_ollama, "detail": out_ollama[:400]}

    ok_docker, out_docker = _cmd_ok(["docker", "version"])
    checks["docker"] = {"ok": ok_docker, "detail": out_docker[:400]}

    # Check configured model presence with hybrid awareness:
    # - local models must exist in `ollama list`
    # - external/cloud aliases are reported separately, not as missing local models
    if checks.get("models_yaml", {}).get("ok") and ok_ollama:
        try:
            cfg = _load_models_config()
            cfg_models = _configured_model_names(cfg)
            local_models = _parse_ollama_models(out_ollama)
            external_configured = [m for m in cfg_models if _is_external_model_alias(m)]
            local_configured = [m for m in cfg_models if not _is_external_model_alias(m)]
            missing_local = [m for m in local_configured if m not in local_models]
            checks["configured_models_present"] = {
                "ok": len(missing_local) == 0,
                "detail": (
                    "all configured models found"
                    if not missing_local
                    else {
                        "missing_local": missing_local,
                        "external_configured": external_configured,
                        "hint": "pull missing model(s): ollama pull <model>",
                    }
                ),
            }
        except Exception as e:
            checks["configured_models_present"] = {"ok": False, "detail": str(e)}

    # Health-style scoring summary.
    checks["health_summary"] = _health_score_from_checks(checks)

    if getattr(args, "json", False):
        print(json.dumps(checks, indent=2))
        return

    from sage.cli.branding import get_console

    dc = get_console()
    dc.print("  [accent]doctor[/accent] [muted]— environment & models[/muted]")
    dc.print(
        "  [muted]Hint:[/muted] cap session logs with [accent]SAGE_SESSION_LOG_MAX_MB[/accent] "
        "[muted](see docs/runbook_failures.md).[/muted]"
    )
    dc.print(
        "  [muted]Ollama:[/muted] chat waits are unbounded by default; set "
        "[accent]SAGE_OLLAMA_CHAT_TIMEOUT_S[/accent] [muted](seconds) to cap. "
        "[accent]SAGE_DISABLE_OLLAMA_SPINNER=1[/accent] [muted]disables stderr loading animation.[/muted]"
    )
    # Display health summary first to make it obvious what to fix.
    hs = checks.get("health_summary") or {}
    overall = hs.get("status")
    if overall:
        print(f"[SAGE doctor] health_status={overall}")
    for name, item in checks.items():
        if name == "health_summary":
            continue
        status = "OK" if item.get("ok") else "FAIL"
        print(f"  - {name}: {status}")
        detail = item.get("detail")
        if detail:
            if isinstance(detail, list):
                for d in detail:
                    print(f"      * {d}")
            else:
                print(f"      {str(detail)[:400]}")
    print("  - health_summary:")
    print(f"      {json.dumps(checks.get('health_summary', {}), ensure_ascii=True)}")


def build_parser(*, exit_on_error: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sage",
        description="SAGE — prompt → production",
        epilog=(
            "Quickstart:\n"
            "  sage init                    # .sage/ + memory/ here\n"
            "  sage prep                    # recommended models for your hardware\n"
            "  sage setup scan && sage setup suggest\n"
            "  sage doctor\n"
            "  sage config show\n"
            '  sage run "your prompt" --auto        # planner may ask clarifying questions (TTY)\n'
            '  sage run "…" --auto --no-clarify     # skip planner Q&A for a fast run\n'
            "  sage shell                   # interactive (same as bare `sage` in a TTY)\n"
            "  sage session reset             # clear memory/system_state.json; new session id\n"
            "\n"
            "Bare `sage` in a terminal opens the interactive shell. "
            "Set SAGE_NON_INTERACTIVE=1 to print help instead.\n"
            "\n"
            "Ollama: SAGE_OLLAMA_CHAT_TIMEOUT_S sets a max wait in seconds (default: unlimited). "
            "SAGE_DISABLE_OLLAMA_SPINNER=1 turns off the stderr loading animation.\n"
            "\n"
            "Development: from the repo run `pip install -e .` (use a venv), then `rehash` / "
            "`hash -r` so `which sage` points at that install; SAGE_SHELL_DEBUG=1 shows loaded paths.\n"
            "\nExit codes: 0 success, 1 user/config error, 2 internal failure.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        exit_on_error=exit_on_error,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run the SAGE pipeline")
    run_p.add_argument("prompt", help="Natural language goal")
    run_p.add_argument(
        "--auto", action="store_true", help="Skip checkpoints except circuit breaker"
    )
    run_p.add_argument(
        "--no-clarify",
        action="store_true",
        help="Skip interactive planner clarifying questions (still runs the DAG)",
    )
    run_p.add_argument("--silent", action="store_true", help="Fully autonomous, skip failed tasks")
    run_p.add_argument(
        "--repo",
        default="",
        help="Path to existing/unfinished repo (enables codebase intelligence)",
    )
    run_p.add_argument(
        "--explain-routing",
        action="store_true",
        help="After run, print a routing decision summary for this session.",
    )

    sub.add_parser("status", help="Show current session state")
    sub.add_parser(
        "commands",
        help="Print the full command catalog (same as /commands in the interactive shell)",
    )
    sub.add_parser("memory", help="Inspect memory layers")
    perm_p = sub.add_parser(
        "permissions",
        help="Show or set workspace + tool policy (see `sage permissions set …`)",
    )
    perm_p.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output (show only; not for set/reset)",
    )
    perm_sub = perm_p.add_subparsers(dest="permissions_command", required=False)
    perm_set = perm_sub.add_parser(
        "set",
        help="Write .sage/policy.json and apply SAGE_* in this process",
    )
    perm_set_sub = perm_set.add_subparsers(dest="permissions_set_command", required=True)
    perm_set_pol = perm_set_sub.add_parser(
        "policy",
        help="standard | strict — strict limits run_command to an allowlist",
    )
    perm_set_pol.add_argument("value", choices=["standard", "strict"])
    perm_set_ws = perm_set_sub.add_parser(
        "workspace",
        help="Workspace root(s); same syntax as SAGE_WORKSPACE_ROOT; use 'clear' to drop saved override",
    )
    perm_set_ws.add_argument("value")
    perm_set_sk = perm_set_sub.add_parser(
        "skills",
        help="Override skills tree; use 'clear' for bundled package skills",
    )
    perm_set_sk.add_argument("value")
    perm_sub.add_parser(
        "reset",
        help="Delete .sage/policy.json and unset SAGE_TOOL_POLICY, SAGE_WORKSPACE_ROOT, SAGE_SKILLS_ROOT",
    )
    sub.add_parser(
        "shell", help="Interactive slash-command shell (default when bare `sage` in a TTY)"
    )

    init_p = sub.add_parser(
        "init",
        help="Create .sage/ + memory/ in this folder (bootstrap project for SAGE)",
    )
    init_p.add_argument(
        "--path",
        default=".",
        help="Project root (default: current directory)",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite .sage/rules.md if it already exists",
    )

    setup_p = sub.add_parser("setup", help="Hardware scan, Ollama models, or workspace init")
    setup_sub = setup_p.add_subparsers(dest="setup_command", required=True)
    setup_scan = setup_sub.add_parser("scan", help="Detect OS, RAM, GPU VRAM (best effort)")
    setup_scan.add_argument("--json", action="store_true", help="Machine-readable output")
    setup_sug = setup_sub.add_parser(
        "suggest", help="Suggest Ollama tags + routing tier for this machine"
    )
    setup_sug.add_argument(
        "--disk-budget",
        type=float,
        default=18.0,
        help="Approximate disk budget for model pulls (GiB).",
    )
    setup_sug.add_argument("--json", action="store_true")
    setup_apply = setup_sub.add_parser("apply", help="Write suggested routing into models.yaml")
    setup_apply.add_argument(
        "--disk-budget",
        type=float,
        default=18.0,
    )
    setup_apply.add_argument(
        "--models-yaml",
        default=None,
        help="Path to models.yaml (default: packaged src/sage/config/models.yaml)",
    )
    setup_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merged YAML as JSON instead of writing",
    )
    setup_pull = setup_sub.add_parser("pull", help="Run ollama pull for suggested tags")
    setup_pull.add_argument("--disk-budget", type=float, default=18.0)
    setup_pull.add_argument("--json", action="store_true")
    setup_init = setup_sub.add_parser(
        "init",
        help="Create .sage/ + memory/ here (same as `sage init`)",
    )
    setup_init.add_argument("--path", default=".", help="Project root (default: current directory)")
    setup_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite .sage/rules.md if it already exists",
    )

    doctor_p = sub.add_parser("doctor", help="Check environment/model readiness")
    doctor_p.add_argument("--json", action="store_true", help="Emit doctor report as JSON")

    config_p = sub.add_parser("config", help="Inspect/validate config")
    config_sub = config_p.add_subparsers(dest="config_command", required=True)
    cfg_show = config_sub.add_parser("show", help="Show routing config summary")
    cfg_show.add_argument("--json", action="store_true", help="Print full config JSON")
    config_sub.add_parser("validate", help="Validate models.yaml structure")
    cfg_migrate = config_sub.add_parser(
        "migrate",
        help="Copy bundled models.yaml to user config dir (~/.config/sage/models.yaml)",
    )
    cfg_migrate.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing user models.yaml",
    )
    config_sub.add_parser("paths", help="Print resolved models.yaml path and user config dir")
    cfg_set = config_sub.add_parser("set", help="Update routing role model settings")
    cfg_set.add_argument("--role", required=True, help="Routing role (e.g. coder)")
    cfg_set.add_argument("--primary", default=None, help="Set primary model")
    cfg_set.add_argument("--fallback", default=None, help="Set fallback model")
    cfg_set.add_argument(
        "--trigger",
        action="append",
        default=None,
        help="Set fallback trigger expression; repeat flag for multiple triggers.",
    )

    bench_p = sub.add_parser("bench", help="Run benchmark suite [Phase 4]")
    bench_p.add_argument(
        "--compare-policy",
        action="store_true",
        help="Run suite twice: SAGE_RL_POLICY=0 vs 1 (requires checkpoint for learned run).",
    )
    bench_p.add_argument(
        "--out",
        default=None,
        help="Write benchmark JSON artifact to this path (e.g. memory/benchmarks/run.json).",
    )
    bench_p.add_argument(
        "--run-pack-dir",
        default=None,
        help="Write benchmark run pack (result + manifest) into this directory.",
    )

    rl_p = sub.add_parser("rl", help="Offline RL dataset export and training")
    rl_sub = rl_p.add_subparsers(dest="rl_command", required=True)
    rl_exp = rl_sub.add_parser("export", help="Export session logs to routing JSONL")
    rl_exp.add_argument("--log-dir", default="memory/sessions", help="Directory of *.log files")
    rl_exp.add_argument("--output", default="datasets/routing_v1.jsonl", help="Output JSONL path")
    rl_exp.add_argument("--from-date", default=None, help="YYYY-MM-DD (inclusive)")
    rl_exp.add_argument("--to-date", default=None, help="YYYY-MM-DD (inclusive)")
    rl_exp.add_argument("--session-id", default=None, help="Filter to a single session_id")
    rl_exp.add_argument(
        "--data-source",
        choices=["all", "real", "synthetic"],
        default="all",
        help="Filter exported rows by provenance label.",
    )
    rl_collect = rl_sub.add_parser(
        "collect-synth", help="Append synthetic TRAJECTORY_STEP rows to session log"
    )
    rl_collect.add_argument("--rows", type=int, default=600)
    rl_collect.add_argument("--seed", type=int, default=42)
    rl_an = rl_sub.add_parser("analyze-rewards", help="Write a reward distribution report JSON")
    rl_an.add_argument("--data", default="datasets/routing_v1.jsonl")
    rl_an.add_argument("--out", default="datasets/reward_report.json")
    rl_eval = rl_sub.add_parser(
        "eval-offline", help="Offline eval: compare checkpoint vs dataset baseline"
    )
    rl_eval.add_argument("--data", default="datasets/routing_v1.jsonl")
    rl_eval.add_argument("--checkpoint", required=True)
    rl_eval.add_argument("--out", default="datasets/offline_eval.json")
    rl_eval.add_argument("--min-confidence", type=float, default=0.0)
    rl_train = rl_sub.add_parser("train-bc", help="Train behavior cloning (sklearn) per agent role")
    rl_train.add_argument("--data", required=True, help="routing_v1.jsonl from export")
    rl_train.add_argument("--out", default="memory/rl/policy_bc.joblib", help="Checkpoint path")
    rl_cql = rl_sub.add_parser(
        "train-cql", help="Train conservative offline policy (CQL-style, bandit)"
    )
    rl_cql.add_argument("--data", default="datasets/routing_v1.jsonl")
    rl_cql.add_argument("--out", default="memory/rl/policy_cql.joblib")

    sim_p = sub.add_parser("sim", help="Simulator oracle tasks and parallel runs")
    sim_sub = sim_p.add_subparsers(dest="sim_command", required=True)
    sim_gen = sim_sub.add_parser("generate", help="Write oracle task JSONL (1000+ tasks)")
    sim_gen.add_argument("--out", default="datasets/sim_tasks.jsonl")
    sim_gen.add_argument("--count", type=int, default=1000)
    sim_gen.add_argument("--seed", type=int, default=42)
    sim_run = sim_sub.add_parser("run", help="Run pytest over a task JSONL in parallel")
    sim_run.add_argument("--tasks", required=True, help="JSONL from sim generate")
    sim_run.add_argument("--workers", type=int, default=4)
    sim_run.add_argument("--limit", type=int, default=None)
    sim_run.add_argument("--docker", action="store_true", help="Run pytest inside Docker sandboxes")

    cron_p = sub.add_parser("cron", help="Run scheduled maintenance jobs")
    cron_p.add_argument(
        "job",
        choices=["weekly-memory-optimizer"],
        help="Job name to run immediately (cron should schedule this).",
    )

    eval_p = sub.add_parser("eval", help="Trust checks (golden trace + optional Ollama smoke)")
    eval_sub = eval_p.add_subparsers(dest="eval_command", required=True)
    eval_sub.add_parser(
        "golden",
        help="Golden trace ordering (fixture + mocks; no Ollama)",
    )
    eval_sub.add_parser(
        "e2e",
        help="Mocked greenfield full pipeline (pytest tests/e2e; no Ollama)",
    )
    eval_sub.add_parser(
        "smoke",
        help="Run tests/integration with SAGE_MODEL_PROFILE=test (needs `ollama` + small model)",
    )

    prep_p = sub.add_parser(
        "prep",
        help="Scan hardware and print recommended Ollama models + pull list",
    )
    prep_p.add_argument(
        "--disk-budget",
        type=float,
        default=18.0,
        help="Approximate disk budget for model pulls (GiB).",
    )
    prep_p.add_argument("--json", action="store_true", help="Machine-readable output")

    session_p = sub.add_parser(
        "session",
        help="Session: reset saved state, refresh view from disk, or show status",
    )
    session_sub = session_p.add_subparsers(dest="session_command", required=True)
    session_sub.add_parser(
        "reset",
        help="Delete memory/system_state.json and set a new SAGE_SESSION_ID (fresh bookkeeping)",
    )
    session_sub.add_parser(
        "refresh",
        help="Re-print session state from disk (same as sage status)",
    )
    session_sub.add_parser(
        "status",
        help="Show session state (alias of sage status)",
    )

    return parser


def _dispatch_command_impl(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.command == "shell":
        if os.environ.get("SAGE_INSIDE_SHELL"):
            from sage.cli.branding import get_console

            get_console().print("  [muted]Already in the SAGE shell. Use /exit to quit.[/muted]")
            return
        cmd_shell(args)
        return
    if args.command == "commands":
        from sage.cli.shell_support import print_commands_table

        print_commands_table()
        return
    if args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "memory":
        cmd_memory(args)
    elif args.command == "permissions":
        cmd_permissions(args)
    elif args.command == "bench":
        from sage.benchmarks.runner import run_benchmarks

        results = run_benchmarks(compare_policy=bool(getattr(args, "compare_policy", False)))
        print("[SAGE] Bench results:")
        print(json.dumps(results, indent=2))
        out_path = _write_bench_artifact(results, getattr(args, "out", None))
        if getattr(args, "run_pack_dir", None):
            pack_dir = _write_bench_run_pack(
                results=results,
                compare_policy=bool(getattr(args, "compare_policy", False)),
                run_pack_dir=str(args.run_pack_dir),
                bench_artifact_path=out_path,
            )
            print(f"[SAGE] Bench run pack written: {pack_dir}")
    elif args.command == "rl":
        if args.rl_command == "export":
            from sage.rl.export_dataset import export_logs_to_jsonl

            meta = export_logs_to_jsonl(
                log_dir=Path(args.log_dir),
                output_path=Path(args.output),
                from_date=args.from_date,
                to_date=args.to_date,
                session_id=args.session_id,
                data_source=args.data_source,
            )
            print(json.dumps(meta, indent=2))
        elif args.rl_command == "collect-synth":
            from sage.rl.collect_synth import SynthCollectConfig, collect_synthetic_trajectories

            rep = collect_synthetic_trajectories(
                cfg=SynthCollectConfig(rows=int(args.rows), seed=int(args.seed)),
            )
            print(json.dumps(rep, indent=2))
        elif args.rl_command == "analyze-rewards":
            from sage.rl.analyze_rewards import write_reward_report

            rep = write_reward_report(Path(args.data), Path(args.out))
            print(json.dumps(rep, indent=2))
        elif args.rl_command == "eval-offline":
            from sage.rl.eval_offline import write_offline_eval_report

            rep = write_offline_eval_report(
                data_path=Path(args.data),
                checkpoint=Path(args.checkpoint),
                out_path=Path(args.out),
                min_confidence=float(getattr(args, "min_confidence", 0.0)),
            )
            print(json.dumps(rep, indent=2))
        elif args.rl_command == "train-bc":
            from sage.rl.train_bc import train_bc_joblib

            report = train_bc_joblib(Path(args.data), Path(args.out))
            print(json.dumps(report, indent=2))
        elif args.rl_command == "train-cql":
            from sage.rl.train_cql import train_cql_stub

            report = train_cql_stub(Path(args.data), Path(args.out))
            print(json.dumps(report, indent=2))
    elif args.command == "sim":
        if args.sim_command == "generate":
            from sage.sim.oracle_tasks import write_tasks_jsonl

            meta = write_tasks_jsonl(Path(args.out), count=int(args.count), seed=int(args.seed))
            print(json.dumps(meta, indent=2))
        elif args.sim_command == "run":
            from sage.sim.parallel_runner import run_suite_from_jsonl

            rep = run_suite_from_jsonl(
                Path(args.tasks),
                workers=int(args.workers),
                limit=args.limit,
                use_docker=bool(getattr(args, "docker", False)),
            )
            print(json.dumps(rep, indent=2))
    elif args.command == "cron":
        if args.job == "weekly-memory-optimizer":
            from sage.agents.memory_optimizer import MemoryOptimizerAgent

            MemoryOptimizerAgent().run()
    elif args.command == "eval":
        if args.eval_command == "smoke":
            cmd_eval_smoke(args)
        elif args.eval_command == "golden":
            cmd_eval_golden(args)
        elif args.eval_command == "e2e":
            cmd_eval_e2e(args)
    elif args.command == "prep":
        cmd_prep(args)
    elif args.command == "session":
        from sage.cli.session_cmd import cmd_session_refresh, cmd_session_reset

        sc = getattr(args, "session_command", None)
        if sc == "reset":
            cmd_session_reset(args)
        elif sc == "refresh":
            cmd_session_refresh(args)
        elif sc == "status":
            cmd_status(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "setup":
        cmd_setup(args)
    else:
        parser.print_help()


def _strip_mistaken_sage_cli_prefix(line: str) -> str:
    """Inside the shell, users often type ``sage run ...``; only ``run ...`` is valid."""
    s = line.strip()
    if s.startswith(":"):
        s = s[1:].strip()
    low = s.lower()
    if low == "sage":
        return ""
    if low.startswith("sage "):
        return s[5:].lstrip()
    return s


def dispatch_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run a parsed subcommand; return a process exit code (for the interactive shell)."""
    try:
        _dispatch_command_impl(args, parser)
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    return 0


def cmd_shell(_args) -> None:
    """
    Interactive slash-like shell (in-process dispatch — fast, Rich errors).
    Examples:
      /commands
      /init
      /doctor
      /run "Build a FastAPI app" --auto
      /setup scan
    """
    from sage.cli.shell_input import read_shell_line
    from sage.cli.shell_support import (
        SHELL_TOP_LEVEL_COMMANDS,
        clear_terminal,
        format_argparse_error_message,
        print_commands_table,
        print_context_panel,
        print_models_panel,
        print_parse_error_rich,
        print_shell_help_screen,
        print_skills_panel,
    )
    from sage.cli.shell_chat import parse_chat_args, respond_nl_chat, run_shell_chat_loop
    from sage.cli.shell_intent import ShellIntentKind, classify_shell_line_ex
    from sage.cli.shell_nl import run_shell_natural_language_goal, shell_natural_language_enabled

    try:
        from sage.cli.branding import print_shell_intro

        print_shell_intro()
        use_rich = True
    except Exception:
        print(
            '[SAGE shell] Enter slash commands: /commands  /init  /doctor  /run "prompt" --auto  /exit to quit.'
        )
        use_rich = False

    os.environ["SAGE_INSIDE_SHELL"] = "1"
    os.environ.setdefault("SAGE_SHELL_MODE", "shell")
    os.environ.setdefault("SAGE_UI_MODE", "agent")
    parser = build_parser(exit_on_error=False)

    # PromptSession (slash menu, completions) must not depend on Rich: if the banner fails,
    # ``use_rich`` is False but we still want prompt_toolkit + ``/`` dropdown.
    shell_session = None
    if not os.environ.get("SAGE_SHELL_SIMPLE_INPUT", "").strip():
        try:
            from sage.cli.shell_input import create_shell_prompt_session

            shell_session = create_shell_prompt_session(use_rich=True)
        except Exception as e:
            if os.environ.get("SAGE_SHELL_DEBUG", "").strip():
                print(f"[SAGE shell] debug  create_shell_prompt_session failed: {e!r}")
            shell_session = None

    if os.environ.get("SAGE_SHELL_DEBUG", "").strip():
        from sage.cli.shell_input import print_shell_input_diagnostics

        print_shell_input_diagnostics(shell_session=shell_session)

    if use_rich and os.environ.get("SAGE_SHELL_SIMPLE_INPUT", "").strip():
        from sage.cli.branding import get_console

        get_console().print(
            "  [accent]![/accent]  [muted]SAGE_SHELL_SIMPLE_INPUT is set — Tab completion disabled. "
            "Unset for prompt_toolkit (Tab / completions).[/muted]"
        )

    try:
        while True:
            try:
                line = read_shell_line(use_rich=use_rich, session=shell_session).strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break
            if not line:
                continue
            if line in {"/exit", "/quit", "exit", "quit"}:
                break
            # Sole "/" was stripped to "" and used to do nothing — show catalog (same as /commands).
            if line == "/":
                print_commands_table()
                continue
            if line.startswith("/"):
                line = line[1:].strip()
            line = _strip_mistaken_sage_cli_prefix(line)
            if not line:
                continue
            try:
                parts = shlex.split(line)
            except ValueError as e:
                if use_rich:
                    from sage.cli.branding import get_console

                    get_console().print(f"  [accent]![/accent]  parse error: {e}")
                else:
                    print(f"[SAGE shell] parse error: {e}")
                continue
            if not parts:
                continue

            head = parts[0].lower()
            # Shorthand: `setup` alone = workspace bootstrap (same as `sage init`).
            if parts[0] == "setup" and len(parts) == 1:
                parts = ["init"]

            # Shell builtins (OpenClaw-style discoverability)
            if head == "commands":
                print_commands_table()
                continue
            if head in ("help", "?"):
                print_shell_help_screen()
                continue
            if head in ("skill", "skills"):
                arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
                print_skills_panel(show_body=arg or None)
                continue
            if head in ("model", "models"):
                print_models_panel()
                continue
            if head == "context":
                print_context_panel()
                continue
            if head == "start" and len(parts) >= 2 and parts[1].lower() == "chat":
                fn, res, init = parse_chat_args(["chat"] + parts[2:])
                rc = run_shell_chat_loop(
                    use_rich=use_rich,
                    session=shell_session,
                    initial_message=init,
                    force_new=fn,
                    resume=res,
                )
                if rc == "exit_shell":
                    break
                continue
            if head == "agent":
                from sage.cli.chat_session_store import clear_chat_session_env

                sub = parts[1].lower() if len(parts) > 1 else ""
                if sub in ("clear", "clear-context"):
                    clear_chat_session_env()
                    if use_rich:
                        from sage.cli.branding import get_console

                        get_console().print(
                            "  [muted]Cleared attach context — the next[/muted] [accent]run[/accent] "
                            "[muted]will not prepend chat history.[/muted]"
                        )
                    else:
                        print("[SAGE] Chat attach context cleared.")
                else:
                    os.environ["SAGE_UI_MODE"] = "agent"
                    if use_rich:
                        from sage.cli.branding import get_console

                        get_console().print(
                            "  [accent]Agent mode[/accent] [muted]— describe work in plain English or "
                            "[/muted][accent]run \"…\"[/accent][muted]. Prior chat (after[/muted] "
                            "[accent]chat[/accent][muted]) is prepended to the pipeline when "
                            "[/muted][accent]SAGE_CHAT_ATTACH_TO_RUN=1[/accent][muted] (default).[/muted]"
                        )
                    else:
                        print("[SAGE] Agent mode — NL and run use chat context when available.")
                continue
            if head == "chat":
                fn, res, init = parse_chat_args(parts)
                rc = run_shell_chat_loop(
                    use_rich=use_rich,
                    session=shell_session,
                    initial_message=init,
                    force_new=fn,
                    resume=res,
                )
                if rc == "exit_shell":
                    break
                continue
            if head == "clear":
                clear_terminal()
                continue
            if head == "shell":
                from sage.cli.branding import get_console

                get_console().print("  [muted]You are already in the SAGE shell.[/muted]")
                continue
            if head == "reset":
                from types import SimpleNamespace

                from sage.cli.session_cmd import cmd_session_reset

                cmd_session_reset(SimpleNamespace())
                continue
            if head == "refresh":
                from types import SimpleNamespace

                from sage.cli.session_cmd import cmd_session_refresh

                cmd_session_refresh(SimpleNamespace())
                continue

            # Natural language: intent routing (chat/help) vs full pipeline.
            if head not in SHELL_TOP_LEVEL_COMMANDS and shell_natural_language_enabled():
                kind, heuristic_hit = classify_shell_line_ex(line)
                if kind == ShellIntentKind.CODE:
                    run_shell_natural_language_goal(line, use_rich=use_rich)
                elif kind == ShellIntentKind.HELP:
                    print_shell_help_screen()
                else:
                    respond_nl_chat(line, use_rich=use_rich, used_heuristic=heuristic_hit)
                continue

            first_token = parts[0]
            try:
                ns = parser.parse_args(parts)
            except ArgumentError as exc:
                print_parse_error_rich(format_argparse_error_message(exc), first_token)
                continue

            code = dispatch_command(ns, parser)
            if code != 0:
                if use_rich:
                    from sage.cli.branding import get_console

                    get_console().print(f"  [muted]exit code[/muted] [accent]{code}[/accent]")
                else:
                    print(f"[SAGE shell] command failed: exit_code={code}")
    finally:
        os.environ.pop("SAGE_INSIDE_SHELL", None)


def cmd_setup(args) -> None:
    from sage.cli.hardware_setup import (
        apply_routing_to_config,
        pull_ollama_tags,
        scan_hardware,
        suggest_ollama_stack,
        write_models_yaml,
    )

    if args.setup_command == "init":
        cmd_init(args)
        return

    if args.setup_command == "scan":
        prof = scan_hardware()
        if getattr(args, "json", False):
            print(json.dumps(prof.to_dict(), indent=2))
        else:
            print("[SAGE setup] hardware scan")
            print(f"  os: {prof.os_name}")
            print(f"  ram_gib: {prof.ram_gib}")
            print(f"  vram_gib: {prof.vram_gib}")
            print(f"  sources: {prof.sources}")
            if prof.raw_excerpt:
                print(f"  excerpt:\n{prof.raw_excerpt[:800]}")
        return

    if args.setup_command == "suggest":
        prof = scan_hardware()
        sug = suggest_ollama_stack(prof, disk_budget_gib=float(args.disk_budget))
        if getattr(args, "json", False):
            out = {"hardware": prof.to_dict(), "suggestion": sug}
            print(json.dumps(out, indent=2))
        else:
            print("[SAGE setup] suggested Ollama stack")
            print(f"  tier: {sug['tier']}  est_disk_gib: ~{sug['estimated_pull_gib']}")
            print(f"  pull: {', '.join(sug['ollama_tags'])}")
            print("  roles (preview):")
            for role, cfg in sorted(sug["routing"].items()):
                print(f"    {role}: primary={cfg['primary']} fallback={cfg['fallback']}")
        return

    if args.setup_command == "apply":
        prof = scan_hardware()
        sug = suggest_ollama_stack(prof, disk_budget_gib=float(args.disk_budget))
        cfg_path = (
            Path(args.models_yaml) if getattr(args, "models_yaml", None) else _models_config_path()
        )
        base = _load_models_config(cfg_path) if cfg_path.exists() else {"routing": {}}
        merged = apply_routing_to_config(base, sug)
        if getattr(args, "dry_run", False):
            print(json.dumps(merged, indent=2))
            return
        write_models_yaml(cfg_path, merged)
        print(f"[SAGE setup] wrote routing to {cfg_path}")
        return

    if args.setup_command == "pull":
        prof = scan_hardware()
        sug = suggest_ollama_stack(prof, disk_budget_gib=float(args.disk_budget))
        tags = list(sug["ollama_tags"])
        if getattr(args, "json", False):
            print(json.dumps({"pull": pull_ollama_tags(tags)}, indent=2))
        else:
            print(f"[SAGE setup] ollama pull ({len(tags)} tags)…")
            for r in pull_ollama_tags(tags):
                status = "ok" if r["ok"] else "fail"
                print(f"  - {r['tag']}: {status}")
        return


def cmd_config(args) -> None:
    cfg = _load_models_config()
    if args.config_command == "show":
        if getattr(args, "json", False):
            print(json.dumps(cfg, indent=2))
        else:
            routing = cfg.get("routing", {})
            print("[SAGE config] routing roles:")
            if isinstance(routing, dict):
                for role in sorted(routing):
                    role_cfg = routing.get(role, {}) or {}
                    print(
                        f"  - {role}: primary={role_cfg.get('primary', '')} fallback={role_cfg.get('fallback', '')}"
                    )
            else:
                print("  (invalid routing structure)")
    elif args.config_command == "validate":
        errs = _validate_models_config(cfg)
        if errs:
            print("[SAGE config] invalid")
            for e in errs:
                print(f"  - {e}")
            raise SystemExit(EX_USAGE)
        print("[SAGE config] valid")
    elif args.config_command == "migrate":
        from shutil import copy2

        from sage.config.paths import bundled_models_yaml, user_config_dir

        dest = user_config_dir() / "models.yaml"
        user_config_dir().mkdir(parents=True, exist_ok=True)
        if dest.exists() and not getattr(args, "force", False):
            print(f"[SAGE config] {dest} already exists; use --force to overwrite")
            raise SystemExit(EX_USAGE)
        copy2(bundled_models_yaml(), dest)
        print(f"[SAGE config] wrote {dest}")
    elif args.config_command == "paths":
        from sage.config.paths import resolved_models_yaml_path, user_config_dir

        print(f"user_config_dir={user_config_dir()}")
        print(f"resolved_models_yaml={resolved_models_yaml_path()}")
    elif args.config_command == "set":
        role = str(args.role).strip()
        if not role:
            raise SystemExit("--role is required")
        routing = cfg.setdefault("routing", {})
        if not isinstance(routing, dict):
            raise SystemExit("models.yaml invalid: routing must be a mapping")
        role_cfg = routing.setdefault(role, {})
        if not isinstance(role_cfg, dict):
            raise SystemExit(f"models.yaml invalid: routing.{role} must be a mapping")

        updated = False
        if args.primary is not None:
            role_cfg["primary"] = args.primary
            updated = True
        if args.fallback is not None:
            role_cfg["fallback"] = args.fallback
            updated = True
        if args.trigger is not None:
            role_cfg["fallback_triggers"] = list(args.trigger)
            updated = True
        if not updated:
            raise SystemExit("nothing to update; pass --primary and/or --fallback and/or --trigger")
        _save_models_config(cfg)
        print(f"[SAGE config] updated role={role}")


def cmd_eval_smoke(_args) -> None:
    """Run Ollama-backed integration tests with laptop-friendly routing."""
    import shutil
    from pathlib import Path

    from sage.cli.branding import get_console

    if shutil.which("ollama") is None:
        get_console().print(
            "  [accent]eval smoke[/accent] [muted]— ollama not in PATH; nothing to run.[/muted]"
        )
        return
    root = Path(__file__).resolve().parents[3]
    tests_dir = root / "tests" / "integration"
    env = os.environ.copy()
    env["SAGE_MODEL_PROFILE"] = "test"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests_dir), "-q", "-m", "ollama"],
        cwd=str(root),
        env=env,
    )
    raise SystemExit(r.returncode)


def cmd_eval_golden(_args) -> None:
    """Golden trace ordering (fixture + mocked Ollama); no network."""
    root = Path(__file__).resolve().parents[3]
    test_file = root / "tests" / "test_golden_trace_regression.py"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q"],
        cwd=str(root),
    )
    raise SystemExit(r.returncode)


def cmd_eval_e2e(_args) -> None:
    """Mocked greenfield app.invoke (see docs/GREENFIELD.md)."""
    root = Path(__file__).resolve().parents[3]
    e2e_dir = root / "tests" / "e2e"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(e2e_dir), "-q"],
        cwd=str(root),
    )
    raise SystemExit(r.returncode)


def cmd_prep(args) -> None:
    """
    Hardware-aware model recommendations for *real* runs.

    Does not throttle anything: it only suggests tags. For pytest/CI, use
    ``SAGE_MODEL_PROFILE=test`` instead (separate from daily work).
    """
    from sage.cli.hardware_setup import scan_hardware, suggest_ollama_stack

    prof = scan_hardware()
    sug = suggest_ollama_stack(prof, disk_budget_gib=float(args.disk_budget))

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "hardware": prof.to_dict(),
                    "suggestion": sug,
                    "note": "Do not set SAGE_MODEL_PROFILE=test for real project work.",
                },
                indent=2,
            )
        )
        return

    from sage.cli.branding import get_console

    c = get_console()
    c.print()
    c.print("  [accent]prep[/accent] [muted]— recommended Ollama stack for this machine[/muted]")
    c.print(
        f"  [muted]OS[/muted] {prof.os_name}   [muted]RAM GiB[/muted] {prof.ram_gib}   "
        f"[muted]VRAM GiB[/muted] {prof.vram_gib}"
    )
    c.print(f"  [muted]Tier[/muted] [brand]{sug['tier']}[/brand]   [muted]~pull GiB[/muted] {sug.get('estimated_pull_gib', '?')}")
    c.print("  [muted]Pull (best effort, fits disk budget):[/muted]")
    for tag in sug.get("ollama_tags") or []:
        c.print(f"    [accent]ollama pull[/accent] {tag}")
    c.print()
    c.print("  [muted]Write routing:[/muted] [accent]sage setup apply[/accent] [muted](merges into models.yaml)[/muted]")
    c.print(
        "  [muted]Real coding:[/muted] leave [accent]SAGE_MODEL_PROFILE[/accent] [muted]unset — "
        "the [accent]test[/accent] [muted]profile forces one tiny model (for CI only).[/muted]"
    )
    c.print(
        "  [muted]Benchmarks:[/muted] [accent]SAGE_BENCH=1[/accent] [muted]extends timeouts; "
        "do not set for normal[/muted] [accent]sage run[/accent][muted].[/muted]"
    )
    c.print("  [muted]Guide:[/muted] docs/LOCAL_PROJECT_PREP.md")
    c.print()


def cmd_status(args):
    import json
    from pathlib import Path

    state_file = Path("memory/system_state.json")
    if not state_file.exists() or state_file.stat().st_size == 0:
        print("[SAGE] No prior session found.")
        return
    with open(state_file) as f:
        state = json.load(f)
    print("\n[SAGE] Current State:")
    for k, v in state.items():
        print(f"  {k}: {v}")


def cmd_memory(args):
    from pathlib import Path

    memory_dir = Path("memory")
    if not memory_dir.exists():
        print("[SAGE] Memory directory not found.")
        return
    print("\n[SAGE] Memory layers:")
    for path in sorted(memory_dir.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            print(f"  {path} ({size} bytes)")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        from sage.cli.branding import (
            print_activation_footer,
            print_cli_help_banner,
            should_activate_shell,
        )

        if should_activate_shell():
            cmd_shell(args)
        else:
            print_cli_help_banner()
            print_activation_footer()
            parser.print_help()
        return

    code = dispatch_command(args, parser)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
