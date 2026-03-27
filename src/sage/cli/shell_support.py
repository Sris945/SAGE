"""
Interactive shell helpers: command catalog, skills, models, context, suggestions.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from sage.config.paths import resolved_models_yaml_path
from sage.version import get_version


@dataclass(frozen=True)
class CommandRow:
    name: str
    summary: str
    example: str


# Curated for the shell /commands table (OpenClaw-style discoverability).
COMMAND_CATALOG: tuple[CommandRow, ...] = (
    CommandRow(
        "commands",
        "Print this catalog (shell: /commands)",
        "commands",
    ),
    CommandRow("run", "Pipeline from a natural-language goal", 'run "Add a /health route" --auto'),
    CommandRow("prep", "Hardware-aware Ollama stack + pull list", "prep"),
    CommandRow("init", "Bootstrap .sage/ + memory/ here", "init"),
    CommandRow("doctor", "Environment, models, ollama, docker checks", "doctor"),
    CommandRow("status", "Last session state (memory/system_state.json)", "status"),
    CommandRow("memory", "List memory layer files", "memory"),
    CommandRow("permissions", "Workspace + tool policy summary", "permissions --json"),
    CommandRow("setup", "Hardware scan / suggest / apply / pull", "setup scan"),
    CommandRow("config", "models.yaml: show | validate | paths | set …", "config show"),
    CommandRow("bench", "Phase-4 benchmark suite", "bench --out memory/benchmarks/run.json"),
    CommandRow("rl", "Offline RL: export, train-bc, train-cql, …", "rl export --output datasets/r.jsonl"),
    CommandRow("sim", "Oracle tasks + parallel pytest", "sim generate --count 100"),
    CommandRow("cron", "Scheduled jobs", "cron weekly-memory-optimizer"),
    CommandRow("eval", "Trust: golden | e2e | smoke", "eval golden"),
    CommandRow("shell", "This REPL (also: bare `sage` in a TTY)", "shell"),
)


SHELL_BUILTIN_COMMANDS: frozenset[str] = frozenset(
    {
        "help",
        "commands",
        "?",
        "skill",
        "skills",
        "model",
        "models",
        "context",
        "clear",
        "exit",
        "quit",
    }
)


def top_level_names() -> list[str]:
    return [r.name for r in COMMAND_CATALOG]


def suggest_commands(word: str, *, limit: int = 5) -> list[str]:
    w = (word or "").strip().lower()
    pool = list(SHELL_BUILTIN_COMMANDS) + top_level_names()
    # Subcommands users often mistype
    pool.extend(
        [
            "scan",
            "suggest",
            "apply",
            "pull",
            "show",
            "validate",
            "export",
            "golden",
            "e2e",
            "smoke",
            "generate",
        ]
    )
    uniq = sorted(set(pool))
    return difflib.get_close_matches(w, uniq, n=limit, cutoff=0.45)


def _bundled_skills_dir() -> Path:
    from sage.prompt_engine.skill_injector import bundled_skills_root

    return bundled_skills_root()


def iter_skill_files() -> list[Path]:
    root = _bundled_skills_dir()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("SKILL.md")):
        if p.is_file():
            out.append(p)
    return out


def skill_id_from_path(skill_md: Path) -> str:
    rel = skill_md.relative_to(_bundled_skills_dir())
    parts = list(rel.parts[:-1])
    return "/".join(parts) if parts else rel.as_posix()


def print_commands_table() -> None:
    from rich import box
    from rich.table import Table

    from sage.cli.branding import get_console

    c = get_console()
    t = Table(
        title=f"[brand]SAGE[/brand] [muted]{get_version()}[/muted] — commands",
        box=box.ROUNDED,
        border_style="rule",
        header_style="accent",
        show_lines=False,
    )
    t.add_column("Command", style="brand", no_wrap=True)
    t.add_column("What it does", style="white")
    t.add_column("Example", style="muted")

    for row in COMMAND_CATALOG:
        t.add_row(row.name, row.summary, row.example)

    c.print()
    c.print(t)
    c.print()
    c.print(
        "  [muted]Shell-only:[/muted] [accent]/help[/accent]  [accent]/commands[/accent]  "
        "[accent]/skill[/accent]  [accent]/model[/accent]  [accent]/context[/accent]  [accent]/clear[/accent]"
    )
    c.print()


def print_shell_help_screen() -> None:
    from rich.panel import Panel

    from sage.cli.branding import get_console

    c = get_console()
    body = (
        "[accent]/commands[/accent] or [accent]/help[/accent] — full command table\n"
        "[accent]/skill[/accent] — list bundled prompt skills (injected by role)\n"
        "[accent]/model[/accent] — routing summary from models.yaml\n"
        "[accent]/context[/accent] — memory dir, config path, env hints\n"
        "[accent]/clear[/accent] — clear the terminal\n"
        "[accent]/exit[/accent] — leave the shell\n"
        "\n"
        "Everything else is a normal CLI invocation without the [muted]sage[/muted] prefix, e.g.\n"
        '  [brand]/doctor[/brand]   [brand]/prep[/brand]   [brand]/run[/brand] [muted]"your goal"[/muted] [muted]--auto[/muted]'
    )
    c.print()
    c.print(
        Panel.fit(
            body,
            title="[brand]SAGE shell[/brand]",
            border_style="#0d9488",
            padding=(1, 2),
        )
    )
    c.print()
    print_commands_table()


def print_skills_panel(*, show_body: str | None = None) -> None:
    from rich import box
    from rich.table import Table

    from sage.cli.branding import get_console

    paths = iter_skill_files()
    c = get_console()
    if not paths:
        c.print("  [muted]No SKILL.md files under bundled skills root.[/muted]")
        return

    if show_body:
        # Find by id prefix match
        want = show_body.strip().lower().replace("\\", "/")
        match: Path | None = None
        for p in paths:
            sid = skill_id_from_path(p).lower()
            if sid == want or sid.endswith("/" + want) or want in sid:
                match = p
                break
        if match is None:
            c.print(f"  [accent]skill[/accent] [muted]— no match for[/muted] {show_body!r}")
            c.print("  [muted]Try[/muted] [accent]/skill[/accent] [muted]for the list of ids.[/muted]")
            return
        text = match.read_text(encoding="utf-8", errors="replace")
        preview = text[:6000] + ("\n\n… [truncated]" if len(text) > 6000 else "")
        c.print()
        c.print(f"  [accent]{skill_id_from_path(match)}[/accent]  [muted]{match}[/muted]")
        c.print()
        c.print(preview)
        c.print()
        return

    t = Table(
        title="[brand]Bundled skills[/brand] (prompt injection)",
        box=box.SIMPLE_HEAD,
        border_style="rule",
        header_style="accent",
    )
    t.add_column("id", style="brand", no_wrap=True)
    t.add_column("path", style="muted")

    for p in paths:
        t.add_row(skill_id_from_path(p), str(p))

    c.print()
    c.print(t)
    c.print(
        "  [muted]Preview:[/muted] [accent]/skill[/accent] [muted]<id-prefix>[/muted]   e.g. "
        '[accent]/skill[/accent] [muted]workflow/tdd-workflow[/muted]'
    )
    c.print()


def _load_models_yaml_dict() -> dict:
    p = resolved_models_yaml_path()
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def print_models_panel() -> None:
    from rich import box
    from rich.table import Table

    from sage.cli.branding import get_console

    c = get_console()
    try:
        cfg = _load_models_yaml_dict()
    except Exception as e:
        c.print(f"  [muted]Could not load models.yaml:[/muted] {e}")
        return

    routing = cfg.get("routing") if isinstance(cfg, dict) else None
    if not isinstance(routing, dict) or not routing:
        c.print("  [muted]No routing table in models.yaml.[/muted]")
        return

    t = Table(
        title="[brand]Model routing[/brand] (models.yaml)",
        box=box.ROUNDED,
        border_style="rule",
        header_style="accent",
    )
    t.add_column("role", style="brand", no_wrap=True)
    t.add_column("primary", style="white")
    t.add_column("fallback", style="white")

    for role in sorted(routing.keys()):
        rc = routing.get(role) or {}
        if not isinstance(rc, dict):
            continue
        t.add_row(
            str(role),
            str(rc.get("primary", "")),
            str(rc.get("fallback", "")),
        )

    c.print()
    c.print(t)
    prof = (os.environ.get("SAGE_MODEL_PROFILE") or "").strip()
    if prof:
        c.print(f"  [muted]SAGE_MODEL_PROFILE=[/muted][accent]{prof}[/accent] [muted](overrides test routing)[/muted]")
    else:
        c.print("  [muted]SAGE_MODEL_PROFILE unset — using models.yaml routing.[/muted]")
    c.print()


def _memory_dir_size_bytes(mem: Path) -> int:
    total = 0
    try:
        for p in mem.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        return 0
    return total


def print_context_panel() -> None:
    from sage.cli.branding import get_console
    from sage.config.paths import resolved_models_yaml_path, user_config_dir

    c = get_console()
    mem = Path("memory")
    sz = _memory_dir_size_bytes(mem) if mem.is_dir() else 0
    sessions = list(mem.glob("sessions/*.log")) if mem.is_dir() else []
    last_log = max(sessions, key=lambda p: p.stat().st_mtime, default=None)

    c.print()
    c.print("  [accent]Context[/accent] [muted]— local workspace[/muted]")
    c.print(f"  [muted]cwd[/muted] {Path.cwd()}")
    c.print(f"  [muted]memory/[/muted] ~{sz / 1024:.1f} KiB" if sz else "  [muted]memory/[/muted] (missing or empty)")
    if last_log:
        c.print(f"  [muted]latest session log[/muted] {last_log}")
    try:
        c.print(f"  [muted]models.yaml[/muted] {resolved_models_yaml_path()}")
    except Exception:
        pass
    c.print(f"  [muted]user config dir[/muted] {user_config_dir()}")
    c.print()


def clear_terminal() -> None:
    try:
        import shutil

        if shutil.which("clear"):
            os.system("clear")  # noqa: S605,S607
            return
    except Exception:
        pass
    from sage.cli.branding import get_console

    get_console().print("\n" * 2)


def format_argparse_error_message(exc: BaseException) -> str:
    return str(exc).strip() or exc.__class__.__name__


def print_parse_error_rich(message: str, typed_token: str | None) -> None:
    from sage.cli.branding import get_console

    c = get_console()
    c.print(f"  [accent]![/accent]  {message}")
    if typed_token:
        sug = suggest_commands(typed_token)
        if sug:
            c.print(f"  [muted]Did you mean:[/muted] {', '.join(sug)}")
    c.print("  [muted]Type[/muted] [accent]/commands[/accent] [muted]for the full table.[/muted]")
    c.print()
