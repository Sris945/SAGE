"""
Skill Injector
--------------
Prompt-injects selected `SKILL.md` content from the bundled SAGE skills tree
(`src/sage/assets/skills/`) into the universal prefix.

Layout (first-party):

- ``discipline/`` — engineering discipline (TDD, verification, debugging)
- ``workflow/`` — execution patterns (coverage loop, prompts, verification, docs)
- ``planning/`` — orchestration (plans, exploration)

Optional override: set ``SAGE_SKILLS_ROOT`` to a directory that mirrors the same
three top-level folders.

Deterministic:
  - fixed skill sets per agent role (+ error-keyword augmentation)
  - optional lightweight task_description keywords
  - per-skill and total character caps (token-efficiency)
  - in-process cache of loaded files
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SkillSpec:
    path: str
    max_chars: int = 3200


def _sage_package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bundled_skills_root() -> Path:
    override = (os.environ.get("SAGE_SKILLS_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _sage_package_root() / "assets" / "skills"


def bundled_skills_root() -> Path:
    """Directory containing ``discipline/``, ``workflow/``, ``planning/`` skill trees."""
    return _bundled_skills_root()


def _safe_read_text(path: Path) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(errors="ignore")
    except OSError:
        return ""


@lru_cache(maxsize=256)
def _load_skill_text(abs_path: str) -> str:
    return _safe_read_text(Path(abs_path))


def clear_skill_text_cache() -> None:
    """Test helper: invalidate LRU cache after swapping files."""
    _load_skill_text.cache_clear()


def _format_skill_block(skill_title: str, content: str) -> str:
    c = (content or "").strip()
    if not c:
        return ""
    c = c[:3500]
    return f"### {skill_title}\n{c}"


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _max_total_chars() -> int:
    v = (os.environ.get("SAGE_MAX_SKILL_CHARS_TOTAL") or "").strip()
    if not v:
        return 12_000
    try:
        return max(1000, int(v))
    except ValueError:
        return 12_000


def _discipline_skill_root() -> Path:
    return _bundled_skills_root() / "discipline"


def _workflow_skill_root() -> Path:
    return _bundled_skills_root() / "workflow"


def _planning_skill_root() -> Path:
    return _bundled_skills_root() / "planning"


def _select_skills(
    *,
    agent_role: str,
    task_description: str,
    last_error: str,
) -> list[_SkillSpec]:
    role = (agent_role or "").lower()
    err = (last_error or "").lower()
    task = (task_description or "").lower()

    specs: list[_SkillSpec] = []

    if role in ("coder", "test_engineer", "reviewer"):
        specs.extend(
            [
                _SkillSpec("discipline/test-driven-development/SKILL.md"),
                _SkillSpec("discipline/verification-before-completion/SKILL.md"),
            ]
        )
    if role == "debugger":
        specs.append(_SkillSpec("discipline/systematic-debugging/SKILL.md"))

    if role != "debugger":
        if any(k in err for k in ["syntaxerror", "traceback", "parse failed", "json", "stack"]):
            specs.append(_SkillSpec("discipline/systematic-debugging/SKILL.md"))

    if role in ("coder", "test_engineer"):
        specs.extend(
            [
                _SkillSpec("workflow/tdd-workflow/SKILL.md"),
                _SkillSpec("workflow/prompt-optimizer/SKILL.md"),
            ]
        )
    if role in ("reviewer", "test_engineer"):
        specs.append(_SkillSpec("workflow/verification-loop/SKILL.md"))
    if role in ("planner", "coder", "debugger"):
        specs.append(_SkillSpec("workflow/documentation-lookup/SKILL.md"))

    if role == "planner":
        specs.append(_SkillSpec("planning/make-plan/SKILL.md"))
        specs.append(_SkillSpec("planning/smart-explore/SKILL.md"))

    if task and role in ("coder", "test_engineer", "reviewer"):
        if any(k in task for k in ("test", "pytest", "coverage", "tdd")):
            specs.append(_SkillSpec("discipline/test-driven-development/SKILL.md"))
        if any(k in task for k in ("debug", "traceback", "stack trace", "error")):
            specs.append(_SkillSpec("discipline/systematic-debugging/SKILL.md"))

    seen: set[str] = set()
    out: list[_SkillSpec] = []
    for s in specs:
        if s.path in seen:
            continue
        seen.add(s.path)
        out.append(s)
    return out


def _resolve_spec_path(spec: _SkillSpec) -> tuple[str, str]:
    """Returns (absolute_path, display_title)."""
    if spec.path.startswith("discipline/"):
        rel = spec.path.replace("discipline/", "")
        abs_path = str(_discipline_skill_root() / rel)
        title = f"sage:discipline:{rel}"
    elif spec.path.startswith("workflow/"):
        rel = spec.path.replace("workflow/", "")
        abs_path = str(_workflow_skill_root() / rel)
        title = f"sage:workflow:{rel}"
    elif spec.path.startswith("planning/"):
        rel = spec.path.replace("planning/", "")
        abs_path = str(_planning_skill_root() / rel)
        title = f"sage:planning:{rel}"
    else:
        return "", ""
    return abs_path, title


def get_skill_injection_context(
    *,
    agent_role: str,
    task_description: str,
    last_error: str = "",
) -> str:
    """
    Returns markdown to inject into prompts, or "" if no skills resolved.
    """
    specs = _select_skills(
        agent_role=agent_role, task_description=task_description, last_error=last_error
    )

    blocks: list[str] = []
    meta_ids: list[str] = []
    meta_hashes: list[str] = []
    char_counts: list[int] = []
    total_used = 0
    cap = _max_total_chars()

    for spec in specs:
        abs_path, title = _resolve_spec_path(spec)
        if not abs_path:
            continue
        raw = _load_skill_text(abs_path)
        if not raw.strip():
            continue
        slice_len = min(spec.max_chars, len(raw))
        body = raw[:slice_len]
        if total_used + len(body) > cap:
            remain = cap - total_used
            if remain <= 200:
                break
            body = body[:remain]
            slice_len = len(body)
        block = _format_skill_block(title, body)
        if not block.strip():
            continue
        blocks.append(block)
        meta_ids.append(title)
        meta_hashes.append(_short_hash(body))
        char_counts.append(slice_len)
        total_used += len(body)
        if total_used >= cap:
            break

    result = "\n\n".join([b for b in blocks if b.strip()])

    if result.strip():
        payload = {
            "agent_role": agent_role,
            "skill_ids": meta_ids,
            "content_sha256_16": meta_hashes,
            "per_skill_chars": char_counts,
            "total_chars": sum(char_counts),
            "approx_prompt_tokens": 1 + sum(char_counts) // 4,
        }
        logger.info("SKILL_INJECTION %s", json.dumps(payload, ensure_ascii=False))
        try:
            from sage.observability.structured_logger import log_event

            log_event("SKILL_INJECTION", payload=payload)
        except Exception:
            pass

    return result
