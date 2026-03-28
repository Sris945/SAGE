"""
SAGE Documentation Agent
------------------------
Writes or updates markdown documentation via PatchRequest (applied by ``tool_executor``).

Use for README, CONTRIBUTING, CHANGELOG, and ``docs/*.md`` tasks assigned by the planner.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_json_object
from sage.cli.branding import print_agent_line
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout
from sage.orchestrator.model_router import ModelRouter
from sage.protocol.schemas import AgentInsight

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "documentation.md"
MAX_EXCERPT_LINES = 120


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text()
    return ""


def _infer_doc_path(task_description: str) -> str:
    d = (task_description or "").lower()
    raw = task_description or ""
    if "contributing" in d:
        return "CONTRIBUTING.md"
    if "changelog" in d:
        return "CHANGELOG.md"
    m = re.search(r"`(docs/[a-zA-Z0-9_./-]+\.md)`", raw)
    if m:
        return m.group(1).replace("\\", "/")
    m2 = re.search(r"\bdocs/[a-zA-Z0-9_./-]+\.md\b", raw)
    if m2:
        return m2.group(0).replace("\\", "/")
    if "readme" in d:
        return "README.md"
    return "README.md"


def _read_excerpt(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        return "(no existing file)"
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    body = "\n".join(lines[:MAX_EXCERPT_LINES])
    if len(lines) > MAX_EXCERPT_LINES:
        body += "\n\n… (truncated for prompt)"
    return body or "(empty file)"


class DocumentationAgent:
    def __init__(self) -> None:
        self.router = ModelRouter()
        self.template = _load_template()

    def run(
        self,
        task: dict,
        memory: dict,
        failure_count: int = 0,
        universal_prefix: str = "",
        insight_sink=None,
    ) -> dict:
        _ = memory

        def _emit(
            insight_type: str,
            *,
            severity: str,
            content: str,
            requires_orchestrator_action: bool = False,
        ) -> None:
            if insight_sink is None:
                return
            try:
                insight_sink.ingest(
                    AgentInsight(
                        agent="documentation",
                        task_id=str(task.get("id", "")),
                        insight_type=insight_type,
                        content=(content or "")[:2000],
                        severity=severity,
                        requires_orchestrator_action=requires_orchestrator_action,
                    )
                )
            except Exception:
                return

        target = _infer_doc_path(str(task.get("description", "")))
        excerpt = _read_excerpt(target)

        model = self.router.select(
            "documentation",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=int(failure_count),
        )
        print_agent_line("Documentation", f"Using model: {model}")
        print_agent_line("Documentation", f"Target doc: {target}")

        system = (
            (self.template or "# Documentation\nEmit PatchRequest JSON for markdown.\n")
            .replace("{task_description}", str(task.get("description", "")))
            .replace("{target_doc_file}", target)
            .replace("{existing_excerpt}", excerpt)
        )
        if universal_prefix:
            system = universal_prefix + "\n\n" + system

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Produce the markdown PatchRequest for `{target}`. "
                            "Return ONLY JSON. No prose."
                        ),
                    },
                ],
                options={"temperature": 0.15},
                timeout_s=None,
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            print_agent_line("Documentation", f"Model call failed: {e}")
            _emit(
                "risk",
                severity="high",
                content=str(e)[:1200],
                requires_orchestrator_action=True,
            )
            return {"status": "failed", "file": target, "error": str(e)}

        msg = response.get("message") or {}
        raw = msg.get("content", "") if isinstance(msg, dict) else ""
        try:
            data = parse_json_object(raw)
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            print_agent_line("Documentation", f"Parse failed: {e}")
            _emit(
                "risk",
                severity="high",
                content=f"documentation parse error: {e}",
                requires_orchestrator_action=True,
            )
            return {"status": "failed", "file": target, "error": str(e)}

        out_file = str(
            data.get("file") or data.get("path") or data.get("filepath") or target
        ).lstrip("/\\")
        operation = str(data.get("operation", "create")).split("|")[0].strip().lower()
        if operation not in ("create", "edit"):
            operation = "create" if not Path(out_file).exists() else "edit"
        body = (
            data.get("patch") or data.get("content") or data.get("body") or data.get("value") or ""
        )
        if not isinstance(body, str):
            body = json.dumps(body, indent=2) if body is not None else ""
        if not body.strip():
            return {"status": "failed", "file": out_file, "error": "empty patch body"}

        patch_request = {
            "file": out_file,
            "operation": operation,
            "patch": body,
            "reason": str(data.get("reason", "") or "documentation update"),
            "epistemic_flags": data.get("epistemic_flags", []) or [],
        }

        return {
            "status": "patch_ready",
            "file": out_file,
            "patch_request": patch_request,
            "model_used": model,
            "strategy_key": "",
        }
