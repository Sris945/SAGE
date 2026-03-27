"""
SAGE Debugger Agent
-------------------
Triggered when a Coder task fails or produces a file that fails verification.

Pipeline:
  1. Receive ErrorReport (task_id, error_message, failed_file, stack_trace)
  2. Load debugger.md template
  3. Call Ollama (devstral:latest primary) with error context
  4. Parse JSON PatchRequest (same format as Coder output)
  5. Apply fix via ToolExecutionEngine
  6. Store fix pattern to memory/fixes/error_patterns.json if successful

Fix-pattern storage schema:
  {
    "error_fingerprint": "sha256 of error message first 200 chars",
    "suspected_cause": "...",
    "fix_operation": "edit|create|run_command",
    "fix_file": "...",
    "success_count": 1,
    "last_seen": "ISO timestamp"
  }
"""

import json
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.orchestrator.model_router import ModelRouter
from sage.protocol.schemas import PatchRequest
from sage.protocol.schemas import AgentInsight
from sage.execution.executor import ToolExecutionEngine
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "debugger.md"
FIX_PATTERNS_PATH = Path("memory") / "fixes" / "error_patterns.json"


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text()
    return ""


def _extract_json(text: str):
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    arr_match = re.search(r"\[[\s\S]+\]", text)
    obj_match = re.search(r"\{[\s\S]+\}", text)
    if obj_match and (not arr_match or obj_match.start() < arr_match.start()):
        return json.loads(obj_match.group())
    if arr_match:
        return json.loads(arr_match.group())
    raise ValueError(f"No JSON in debugger response:\n{text[:400]}")


def _normalise_data(raw_data) -> dict:
    if isinstance(raw_data, list):
        for op in raw_data:
            if op.get("op") in ("add", "replace"):
                return {
                    "file": op.get("path", "output.py").lstrip("/"),
                    "operation": "create" if op.get("op") == "add" else "edit",
                    "patch": op.get("value", ""),
                    "reason": "Debug fix by agent",
                    "suspected_cause": "unknown",
                    "epistemic_flags": [],
                }
    return raw_data


def _to_patch_request(data: dict) -> PatchRequest:
    file_val = (
        data.get("file")
        or data.get("filepath")
        or data.get("path")
        or data.get("filename", "output.py")
    )
    file_val = str(file_val).lstrip("/")
    patch_val = (
        data.get("patch")
        or data.get("content")
        or data.get("code")
        or data.get("body")
        or data.get("value", "")
    )
    if not isinstance(patch_val, str):
        patch_val = json.dumps(patch_val, indent=2)
    return PatchRequest(
        file=file_val,
        operation=data.get("operation", "edit").split("|")[0].strip().lower(),
        patch=patch_val,
        reason=data.get("reason", ""),
        epistemic_flags=data.get("epistemic_flags", []),
    )


def _error_fingerprint(error: str) -> str:
    return hashlib.sha256(error[:200].encode()).hexdigest()[:16]


def _save_fix_pattern(error: str, data: dict, patch_req: PatchRequest) -> None:
    """
    Save an applied fix into SAGE's fix-pattern store.

    The store format is aligned with `memory/fixes/error_patterns.json`:
      - error_signature
      - suspected_cause
      - fix_operation / fix_file / fix_patch
      - success_rate, times_applied, last_used
    """
    from sage.memory.manager import MemoryManager

    error_signature = _error_fingerprint(error)
    mm = MemoryManager()
    mm.save_fix_pattern(
        {
            "error_signature": error_signature,
            "suspected_cause": data.get("suspected_cause", "unknown"),
            "fix_operation": patch_req.operation,
            "fix_file": patch_req.file,
            "fix_patch": patch_req.patch,
            "success_rate": 1.0,
            "times_applied": 1,
            "last_used": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": "debugger",
        }
    )


