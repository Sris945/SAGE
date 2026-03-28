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
import hashlib
from pathlib import Path
from datetime import datetime, timezone

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_patch_json
from sage.debug_mode_log import agent_debug_log
from sage.cli.branding import print_agent_line
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


def _normalise_data(raw_data) -> dict:
    """
    ``parse_patch_json`` may return a dict (PatchRequest) or a list (JSON Patch ops
    or occasionally a list of candidate objects). Never pass a bare list to
    ``_to_patch_request`` — that caused AttributeError in the wild.
    """
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, list):
        if len(raw_data) == 0:
            raise ValueError("Debugger model returned empty JSON array [] (no patch).")
        # RFC-6902 JSON Patch: [{"op":"add","path":"...","value":"..."}, ...]
        for op in raw_data:
            if not isinstance(op, dict):
                continue
            if op.get("op") in ("add", "replace"):
                return {
                    "file": op.get("path", "output.py").lstrip("/"),
                    "operation": "create" if op.get("op") == "add" else "edit",
                    "patch": op.get("value", ""),
                    "reason": "Debug fix by agent",
                    "suspected_cause": "unknown",
                    "epistemic_flags": [],
                }
        # Some models emit [ { "file": "...", "patch": "...", ... } ]
        for item in raw_data:
            if isinstance(item, dict) and (
                "file" in item or "patch" in item or "operation" in item
            ):
                return item
        raise ValueError(
            "Debugger JSON was a list that could not be mapped to a PatchRequest "
            f"(len={len(raw_data)})."
        )
    raise ValueError(f"Debugger JSON must be an object or array, got {type(raw_data).__name__}")


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

    # ── Private helpers ──────────────────────────────────────────────────────

    def _build_debug_prompt(
        self,
        task: dict,
        error: str,
        failed_file: str,
        memory: dict,
        prefix: str,
        failure_count: int,
    ) -> str:
        """
        Build the structured 4-phase debug prompt.

        The LLM is forced to reason through reproduction, isolation, hypothesis,
        and patch in a single structured JSON response. Contextual memory and
        failure history are included so the model can avoid repeating past mistakes.
        """
        memory_summary = json.dumps(memory, indent=2) if memory else "No prior state"
        fix_patterns_raw = memory.get("retrieved_fix_patterns") or []
        fix_patterns = json.dumps(fix_patterns_raw, indent=2) if fix_patterns_raw else "None"

        template_section = (
            self.template.replace("{error_report}", error)
            .replace("{failed_file}", failed_file)
            .replace("{task_description}", task.get("description", ""))
        )

        structured_instructions = f"""
You are a structured debugger. You must respond with a single JSON object following the exact
4-phase schema below. Do not include any text outside the JSON.

CONTEXT:
  Task description : {task.get("description", "(none)")}
  Failed file      : {failed_file or "(none)"}
  Failure attempt  : #{failure_count + 1}
  Project memory   : {memory_summary[:2000]}
  Known fix patterns: {fix_patterns[:1000]}

ERROR:
{error}

OUTPUT SCHEMA (respond with this exact structure — all fields required):
{{
  "phase_1_reproduce": {{
    "error_type": "ImportError|RuntimeError|TestFailure|SyntaxError|TypeError|LogicError|Other",
    "error_location": "file:line or function name",
    "reproduction_steps": "minimal steps to reproduce"
  }},
  "phase_2_isolate": {{
    "affected_components": ["list of files/functions involved"],
    "root_cause_candidates": ["candidate 1", "candidate 2"],
    "eliminated_causes": ["what it is NOT and why"]
  }},
  "phase_3_hypothesize": {{
    "most_likely_cause": "specific, concrete hypothesis",
    "confidence": 0.0,
    "reasoning": "why this specific cause leads to the observed error"
  }},
  "phase_4_patch": {{
    "file": "path/to/fix",
    "operation": "edit",
    "patch": "full corrected file content",
    "reason": "one sentence: why this patch fixes the root cause from phase 3",
    "suspected_cause": "brief cause label (confidence 0-1)",
    "epistemic_flags": []
  }}
}}

RULES:
- operation must be exactly ONE of: edit, create, run_command
- patch must be the COMPLETE corrected file content for edit/create
- Do not patch symptoms. Fix the root cause identified in phase_3_hypothesize.
- epistemic_flags: ["INFERRED"] if guessing, [] if confident
- confidence in phase_3_hypothesize: 0.0 (uncertain) to 1.0 (certain)

{template_section}
"""
        if prefix:
            return prefix + "\n\n" + structured_instructions
        return structured_instructions

    def _record_debug_pattern(
        self,
        error_text: str,
        patch_request: dict,
        task_id: str,
    ) -> None:
        """
        Best-effort: save a PATTERN_LEARNED event and persist the fix pattern to memory.

        This method MUST NOT raise — any exception is silently swallowed so that
        pattern recording never interrupts the orchestration pipeline.
        """
        try:
            from sage.memory.manager import MemoryManager

            error_signature = _error_fingerprint(error_text)
            MemoryManager().save_fix_pattern(
                {
                    "error_signature": error_signature,
                    "suspected_cause": patch_request.get("suspected_cause", "unknown"),
                    "fix_operation": patch_request.get("operation", "edit"),
                    "fix_file": patch_request.get("file", ""),
                    "fix_patch": (patch_request.get("patch") or "")[:500],
                    "success_rate": 1.0,
                    "times_applied": 1,
                    "last_used": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "source": "debugger_4phase",
                    "task_id": task_id,
                }
            )
        except Exception:
            pass

        try:
            from sage.observability.structured_logger import log_event

            log_event(
                "PATTERN_LEARNED",
                payload={
                    "task_id": task_id,
                    "error_signature": _error_fingerprint(error_text),
                    "fix_file": patch_request.get("file", ""),
                    "fix_operation": patch_request.get("operation", ""),
                    "suspected_cause": patch_request.get("suspected_cause", ""),
                    "source": "debugger_4phase",
                },
            )
        except Exception:
            pass

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

        agent_debug_log(
            hypothesis_id="H_debugger",
            location="debugger.py:run",
            message="debugger_invoked",
            data={
                "task_id": str(task.get("id", "")),
                "failed_file": failed_file,
                "error_head": (error or "")[:500],
            },
        )

        model = self.router.select(
            "debugger",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=failure_count,
        )
        memory = memory or {}

        # Build structured 4-phase prompt
        system = self._build_debug_prompt(
            task=task,
            error=error,
            failed_file=failed_file,
            memory=memory,
            prefix=universal_prefix,
            failure_count=failure_count,
        )

        print_agent_line("Debugger", f"Using model: {model}")
        err_disp = (error or "").strip() or "(no error text — check reviewer/verify output)"
        print_agent_line("Debugger", f"Error: {err_disp[:200]}")

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
                timeout_s=None,
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

        msg = response.get("message") or {}
        raw = msg.get("content", "") if isinstance(msg, dict) else ""

        try:
            raw_data = parse_patch_json(raw)
            # Handle 4-phase structured output: extract phase_4_patch as the patch dict
            if isinstance(raw_data, dict) and "phase_4_patch" in raw_data:
                phase4 = raw_data["phase_4_patch"]
                # Enrich with suspected_cause from phase_3 if available
                phase3 = raw_data.get("phase_3_hypothesize", {})
                if "suspected_cause" not in phase4 and phase3.get("most_likely_cause"):
                    confidence = phase3.get("confidence", 0.8)
                    phase4["suspected_cause"] = f"{phase3['most_likely_cause']} ({confidence:.2f})"
                data = _normalise_data(phase4)
                # Store full 4-phase analysis for observability
                debug_phases = {k: v for k, v in raw_data.items() if k.startswith("phase_")}
            else:
                data = _normalise_data(raw_data)
                debug_phases = {}
            patch_req = _to_patch_request(data)
        except (ValueError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
            print_agent_line("Debugger", f"Parse failed: {e}")
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
                "fix_generated": False,
                "error_signature": _error_fingerprint(error),
                "epistemic_flags": [],
            }

        if not str(patch_req.patch or "").strip():
            err = "debugger model returned empty patch"
            print_agent_line("Debugger", err)
            _emit(
                "risk",
                severity="high",
                content=err,
                requires_orchestrator_action=True,
            )
            return {
                "status": "failed",
                "file": failed_file,
                "error": err,
                "suspected_cause": "empty_patch",
                "fix_generated": False,
                "error_signature": _error_fingerprint(error),
                "epistemic_flags": [],
            }

        suspected_cause = data.get("suspected_cause", "")
        print_agent_line("Debugger", f"Fix generated → {patch_req.file} ({patch_req.operation})")
        print_agent_line("Debugger", f"Suspected cause: {suspected_cause or 'unknown'}")

        # Emit 4-phase reasoning summary if available
        if debug_phases:
            phase3 = debug_phases.get("phase_3_hypothesize", {})
            confidence = phase3.get("confidence", 0.0)
            most_likely = phase3.get("most_likely_cause", "")
            if most_likely:
                print_agent_line(
                    "Debugger",
                    f"Root cause (confidence={confidence:.2f}): {most_likely[:120]}",
                )

        _emit(
            "observation",
            severity="low",
            content=(
                f"PatchRequest ready: file={patch_req.file}, operation={patch_req.operation}, "
                f"suspected_cause={suspected_cause}"
            ),
        )

        # Record learned pattern (best-effort — never crashes caller)
        self._record_debug_pattern(
            error_text=error,
            patch_request={
                **vars(patch_req),
                "suspected_cause": suspected_cause,
            },
            task_id=str(task.get("id", "")),
        )

        return {
            "status": "patch_ready",
            "patch_request": vars(patch_req),
            "file": patch_req.file,
            "operation": patch_req.operation,
            "reason": patch_req.reason,
            "suspected_cause": suspected_cause,
            "error_signature": _error_fingerprint(error),
            "fix_generated": True,
            "epistemic_flags": patch_req.epistemic_flags,
            "error": None,
            "debug_phases": debug_phases,
        }
