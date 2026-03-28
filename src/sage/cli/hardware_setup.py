"""
Hardware-aware Ollama model suggestions for SAGE.

Runs before heavy model use: detects OS, RAM, optional GPU VRAM (Linux/Windows),
then suggests a small set of Ollama tags that fit a disk budget (~15–20 GB total).
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Approximate on-disk sizes (GiB, rough) for budgeting — user pulls may vary by quant.
_MODEL_SIZES_GIB: dict[str, float] = {
    "qwen2.5-coder:1.5b": 1.0,
    "nomic-embed-text:latest": 0.3,
    "qwen2.5-coder:7b-instruct-q4_K_M": 4.5,
    "qwen2.5-coder:14b-instruct-q4_K_M": 9.0,
    "phi3:mini": 2.3,
    "llama3.2:3b": 2.0,
}


@dataclass
class HardwareProfile:
    os_name: str
    ram_gib: float | None = None
    vram_gib: float | None = None
    sources: dict[str, str] = field(default_factory=dict)
    raw_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name,
            "ram_gib": self.ram_gib,
            "vram_gib": self.vram_gib,
            "sources": self.sources,
            "raw_excerpt": self.raw_excerpt[:2000],
        }


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
                    parts = line.split()
                    kb = int(parts[1])
                    return round(kb / (1024 * 1024), 2)  # KiB -> GiB
    except OSError:
        pass
    return None


def _nvidia_vram_gib() -> float | None:
    code, out, _ = _run_capture(
        [
            "nvidia-smi",
            "--query-gpu=memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout=8.0,
    )
    if code != 0 or not out.strip():
        return None
    try:
        # "8192 MiB" or "8192" depending on driver
        first = out.strip().splitlines()[0].strip()
        m = re.search(r"([0-9]+)", first)
        if not m:
            return None
        mib = float(m.group(1))
        if "MiB" in first or mib > 256:  # likely MiB
            return round(mib / 1024, 2)
        return round(mib / 1024, 2)
    except Exception:
        return None


def _try_fastfetch_json() -> tuple[float | None, float | None, str]:
    code, out, _ = _run_capture(["fastfetch", "--json"], timeout=10.0)
    if code != 0 or not out.strip():
        return None, None, ""
    try:
        data = json.loads(out)
        ram = None
        vram = None
        blob = json.dumps(data)
        # Heuristic: "memory":{"total":...bytes} or MiB strings in result
        m = re.search(r'"total"\s*:\s*([0-9]{6,})', blob)
        if m:
            ram = round(int(m.group(1)) / (1024**3), 2)
        m2 = re.search(r'"dedicatedMemory"\s*:\s*([0-9]{6,})', blob, re.I)
        if m2:
            vram = round(int(m2.group(1)) / (1024**3), 2)
        return ram, vram, out[:1500]
    except Exception:
        return None, None, out[:1500]


def _try_neofetch_mem() -> tuple[float | None, str]:
    code, out, _ = _run_capture(["neofetch", "--stdout"], timeout=12.0)
    if code != 0:
        return None, ""
    # "Memory: 15GiB / 31GiB" or similar
    m = re.search(r"Memory:\s*([0-9.]+)\s*GiB", out, re.I)
    if m:
        return float(m.group(1)), out[:1500]
    return None, out[:1500]


def _windows_profile() -> HardwareProfile:
    ps = (
        "$m = Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty TotalPhysicalMemory; "
        "[math]::Round($m / 1GB, 2)"
    )
    code, out, err = _run_capture(
        ["powershell", "-NoProfile", "-Command", ps],
        timeout=15.0,
    )
    ram = None
    if code == 0 and out.strip():
        try:
            ram = float(out.strip().splitlines()[-1].strip())
        except ValueError:
            pass
    vram = None
    code2, out2, _ = _run_capture(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Where-Object { $_.AdapterRAM -and $_.AdapterRAM -gt 0 } | "
            "Select-Object -First 1 -ExpandProperty AdapterRAM",
        ],
        timeout=15.0,
    )
    if code2 == 0 and out2.strip():
        try:
            ar = int(out2.strip().splitlines()[0].strip())
            if ar > 0:
                vram = round(ar / (1024**3), 2)
        except (ValueError, IndexError):
            pass
    return HardwareProfile(
        os_name="windows",
        ram_gib=ram,
        vram_gib=vram,
        sources={"powershell": "memory+vram"},
        raw_excerpt=(err or "")[:500],
    )


def scan_hardware() -> HardwareProfile:
    system = platform.system().lower()
    if system == "windows":
        return _windows_profile()

    ram = _linux_mem_gib()
    vram = _nvidia_vram_gib()
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

    if vram is None:
        vram = _nvidia_vram_gib()
        if vram is not None:
            sources["nvidia-smi"] = "vram"

    return HardwareProfile(
        os_name="linux" if system == "linux" else system,
        ram_gib=ram,
        vram_gib=vram,
        sources=sources or {"proc": "meminfo"},
        raw_excerpt="\n".join(raw_parts)[:2000],
    )


def suggest_ollama_stack(
    profile: HardwareProfile,
    *,
    disk_budget_gib: float = 18.0,
) -> dict[str, Any]:
    """
    Return suggested Ollama tags + role mapping (local-only, fits budget).

    Tiers use VRAM when known; else RAM; else conservative tiny stack.
    """
    vram = profile.vram_gib
    ram = profile.ram_gib

    # Default: lightweight everywhere (~2–3 GB models + embed)
    tiny_primary = "qwen2.5-coder:1.5b"
    tiny_fallback = "qwen2.5-coder:7b-instruct-q4_K_M"
    med = "qwen2.5-coder:14b-instruct-q4_K_M"
    embed = "nomic-embed-text:latest"

    tier = "conservative"
    if vram is not None:
        if vram >= 14:
            tier = "comfortable"
        elif vram >= 8:
            tier = "balanced"
        elif vram >= 6:
            tier = "light"
        else:
            tier = "minimal"
    elif ram is not None:
        if ram >= 24:
            tier = "balanced"
        elif ram >= 16:
            tier = "light"
        else:
            tier = "minimal"

    if tier == "conservative":
        tier = "minimal"

    # Role-specific mapping (planner/architect/coder/reviewer/test_engineer/documentation/debugger/memory_optimizer)
    routing: dict[str, dict[str, str | list]] = {}

    if tier == "minimal":
        for role in (
            "planner",
            "architect",
            "coder",
            "reviewer",
            "test_engineer",
            "debugger",
            "memory_optimizer",
        ):
            routing[role] = {
                "primary": tiny_primary,
                "fallback": tiny_primary,
                "fallback_triggers": ["primary_failure_count >= 2"],
            }
        pull_set: set[str] = {tiny_primary, embed}
    elif tier == "light":
        routing = {
            "planner": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["task_complexity_score > 0.8"],
            },
            "architect": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["task_complexity_score > 0.8"],
            },
            "coder": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "reviewer": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "test_engineer": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "documentation": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "debugger": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 1"],
            },
            "memory_optimizer": {
                "primary": tiny_fallback,
                "fallback": tiny_primary,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
        }
        pull_set = {tiny_primary, tiny_fallback, embed}
    elif tier == "balanced":
        routing = {
            "planner": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["task_complexity_score > 0.8"],
            },
            "architect": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["task_complexity_score > 0.8"],
            },
            "coder": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "reviewer": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "test_engineer": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "documentation": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "debugger": {
                "primary": tiny_fallback,
                "fallback": med,
                "fallback_triggers": ["primary_failure_count >= 1"],
            },
            "memory_optimizer": {
                "primary": tiny_fallback,
                "fallback": med,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
        }
        pull_set = {tiny_primary, tiny_fallback, med, embed}
    else:  # comfortable
        routing = {
            "planner": {
                "primary": tiny_fallback,
                "fallback": med,
                "fallback_triggers": ["task_complexity_score > 0.8"],
            },
            "architect": {
                "primary": tiny_fallback,
                "fallback": med,
                "fallback_triggers": ["task_complexity_score > 0.8"],
            },
            "coder": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "reviewer": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "test_engineer": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "documentation": {
                "primary": tiny_primary,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
            "debugger": {
                "primary": tiny_fallback,
                "fallback": med,
                "fallback_triggers": ["primary_failure_count >= 1"],
            },
            "memory_optimizer": {
                "primary": med,
                "fallback": tiny_fallback,
                "fallback_triggers": ["primary_failure_count >= 2"],
            },
        }
        pull_set = {tiny_primary, tiny_fallback, med, embed}

    # Trim to disk budget: drop largest optional model first (keep tiny + embed)
    def _estimate(s: set[str]) -> float:
        return sum(_MODEL_SIZES_GIB.get(t, 2.0) for t in s)

    ordered = sorted(pull_set, key=lambda t: -_MODEL_SIZES_GIB.get(t, 5.0))
    total = _estimate(pull_set)
    while total > disk_budget_gib and len(pull_set) > 2 and ordered:
        drop = ordered.pop(0)
        if drop in (tiny_primary, embed):
            continue
        pull_set.discard(drop)
        total = _estimate(pull_set)
        if med not in pull_set:
            for rcfg in routing.values():
                if rcfg.get("primary") == med:
                    rcfg["primary"] = tiny_fallback
                if rcfg.get("fallback") == med:
                    rcfg["fallback"] = tiny_fallback

    estimated_gib = round(_estimate(pull_set), 2)

    return {
        "tier": tier,
        "disk_budget_gib": disk_budget_gib,
        "estimated_pull_gib": estimated_gib,
        "ollama_tags": sorted(pull_set),
        "routing": routing,
        "embed_tag": embed,
        "notes": "Cloud fallbacks (Anthropic/OpenAI) are not auto-configured; set in models.yaml if desired.",
    }


def apply_routing_to_config(
    base: dict[str, Any],
    suggestion: dict[str, Any],
) -> dict[str, Any]:
    out = dict(base)
    routing = dict(out.get("routing") or {})
    for role, cfg in suggestion["routing"].items():
        routing[role] = {
            "primary": cfg["primary"],
            "fallback": cfg["fallback"],
            "fallback_triggers": list(cfg.get("fallback_triggers") or []),
        }
    out["routing"] = routing
    return out


def write_models_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def pull_ollama_tags(tags: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for tag in tags:
        code, out, err = _run_capture(["ollama", "pull", tag], timeout=600.0)
        results.append({"tag": tag, "ok": code == 0, "stderr": (err or "")[:500]})
    return results
