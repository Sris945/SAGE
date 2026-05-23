"""
Hardware-aware Ollama model suggestions for SAGE.

Detects OS, RAM, VRAM, CPU cores, and available disk, then selects the best
Ollama model stack for each agent role that fits inside the user's chosen
allocation budget.

Public API
----------
scan_hardware()            → HardwareProfile
run_allocation_wizard()    → AllocationConfig  (interactive or headless)
suggest_ollama_stack()     → dict with tier, routing, tags
apply_routing_to_config()  → updated models.yaml dict
pull_ollama_tags()         → list of pull results (with Rich progress)
write_models_yaml()        → None
save_hardware_json()       → None
load_hardware_json()       → AllocationConfig | None
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Model catalogue ───────────────────────────────────────────────────────────

# Approximate on-disk sizes (GiB, q4_K_M quant unless noted)
_MODEL_SIZES_GIB: dict[str, float] = {
    "qwen2.5-coder:1.5b": 1.0,
    "qwen2.5-coder:7b-instruct-q4_K_M": 4.5,
    "qwen2.5-coder:14b-instruct-q4_K_M": 9.0,
    "qwen2.5-coder:32b-instruct-q4_K_M": 19.0,
    "llama3.2:3b": 2.0,
    "phi3:mini": 2.3,
    "nomic-embed-text:latest": 0.3,
}

# RAM required to run each model comfortably (GiB, includes OS overhead)
_MODEL_RAM_REQUIRED_GIB: dict[str, float] = {
    "qwen2.5-coder:1.5b": 3.0,
    "qwen2.5-coder:7b-instruct-q4_K_M": 6.0,
    "qwen2.5-coder:14b-instruct-q4_K_M": 12.0,
    "qwen2.5-coder:32b-instruct-q4_K_M": 24.0,
    "llama3.2:3b": 4.0,
    "phi3:mini": 4.0,
    "nomic-embed-text:latest": 1.0,
}

# Context window (tokens) per model
_MODEL_CONTEXT_WINDOW: dict[str, int] = {
    "qwen2.5-coder:1.5b": 32768,
    "qwen2.5-coder:7b-instruct-q4_K_M": 32768,
    "qwen2.5-coder:14b-instruct-q4_K_M": 32768,
    "qwen2.5-coder:32b-instruct-q4_K_M": 32768,
    "llama3.2:3b": 131072,
    "phi3:mini": 131072,
    "nomic-embed-text:latest": 8192,
}

_EMBED_MODEL = "nomic-embed-text:latest"

_TIERS = [
    # (min_budget_gib, tier_name, primary_coder, strong_model)
    (24.0, "large",    "qwen2.5-coder:14b-instruct-q4_K_M", "qwen2.5-coder:32b-instruct-q4_K_M"),
    (12.0, "balanced", "qwen2.5-coder:7b-instruct-q4_K_M",  "qwen2.5-coder:14b-instruct-q4_K_M"),
    (5.0,  "light",    "qwen2.5-coder:1.5b",                "qwen2.5-coder:7b-instruct-q4_K_M"),
    (0.0,  "minimal",  "qwen2.5-coder:1.5b",                "qwen2.5-coder:1.5b"),
]


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class HardwareProfile:
    os_name: str
    ram_gib: float | None = None
    vram_gib: float | None = None
    cpu_cores: int | None = None
    disk_free_gib: float | None = None
    ollama_model_dir: str = ""
    sources: dict[str, str] = field(default_factory=dict)
    raw_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name,
            "ram_gib": self.ram_gib,
            "vram_gib": self.vram_gib,
            "cpu_cores": self.cpu_cores,
            "disk_free_gib": self.disk_free_gib,
            "ollama_model_dir": self.ollama_model_dir,
            "sources": self.sources,
        }


@dataclass
class AllocationConfig:
    ram_budget_gib: float
    quality_preference: str        # "speed" | "balanced" | "quality"
    disk_budget_gib: float
    hardware: HardwareProfile | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ram_budget_gib": self.ram_budget_gib,
            "quality_preference": self.quality_preference,
            "disk_budget_gib": self.disk_budget_gib,
            "hardware": self.hardware.to_dict() if self.hardware else None,
        }


# ── Low-level detection helpers ───────────────────────────────────────────────

def _run_capture(cmd: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception as e:
        return 1, "", str(e)


def _linux_mem_gib() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024 * 1024), 2)
    except OSError:
        pass
    return None


def _cpu_cores() -> int | None:
    try:
        count = os.cpu_count()
        return count if count and count > 0 else None
    except Exception:
        return None


def _disk_free_gib(path: str) -> float | None:
    try:
        import shutil
        usage = shutil.disk_usage(path)
        return round(usage.free / (1024 ** 3), 2)
    except Exception:
        return None


def _ollama_model_dir() -> str:
    env = os.environ.get("OLLAMA_MODELS", "")
    if env:
        return env
    home = Path.home()
    candidates = [
        home / ".ollama" / "models",
        Path("/usr/share/ollama/.ollama/models"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(home / ".ollama" / "models")


def _nvidia_vram_gib() -> float | None:
    code, out, _ = _run_capture(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        timeout=8.0,
    )
    if code != 0 or not out.strip():
        return None
    try:
        first = out.strip().splitlines()[0].strip()
        m = re.search(r"([0-9]+)", first)
        if not m:
            return None
        mib = float(m.group(1))
        return round(mib / 1024, 2)
    except Exception:
        return None


def _rocm_vram_gib() -> float | None:
    code, out, _ = _run_capture(["rocm-smi", "--showmeminfo", "vram", "--json"], timeout=8.0)
    if code != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
        for card in data.values():
            total = card.get("VRAM Total Memory (B)")
            if total:
                return round(int(total) / (1024 ** 3), 2)
    except Exception:
        pass
    return None


def _try_fastfetch_json() -> tuple[float | None, float | None, str]:
    code, out, _ = _run_capture(["fastfetch", "--json"], timeout=10.0)
    if code != 0 or not out.strip():
        return None, None, ""
    try:
        data = json.loads(out)
        blob = json.dumps(data)
        ram = None
        vram = None
        m = re.search(r'"total"\s*:\s*([0-9]{6,})', blob)
        if m:
            ram = round(int(m.group(1)) / (1024 ** 3), 2)
        m2 = re.search(r'"dedicatedMemory"\s*:\s*([0-9]{6,})', blob, re.I)
        if m2:
            vram = round(int(m2.group(1)) / (1024 ** 3), 2)
        return ram, vram, out[:1500]
    except Exception:
        return None, None, out[:1500]


def _try_neofetch_mem() -> tuple[float | None, str]:
    code, out, _ = _run_capture(["neofetch", "--stdout"], timeout=12.0)
    if code != 0:
        return None, ""
    m = re.search(r"Memory:\s*([0-9.]+)\s*GiB", out, re.I)
    if m:
        return float(m.group(1)), out[:1500]
    return None, out[:1500]


def _windows_profile() -> HardwareProfile:
    ps_ram = (
        "$m = Get-CimInstance Win32_ComputerSystem | "
        "Select-Object -ExpandProperty TotalPhysicalMemory; "
        "[math]::Round($m / 1GB, 2)"
    )
    code, out, err = _run_capture(["powershell", "-NoProfile", "-Command", ps_ram], timeout=15.0)
    ram = None
    if code == 0 and out.strip():
        try:
            ram = float(out.strip().splitlines()[-1].strip())
        except ValueError:
            pass

    ps_vram = (
        "Get-CimInstance Win32_VideoController | "
        "Where-Object { $_.AdapterRAM -and $_.AdapterRAM -gt 0 } | "
        "Select-Object -First 1 -ExpandProperty AdapterRAM"
    )
    code2, out2, _ = _run_capture(["powershell", "-NoProfile", "-Command", ps_vram], timeout=15.0)
    vram = None
    if code2 == 0 and out2.strip():
        try:
            ar = int(out2.strip().splitlines()[0].strip())
            if ar > 0:
                vram = round(ar / (1024 ** 3), 2)
        except (ValueError, IndexError):
            pass

    model_dir = _ollama_model_dir()
    return HardwareProfile(
        os_name="windows",
        ram_gib=ram,
        vram_gib=vram,
        cpu_cores=_cpu_cores(),
        disk_free_gib=_disk_free_gib(model_dir),
        ollama_model_dir=model_dir,
        sources={"powershell": "memory+vram"},
        raw_excerpt=(err or "")[:500],
    )


# ── Public: scan hardware ─────────────────────────────────────────────────────

def scan_hardware() -> HardwareProfile:
    """Detect OS, RAM, VRAM, CPU cores, and free disk at the Ollama model directory."""
    system = platform.system().lower()
    if system == "windows":
        return _windows_profile()

    ram: float | None = _linux_mem_gib()
    vram: float | None = _nvidia_vram_gib() or _rocm_vram_gib()
    sources: dict[str, str] = {}
    raw_parts: list[str] = []

    ff_ram, ff_vram, ff_raw = _try_fastfetch_json()
    if ff_ram is not None:
        ram = ff_ram
        sources["fastfetch"] = "ram"
    if ff_vram is not None:
        vram = ff_vram
        sources["fastfetch"] = sources.get("fastfetch", "") + "+vram"
    if ff_raw:
        raw_parts.append(ff_raw)

    if ram is None:
        nr, nraw = _try_neofetch_mem()
        if nr is not None:
            ram = nr
            sources["neofetch"] = "ram"
        if nraw:
            raw_parts.append(nraw)

    if ram is not None and "fastfetch" not in sources and "neofetch" not in sources:
        sources["proc"] = "meminfo"

    if vram is None:
        v = _nvidia_vram_gib()
        if v is not None:
            vram = v
            sources["nvidia-smi"] = "vram"
        else:
            v = _rocm_vram_gib()
            if v is not None:
                vram = v
                sources["rocm-smi"] = "vram"

    model_dir = _ollama_model_dir()
    return HardwareProfile(
        os_name="linux" if system == "linux" else system,
        ram_gib=ram,
        vram_gib=vram,
        cpu_cores=_cpu_cores(),
        disk_free_gib=_disk_free_gib(model_dir),
        ollama_model_dir=model_dir,
        sources=sources,
        raw_excerpt="\n".join(raw_parts)[:2000],
    )


# ── Public: allocation wizard ─────────────────────────────────────────────────

def run_allocation_wizard(
    profile: HardwareProfile,
    *,
    headless: bool = False,
) -> AllocationConfig:
    """
    Ask the user how much RAM and disk to allocate to SAGE models.

    In headless mode (CI / --headless), picks safe defaults automatically.
    Returns an AllocationConfig that can be passed to suggest_ollama_stack().
    """
    ram = profile.ram_gib or 8.0
    disk = profile.disk_free_gib or 20.0

    # Build RAM budget options based on what's available
    options: list[float] = []
    for frac, label in [(0.25, "25%"), (0.5, "50%"), (0.75, "75%")]:
        val = round(ram * frac, 1)
        if val >= 3.0:
            options.append(val)
    options.append(round(min(ram * 0.9, ram - 2.0), 1))  # max: leave 2 GB for OS
    options = sorted(set(options))

    disk_options: list[float] = []
    for frac in [0.25, 0.5, 0.75]:
        val = round(disk * frac, 1)
        if val >= 2.0:
            disk_options.append(val)
    disk_options.append(round(min(disk * 0.9, disk - 2.0), 1))
    disk_options = sorted(set(disk_options))

    if headless or not _is_tty():
        ram_budget = options[len(options) // 2] if options else 6.0
        disk_budget = disk_options[len(disk_options) // 2] if disk_options else 10.0
        quality = "balanced"
        return AllocationConfig(
            ram_budget_gib=ram_budget,
            quality_preference=quality,
            disk_budget_gib=disk_budget,
            hardware=profile,
        )

    try:
        from rich.panel import Panel
        from rich.table import Table
        from rich import box
        from sage.cli.branding import get_console
        c = get_console()

        c.print()
        c.print(Panel.fit(
            f"[white]Detected[/white]\n"
            f"  RAM        [brand]{profile.ram_gib or '?'} GiB[/brand]\n"
            f"  VRAM       [brand]{profile.vram_gib or 'none detected'} GiB[/brand]\n"
            f"  CPU cores  [brand]{profile.cpu_cores or '?'}[/brand]\n"
            f"  Disk free  [brand]{profile.disk_free_gib or '?'} GiB[/brand]  "
            f"[dim]({profile.ollama_model_dir})[/dim]",
            title="[accent]SAGE Hardware Setup[/accent]",
            border_style="#0d9488",
            padding=(0, 1),
        ))
        c.print()

        # RAM budget
        c.print("[brand]How much RAM should SAGE allocate for models?[/brand]")
        for i, val in enumerate(options, 1):
            c.print(f"  [accent]{i}[/accent]  {val} GiB")
        c.print(f"  [accent]{len(options) + 1}[/accent]  Enter custom value")
        c.print()

        ram_budget = options[len(options) // 2]
        try:
            raw = input(f"Choice [1–{len(options) + 1}] (default {len(options) // 2 + 1}): ").strip()
            if raw:
                idx = int(raw) - 1
                if 0 <= idx < len(options):
                    ram_budget = options[idx]
                elif idx == len(options):
                    custom = input("Custom RAM budget (GiB): ").strip()
                    ram_budget = float(custom)
        except (ValueError, EOFError):
            pass

        c.print()
        c.print("[brand]Quality preference?[/brand]")
        c.print("  [accent]1[/accent]  Speed    — smallest models, fastest responses")
        c.print("  [accent]2[/accent]  Balanced — (default)")
        c.print("  [accent]3[/accent]  Quality  — largest models that fit your budget")
        c.print()

        quality = "balanced"
        try:
            raw = input("Choice [1–3] (default 2): ").strip()
            quality = {"1": "speed", "2": "balanced", "3": "quality"}.get(raw, "balanced")
        except EOFError:
            pass

        # Disk budget
        c.print()
        c.print("[brand]How much disk space for Ollama models?[/brand]")
        for i, val in enumerate(disk_options, 1):
            c.print(f"  [accent]{i}[/accent]  {val} GiB")
        c.print()

        disk_budget = disk_options[len(disk_options) // 2] if disk_options else 10.0
        try:
            raw = input(f"Choice [1–{len(disk_options)}] (default {len(disk_options) // 2 + 1}): ").strip()
            if raw:
                idx = int(raw) - 1
                if 0 <= idx < len(disk_options):
                    disk_budget = disk_options[idx]
        except (ValueError, EOFError):
            pass

        c.print()
        return AllocationConfig(
            ram_budget_gib=ram_budget,
            quality_preference=quality,
            disk_budget_gib=disk_budget,
            hardware=profile,
        )
    except Exception:
        # Rich unavailable or non-TTY — safe defaults
        ram_budget = options[len(options) // 2] if options else 6.0
        return AllocationConfig(
            ram_budget_gib=ram_budget,
            quality_preference="balanced",
            disk_budget_gib=disk_options[len(disk_options) // 2] if disk_options else 10.0,
            hardware=profile,
        )


def _is_tty() -> bool:
    import sys
    return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()


# ── Public: model suggestion ──────────────────────────────────────────────────

def suggest_ollama_stack(
    profile: HardwareProfile,
    *,
    disk_budget_gib: float = 18.0,
    ram_budget_gib: float | None = None,
    quality_preference: str = "balanced",
) -> dict[str, Any]:
    """
    Select the best Ollama model stack for each agent role.

    Priority: VRAM > ram_budget_gib > RAM total.
    Planner always gets the strongest model the budget allows.
    Coder gets second-strongest. Reviewer/tester/debugger get mid.
    Shell roles always get the lightest (latency-sensitive).
    """
    effective_ram = ram_budget_gib or profile.vram_gib or profile.ram_gib or 4.0

    # Quality preference adjusts the effective budget up/down by 20%
    if quality_preference == "quality":
        effective_ram *= 1.2
    elif quality_preference == "speed":
        effective_ram *= 0.8

    # Pick tier
    tier = "minimal"
    coder_model = "qwen2.5-coder:1.5b"
    strong_model = "qwen2.5-coder:1.5b"
    for min_ram, tier_name, coder, strong in _TIERS:
        if effective_ram >= min_ram:
            tier = tier_name
            coder_model = coder
            strong_model = strong
            break

    tiny = "qwen2.5-coder:1.5b"
    embed = _EMBED_MODEL

    # Role assignments: planner/architect get strongest; coder gets coder_model;
    # reviewer/test/docs get coder_model; debugger/memory get strong_model
    routing: dict[str, dict] = {
        "planner": {
            "primary": strong_model,
            "fallback": coder_model,
            "fallback_triggers": ["task_complexity_score > 0.8"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(strong_model, 32768),
        },
        "architect": {
            "primary": strong_model,
            "fallback": coder_model,
            "fallback_triggers": ["task_complexity_score > 0.8"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(strong_model, 32768),
        },
        "coder": {
            "primary": coder_model,
            "fallback": strong_model,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(coder_model, 32768),
        },
        "reviewer": {
            "primary": coder_model,
            "fallback": strong_model,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(coder_model, 32768),
        },
        "test_engineer": {
            "primary": coder_model,
            "fallback": strong_model,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(coder_model, 32768),
        },
        "documentation": {
            "primary": coder_model,
            "fallback": coder_model,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(coder_model, 32768),
        },
        "debugger": {
            "primary": strong_model,
            "fallback": coder_model,
            "fallback_triggers": ["primary_failure_count >= 1"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(strong_model, 32768),
        },
        "memory_optimizer": {
            "primary": coder_model,
            "fallback": tiny,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(coder_model, 32768),
        },
        "shell_router": {
            "primary": tiny,
            "fallback": coder_model,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(tiny, 32768),
        },
        "shell_chat": {
            "primary": coder_model,
            "fallback": strong_model,
            "fallback_triggers": ["primary_failure_count >= 2"],
            "context_window": _MODEL_CONTEXT_WINDOW.get(coder_model, 32768),
        },
    }

    pull_set: set[str] = {tiny, coder_model, strong_model, embed}

    # Trim to disk budget: drop largest models first, keep tiny + embed
    def _estimate(s: set[str]) -> float:
        return sum(_MODEL_SIZES_GIB.get(t, 2.0) for t in s)

    ordered = sorted(pull_set, key=lambda t: -_MODEL_SIZES_GIB.get(t, 5.0))
    total = _estimate(pull_set)
    while total > disk_budget_gib and len(pull_set) > 2 and ordered:
        drop = ordered.pop(0)
        if drop in (tiny, embed):
            continue
        pull_set.discard(drop)
        total = _estimate(pull_set)
        # Downgrade routing entries that reference the dropped model
        for rcfg in routing.values():
            if rcfg.get("primary") == drop:
                rcfg["primary"] = tiny
            if rcfg.get("fallback") == drop:
                rcfg["fallback"] = tiny

    return {
        "tier": tier,
        "ram_budget_gib": effective_ram,
        "disk_budget_gib": disk_budget_gib,
        "estimated_pull_gib": round(_estimate(pull_set), 2),
        "ollama_tags": sorted(pull_set),
        "routing": routing,
        "embed_tag": embed,
        "notes": (
            "Cloud fallbacks (Anthropic/OpenAI) are not auto-configured; "
            "set manually in models.yaml if desired."
        ),
    }


# ── Public: pull with progress ────────────────────────────────────────────────

def pull_ollama_tags(tags: list[str]) -> list[dict[str, Any]]:
    """Pull Ollama models with a Rich progress panel. Skips already-present models."""
    already_pulled = _list_ollama_tags()
    results: list[dict[str, Any]] = []

    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
        from sage.cli.branding import get_console
        c = get_console()

        for tag in tags:
            if tag in already_pulled:
                c.print(f"  [dim]✓ {tag} already present — skipping[/dim]")
                results.append({"tag": tag, "ok": True, "skipped": True})
                continue

            size_hint = f"~{_MODEL_SIZES_GIB.get(tag, '?')} GiB"
            c.print(f"  [brand]↓[/brand] Pulling [accent]{tag}[/accent] ({size_hint}) …")
            code, out, err = _run_capture(["ollama", "pull", tag], timeout=1800.0)
            if code == 0:
                c.print(f"    [bold green]✓[/bold green] {tag}")
            else:
                c.print(f"    [bold red]✗[/bold red] {tag}: {(err or '')[:120]}")
            results.append({"tag": tag, "ok": code == 0, "skipped": False, "stderr": (err or "")[:500]})

    except Exception:
        # Fallback: plain output
        for tag in tags:
            if tag in already_pulled:
                print(f"[SAGE] {tag} already present — skipping")
                results.append({"tag": tag, "ok": True, "skipped": True})
                continue
            print(f"[SAGE] Pulling {tag} …")
            code, out, err = _run_capture(["ollama", "pull", tag], timeout=1800.0)
            results.append({"tag": tag, "ok": code == 0, "skipped": False, "stderr": (err or "")[:500]})

    return results


def _list_ollama_tags() -> set[str]:
    code, out, _ = _run_capture(["ollama", "list"], timeout=10.0)
    if code != 0 or not out.strip():
        return set()
    tags: set[str] = set()
    for line in out.strip().splitlines()[1:]:  # skip header
        parts = line.split()
        if parts:
            tags.add(parts[0])
    return tags


# ── Public: models.yaml helpers ───────────────────────────────────────────────

def apply_routing_to_config(
    base: dict[str, Any],
    suggestion: dict[str, Any],
) -> dict[str, Any]:
    """Merge suggested routing into an existing models.yaml dict."""
    out = dict(base)
    routing = dict(out.get("routing") or {})
    for role, cfg in suggestion["routing"].items():
        entry: dict[str, Any] = {
            "primary": cfg["primary"],
            "fallback": cfg["fallback"],
            "fallback_triggers": list(cfg.get("fallback_triggers") or []),
        }
        if "context_window" in cfg:
            entry["context_window"] = cfg["context_window"]
        routing[role] = entry
    out["routing"] = routing
    out["_sage_tier"] = suggestion["tier"]
    out["_sage_ram_budget_gib"] = suggestion["ram_budget_gib"]
    return out


def write_models_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


# ── Public: hardware.json persistence ────────────────────────────────────────

def save_hardware_json(config: AllocationConfig, sage_dir: Path = Path(".sage")) -> Path:
    """Persist allocation config to .sage/hardware.json."""
    path = sage_dir / "hardware.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    return path


def load_hardware_json(sage_dir: Path = Path(".sage")) -> AllocationConfig | None:
    """Load previously saved allocation config. Returns None if absent or corrupt."""
    path = sage_dir / "hardware.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AllocationConfig(
            ram_budget_gib=float(data["ram_budget_gib"]),
            quality_preference=str(data.get("quality_preference", "balanced")),
            disk_budget_gib=float(data.get("disk_budget_gib", 18.0)),
        )
    except Exception:
        return None