class DebuggerAgent:
    def __init__(self):
        self.router = ModelRouter()
        self.template = _load_template()
        # NOTE: DebuggerAgent must only emit PatchRequest; the workflow's
        # `tool_executor` will apply patches safely.
        self.executor = ToolExecutionEngine()

    def run(
        self,
        task: dict,
        error: str,
        failed_file: str = "",
        memory: dict | None = None,
        failure_count: int = 0,
        universal_prefix: str = "",
        insight_sink=None,
    ) -> dict:
        """
        Attempt to generate a fix patch for a failed task.

        Returns:
          {
            "status": "patch_ready" | "failed",
            "patch_request": {...},
            "file": str,
            "operation": str,
            "reason": str,
            "suspected_cause": str,
            "error_signature": str,
            "fix_generated": bool,
            "epistemic_flags": list[str],
            "error": str | None
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
                        agent="debugger",
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
            "debugger",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=failure_count,
        )
        memory = memory or {}

        system = (
            self.template.replace("{error_report}", error)
            .replace("{failed_file}", failed_file)
            .replace("{task_description}", task.get("description", ""))
        )
        if universal_prefix:
            system = universal_prefix + "\n\n" + system

        print(f"\n[Debugger] Using model: {model}")
        print(f"[Debugger] Error: {error[:120]}")

        _emit(
            "decision",
            severity="low",
            content=f"Debugger selected model={model} for error fix.",
        )

        if ollama is None:
            _emit(
                "risk",
                severity="high",
                content="ollama module not available; cannot generate PatchRequest.",
                requires_orchestrator_action=True,
            )
            err = "ollama module not available"
            return {
                "status": "failed",
                "file": failed_file,
                "error": err,
                "suspected_cause": "dependency_missing",
                "fix_generated": False,
                "error_signature": _error_fingerprint(error),
                "epistemic_flags": [],
            }

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Fix the following error.\n\n"
                            f"ERROR: {error}\n"
                            f"FILE: {failed_file}\n"
                            f"TASK: {task.get('description', '')}\n\n"
                            "Return ONLY a JSON PatchRequest. No prose."
                        ),
                    },
                ],
                options={"temperature": 0.05},
                timeout_s=8.0,
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            _emit(
                "risk",
                severity="high",
                content=f"Debugger LLM call failed/timeout: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return {
                "status": "failed",
                "file": failed_file,
                "error": str(e),
                "suspected_cause": "model call failed",
                "fix_generated": False,
                "error_signature": _error_fingerprint(error),
                "epistemic_flags": [],
            }

        raw = response["message"]["content"]

        try:
            raw_data = _extract_json(raw)
            data = _normalise_data(raw_data)
            patch_req = _to_patch_request(data)
        except (ValueError, json.JSONDecodeError, KeyError) as e:
            print(f"[Debugger] Parse failed: {e}")
            _emit(
                "risk",
                severity="high",
                content=f"Failed to parse Debugger output into PatchRequest: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return {
                "status": "failed",
                "file": failed_file,
                "error": str(e),
                "suspected_cause": "parse failed",
                "fix_applied": False,
            }

        print(f"[Debugger] ✓ Fix generated → {patch_req.file} ({patch_req.operation})")
        print(f"[Debugger] Suspected cause: {data.get('suspected_cause', 'unknown')}")

        _emit(
            "observation",
            severity="low",
            content=(
                f"PatchRequest ready: file={patch_req.file}, operation={patch_req.operation}, "
                f"suspected_cause={data.get('suspected_cause', '')}"
            ),
        )
        return {
            "status": "patch_ready",
            "patch_request": vars(patch_req),
            "file": patch_req.file,
            "operation": patch_req.operation,
            "reason": patch_req.reason,
            "suspected_cause": data.get("suspected_cause", ""),
            "error_signature": _error_fingerprint(error),
            "fix_generated": True,
            "epistemic_flags": patch_req.epistemic_flags,
            "error": None,
        }
