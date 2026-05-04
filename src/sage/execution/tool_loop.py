"""
SAGE Agentic Tool-Use Loop
--------------------------
Replaces single-shot PatchRequest generation with a ReAct-style loop:

  system_prompt (task + tools) →
    model emits tool_call JSON →
    engine executes tool →
    result appended to conversation →
    repeat until model emits {"tool": "done"} or max_turns reached

This is the single biggest capability upgrade: the model can now read files,
grep for symbols, make surgical edits, run tests, see failures, and fix them
— all in one coherent conversation.

Design principles:
  - The conversation is a plain list of {"role", "content"} dicts — works with
    any chat API (Ollama, OpenAI, etc.)
  - Hard turn cap prevents infinite loops
  - Tool results are injected as assistant-prefixed "tool_result" messages
  - On loop exit the engine returns a LoopResult summarising all writes/creates
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sage.agents.llm_parse import parse_json_value, strip_llm_noise
from sage.tools.tool_registry import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DEFAULT_MAX_TURNS = 24          # generous — most tasks finish in 6-12 turns
TOOL_CALL_BUDGET_WARN = 18      # warn model when budget is running low

_DONE_SIGNAL = {"tool": "done"}


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    turn: int
    tool: str
    args: dict
    success: bool
    output_preview: str    # first 300 chars of result


@dataclass
class LoopResult:
    status: str            # "done" | "max_turns" | "error"
    turns: int
    files_written: list[str] = field(default_factory=list)
    files_edited: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    history: list[TurnRecord] = field(default_factory=list)
    final_summary: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return self.status in ("done",)


# ── System prompt builder ─────────────────────────────────────────────────────

_TOOL_LOOP_INSTRUCTIONS_TEMPLATE = """\
You are a precise coding agent. You accomplish tasks by calling tools one at a time.

TOOL CALL FORMAT — emit EXACTLY this JSON on its own (no prose around it):
{{"tool": "<name>", "args": {{<arguments>}}}}

To signal completion:
{{"tool": "done", "args": {{}}}}

RULES:
1. Read before you write — use read_file to see current content before editing.
2. Use edit_file (surgical) for changes to existing files; use write_file only for new files.
3. edit_file old_string must match the file EXACTLY (copy from read_file output).
4. After writing/editing, run the relevant tests with run_command to confirm correctness.
5. Fix test failures before calling done.
6. Never emit prose outside the JSON tool call — the engine cannot parse it.
7. If unsure where something is defined, use grep_code first.

