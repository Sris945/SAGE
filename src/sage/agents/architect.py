"""
SAGE Architect Agent
---------------------
Runs BEFORE the CoderAgent on any task where no existing file structure exists.
Decides:
  - What folder(s)/files the Coder should create
  - Which tech decisions apply (framework, naming conventions, etc.)
  - Returns a "blueprint" that seeds the Coder's prompt context

Input:  task dict + session_memory
Output: {"folders": [...], "files": [...], "tech_decisions": {...}, "summary": "..."}

Blueprint is stored in session_memory["architect_blueprint"] so every downstream
CoderAgent call can reference it without re-running the architect.

Primary model: As per model_router "architect" role.
"""

import json
import re
from pathlib import Path

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.orchestrator.model_router import ModelRouter
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout
from sage.protocol.schemas import AgentInsight

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "architect.md"


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text()
    return ""


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    match = re.search(r"\{[\s\S]+\}", text)
    if not match:
        raise ValueError(f"No JSON in architect response:\n{text[:300]}")
    return json.loads(match.group())


class ArchitectAgent:
    def __init__(self):
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
        """
        Generate a project-level blueprint for the given task.

        Returns:
          {
            "status": "completed" | "failed",
            "blueprint": {
              "folders": ["src/", "tests/", ...],
              "files":   ["src/app.py", "tests/test_app.py", ...],
              "tech_decisions": {"framework": "FastAPI", "test_runner": "pytest"},
              "summary": "FastAPI app with pytest in src/ layout"
            }
          }
        """

        # Small helper: emit AgentInsight packets if an orchestrator sink exists.
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
                        agent="architect",
                        task_id=str(task.get("id", "")),
                        insight_type=insight_type,
                        content=(content or "")[:2000],
                        severity=severity,
                        requires_orchestrator_action=requires_orchestrator_action,
                    )
                )
            except Exception:
                return

        model = self.router.select(
            "architect",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=failure_count,
        )
        print(f"\n[Architect] Using model: {model}")
        print(f"[Architect] Designing blueprint for: {task.get('description', '')[:80]}")

        _emit(
            "decision",
            severity="low",
            content=f"Architect selected model={model} for blueprint generation.",
        )

        system = self.template.replace("{task_description}", task.get("description", "")).replace(
            "{project_memory_summary}", json.dumps(memory, indent=2)
        )
        if universal_prefix:
            system = universal_prefix + "\n\n" + system

        if ollama is None:
            print("[Architect] WARNING: ollama module not available; skipping blueprint.")
            _emit(
                "risk",
                severity="high",
                content="ollama module not available; cannot generate blueprint.",
                requires_orchestrator_action=True,
            )
            return {"status": "skipped", "blueprint": {}}

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Design the project blueprint for:\n\n"
                            f"TASK: {task.get('description', '')}\n\n"
                            "Return ONLY a JSON blueprint. No prose."
                        ),
                    },
                ],
                options={"temperature": 0.0},
                timeout_s=8.0,
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            print(f"[Architect] Model call failed/timeout: {e} — skipping blueprint.")
            _emit(
                "risk",
                severity="high",
                content=f"Architect model call failed/timeout: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return {"status": "skipped", "blueprint": {}}

        raw = response["message"]["content"]
        try:
            data = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"[Architect] Parse failed: {e} — skipping blueprint.")
            _emit(
                "risk",
                severity="high",
                content=f"Architect response parse failed: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return {"status": "skipped", "blueprint": {}}

        blueprint = {
            "folders": data.get("folders", []),
            "files": data.get("files", []),
            "tech_decisions": data.get("tech_decisions", {}),
            "summary": data.get("summary", ""),
        }

        print(
            f"[Architect] ✓ Blueprint ready — {len(blueprint['files'])} file(s), "
            f"{len(blueprint['folders'])} folder(s)"
        )
        if blueprint["summary"]:
            print(f"[Architect]   {blueprint['summary']}")

        _emit(
            "observation",
            severity="low",
            content=(
                f"Blueprint ready: folders={len(blueprint['folders'])}, "
                f"files={len(blueprint['files'])}"
            ),
        )

        return {"status": "completed", "blueprint": blueprint}