{tool_catalogue}
"""


def build_system_prompt(
    task_description: str,
    memory_context: str,
    user_rules: str,
    registry: ToolRegistry,
    universal_prefix: str = "",
    extra_context: str = "",
) -> str:
    parts: list[str] = []
    if universal_prefix:
        parts.append(universal_prefix.strip())

    instructions = _TOOL_LOOP_INSTRUCTIONS_TEMPLATE.format(
        tool_catalogue=registry.schema_prompt()
    )
    parts.append(instructions)

    if user_rules and user_rules.strip() not in ("No project-specific rules defined.", ""):
        parts.append(f"PROJECT RULES:\n{user_rules.strip()}")

    if memory_context and memory_context.strip():
        parts.append(f"MEMORY CONTEXT:\n{memory_context.strip()}")

    if extra_context and extra_context.strip():
        parts.append(f"ADDITIONAL CONTEXT:\n{extra_context.strip()}")

    parts.append(f"TASK:\n{task_description.strip()}")

    return "\n\n---\n\n".join(parts)


# ── Loop engine ───────────────────────────────────────────────────────────────

class ToolLoopEngine:
    """
    Drives the agentic loop for one task.

    Args:
        registry: ToolRegistry with workspace configured
        chat_fn: callable(messages, model, options) → str  (wraps ollama/openai)
        model: model name to use
        max_turns: hard cap on tool calls
    """

    def __init__(
        self,
        registry: ToolRegistry,
        chat_fn: Any,         # (messages: list[dict], model: str, options: dict) -> str
        model: str,
        max_turns: int = DEFAULT_MAX_TURNS,
        temperature: float = 0.05,
    ) -> None:
        self.registry = registry
        self.chat_fn = chat_fn
        self.model = model
        self.max_turns = max_turns
        self.temperature = temperature

    def run(
        self,
        system_prompt: str,
        task_description: str,
        insight_sink: Any = None,
    ) -> LoopResult:
        """Execute the agentic loop. Returns a LoopResult summarising all actions."""
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_description},
        ]

        result = LoopResult(status="error", turns=0)
        turn = 0

        while turn < self.max_turns:
            turn += 1

            # Budget warning — nudge model to wrap up
            if turn == TOOL_CALL_BUDGET_WARN:
                messages.append({
                    "role": "user",
                    "content": (
                        f"[SYSTEM] You have {self.max_turns - turn} tool calls remaining. "
                        "Prioritise completing and testing the task, then call done."
                    ),
                })

            # ── LLM call ──────────────────────────────────────────────────
            try:
                raw_response = self.chat_fn(
                    messages=messages,
                    model=self.model,
                    options={"temperature": self.temperature},
                )
            except Exception as exc:
                result.error = f"LLM call failed at turn {turn}: {exc}"
                result.status = "error"
                result.turns = turn
                _emit_insight(insight_sink, "risk", "high",
                              f"Tool loop LLM failure: {exc}", True)
                return result

            messages.append({"role": "assistant", "content": raw_response})

            # ── Parse tool call ───────────────────────────────────────────
            tool_call, parse_err = _parse_tool_call(raw_response)
            if parse_err:
                # Give the model one chance to recover by telling it what went wrong
                messages.append({
                    "role": "user",
                    "content": (
                        f"[SYSTEM] Could not parse your tool call: {parse_err}\n"
                        "Emit EXACTLY: {\"tool\": \"<name>\", \"args\": {...}} with no prose."
                    ),
                })
                _emit_insight(insight_sink, "uncertainty", "medium",
                              f"Tool call parse error turn {turn}: {parse_err}", False)
                continue

            tool_name = tool_call.get("tool", "")

            # ── Done signal ───────────────────────────────────────────────
            if tool_name == "done":
                result.status = "done"
                result.turns = turn
                result.final_summary = (
                    tool_call.get("args", {}).get("summary", "")
                    or f"Completed in {turn} turns."
                )
                return result

            # ── Execute tool ──────────────────────────────────────────────
            tool_result: ToolResult = self.registry.dispatch(tool_call)

            # Track mutations
            if tool_name in ("write_file",) and tool_result.success:
                path = str(tool_call.get("args", {}).get("path", ""))
                if path and path not in result.files_written:
                    result.files_written.append(path)
            elif tool_name in ("edit_file",) and tool_result.success:
                path = str(tool_call.get("args", {}).get("path", ""))
                if path and path not in result.files_edited:
                    result.files_edited.append(path)
            elif tool_name == "run_command" and tool_result.success:
                cmd = str(tool_call.get("args", {}).get("command", ""))
                result.commands_run.append(cmd)

            # Track history
            result.history.append(TurnRecord(
                turn=turn,
                tool=tool_name,
                args=tool_call.get("args", {}),
                success=tool_result.success,
                output_preview=tool_result.output[:300],
            ))

            # Feed result back to model
            result_msg = tool_result.to_message()
            messages.append({"role": "user", "content": result_msg})

            logger.debug(
                "Tool loop turn %d/%d: %s → %s",
                turn, self.max_turns, tool_name,
                "ok" if tool_result.success else f"ERROR: {tool_result.error[:80]}",
            )

        # Exhausted turns without done
        result.status = "max_turns"
        result.turns = turn
        result.error = f"Reached max_turns={self.max_turns} without completing."
        _emit_insight(insight_sink, "risk", "high",
                      f"Tool loop hit max_turns ({self.max_turns})", True)
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_tool_call(raw: str) -> tuple[dict, str]:
    """
    Extract the first JSON object from the model response.
    Returns (tool_call_dict, "") on success or ({}, error_message) on failure.
    """
    cleaned = strip_llm_noise(raw)
    try:
        val = parse_json_value(cleaned)
        if not isinstance(val, dict):
            return {}, f"Expected JSON object, got {type(val).__name__}"
        if "tool" not in val:
            return {}, 'JSON object missing "tool" key'
        return val, ""
    except (ValueError, json.JSONDecodeError) as exc:
        return {}, str(exc)


def _emit_insight(sink: Any, insight_type: str, severity: str, content: str, requires_action: bool) -> None:
    if sink is None:
        return
    try:
        from sage.protocol.schemas import AgentInsight
        sink.ingest(AgentInsight(
            agent="tool_loop",
            task_id="",
            insight_type=insight_type,
            content=content[:2000],
            severity=severity,
            requires_orchestrator_action=requires_action,
        ))
    except Exception:
        pass


# ── Chat function adapters ────────────────────────────────────────────────────

def make_ollama_chat_fn(timeout_s: float | None = None):
    """Returns a chat_fn compatible with ToolLoopEngine using ollama."""
    from sage.llm.ollama_safe import chat_with_timeout

    def chat_fn(messages: list[dict], model: str, options: dict) -> str:
        response = chat_with_timeout(
            model=model,
            messages=messages,
            options=options,
            timeout_s=timeout_s,
        )
        # chat_with_timeout returns {"message": {"content": "..."}}
        if isinstance(response, dict):
            msg = response.get("message") or {}
            if isinstance(msg, dict):
                return str(msg.get("content") or "")
            return str(msg)
        return str(response)

    return chat_fn
