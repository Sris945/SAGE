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
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sage.agents.llm_parse import parse_json_value, strip_llm_noise
from sage.tools.tool_registry import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DEFAULT_MAX_TURNS = 24          # generous — most tasks finish in 6-12 turns
TOOL_CALL_BUDGET_WARN = 18      # warn model when budget is running low
_MAX_TOOL_OUTPUT_CHARS = 6_000  # above this, smart-truncate to keep head+tail

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
    status: str            # "done" | "max_turns" | "error" | "interrupted"
    turns: int
    files_written: list[str] = field(default_factory=list)
    files_edited: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    history: list[TurnRecord] = field(default_factory=list)
    final_summary: str = ""
    error: str = ""
    tokens_used: int = 0   # accumulated prompt+completion tokens across all turns

    @property
    def success(self) -> bool:
        return self.status == "done"

    @property
    def interrupted(self) -> bool:
        return self.status == "interrupted"


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
    agent_role: str = "coder",
) -> str:
    parts: list[str] = []
    if universal_prefix:
        parts.append(universal_prefix.strip())

    instructions = _TOOL_LOOP_INSTRUCTIONS_TEMPLATE.format(
        tool_catalogue=registry.schema_prompt()
    )
    parts.append(instructions)

    # Always try to load rules fresh from workspace (guaranteed injection).
    # The caller-supplied user_rules is merged in but workspace rules take precedence.
    live_rules = _load_live_rules(agent_role)
    merged_rules = "\n\n".join(
        r for r in [live_rules, user_rules] if r and r.strip()
        and r.strip() not in ("No project-specific rules defined.",)
    ).strip()
    if merged_rules:
        parts.append(f"PROJECT RULES:\n{merged_rules}")

    if memory_context and memory_context.strip():
        parts.append(f"MEMORY CONTEXT:\n{memory_context.strip()}")

    if extra_context and extra_context.strip():
        parts.append(f"ADDITIONAL CONTEXT:\n{extra_context.strip()}")

    parts.append(f"TASK:\n{task_description.strip()}")

    return "\n\n---\n\n".join(parts)


def _load_live_rules(agent_role: str) -> str:
    """Load rules from workspace root at call time (guaranteed fresh)."""
    try:
        from sage.prompt_engine.rules_manager import load_merged_rules
        return load_merged_rules(agent_role=agent_role, base_dir=_find_workspace_root())
    except Exception:
        return ""


def _find_workspace_root() -> "Path":
    """Find the nearest .sage/ ancestor, or fall back to cwd."""
    from pathlib import Path
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".sage").is_dir():
            return parent
    return cwd


# ── Loop engine ───────────────────────────────────────────────────────────────

_PLAN_REQUEST = (
    "Before executing any tools, list your step-by-step plan (max 10 numbered steps). "
    "Include which files you'll read, what you'll change, and how you'll verify success. "
    "Be concise — one line per step. Do NOT start executing yet."
)


class ToolLoopEngine:
    """
    Drives the agentic loop for one task.

    Args:
        registry: ToolRegistry with workspace configured
        chat_fn: callable(messages, model, options) → str  (wraps ollama/openai)
        model: model name to use
        max_turns: hard cap on tool calls
        plan_mode: show plan and ask for confirmation before executing
    """

    def __init__(
        self,
        registry: ToolRegistry,
        chat_fn: Any,         # (messages: list[dict], model: str, options: dict) -> str
        model: str,
        max_turns: int = DEFAULT_MAX_TURNS,
        temperature: float = 0.05,
        plan_mode: bool = False,
        checkpoint_path: "Path | None" = None,
        resume: bool = False,
    ) -> None:
        self.registry = registry
        self.chat_fn = chat_fn
        self.model = model
        self.max_turns = max_turns
        self.temperature = temperature
        self.plan_mode = plan_mode
        self.checkpoint_path = checkpoint_path  # always save here after each turn
        self.resume = resume                    # load checkpoint at start only if True
        self._read_cache: dict[str, str] = {}

    def _confirm_plan(self, system_prompt: str, task_description: str) -> bool:
        """Ask model to plan, display plan, return True if user confirms (or non-TTY)."""
        plan_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{task_description}\n\n{_PLAN_REQUEST}"},
        ]
        try:
            plan_raw = self.chat_fn(
                messages=plan_messages,
                model=self.model,
                options={"temperature": 0.1},
            )
        except Exception:
            return True  # on failure, just proceed

        # strip_llm_noise already removes <think> blocks and markdown fences;
        # additionally remove any JSON tool-call the model may have accidentally emitted
        plan_text = re.sub(r'\{[^{}]{0,500}?"tool"[^{}]{0,500}?\}', "", strip_llm_noise(plan_raw)).strip()

        sep = "─" * 58
        print(f"\n{sep}")
        print("  PLAN")
        print(sep)
        print(plan_text or "(model returned no plan text)")
        print(sep)

        if not sys.stdin.isatty():
            print("  [non-interactive] proceeding automatically.")
            return True

        try:
            answer = input("  Proceed? [Y/n] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        return answer in ("", "y", "yes")

    def run(
        self,
        system_prompt: str,
        task_description: str,
        insight_sink: Any = None,
    ) -> LoopResult:
        """Execute the agentic loop. Returns a LoopResult summarising all actions."""
        if self.plan_mode:
            if not self._confirm_plan(system_prompt, task_description):
                r = LoopResult(status="error", turns=0)
                r.error = "Cancelled by user at plan review."
                return r

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_description},
        ]

        result = LoopResult(status="error", turns=0)
        turn = 0

        # Load checkpoint only when explicitly resuming
        if self.resume and self.checkpoint_path and self.checkpoint_path.exists():
            try:
                saved = _load_checkpoint(self.checkpoint_path)
                if saved:
                    messages = saved["messages"]
                    result.files_written = saved.get("files_written", [])
                    result.files_edited = saved.get("files_edited", [])
                    result.commands_run = saved.get("commands_run", [])
                    result.tokens_used = saved.get("tokens_used", 0)
                    # Inject resume marker so model knows context is being restored
                    messages.append({
                        "role": "user",
                        "content": (
                            "[RESUMED] The previous run was interrupted. "
                            f"You had completed {saved.get('turns', 0)} turns. "
                            "Review your progress above and continue from where you left off."
                        ),
                    })
                    logger.info("Resumed from checkpoint (%d turns completed)", saved.get("turns", 0))
            except Exception as exc:
                logger.warning("Could not load checkpoint: %s", exc)

        _context_warned = False

        while turn < self.max_turns:
            turn += 1

            # Turn-count budget warning
            if turn == TOOL_CALL_BUDGET_WARN:
                messages.append({
                    "role": "user",
                    "content": (
                        f"[SYSTEM] You have {self.max_turns - turn} tool calls remaining. "
                        "Prioritise completing and testing the task, then call done."
                    ),
                })

            # Context size warning — fires once when messages exceed ~80K chars (~20K tokens)
            if not _context_warned:
                ctx_chars = sum(len(str(m.get("content", ""))) for m in messages)
                if ctx_chars > 80_000:
                    _context_warned = True
                    messages.append({
                        "role": "user",
                        "content": (
                            "[SYSTEM] Context is growing large. Avoid re-reading files you've already "
                            "read. Summarise completed work mentally and call done as soon as possible."
                        ),
                    })

            # ── LLM call ──────────────────────────────────────────────────
            try:
                raw_response = self.chat_fn(
                    messages=messages,
                    model=self.model,
                    options={"temperature": self.temperature},
                )
            except KeyboardInterrupt:
                result.status = "interrupted"
                result.turns = turn
                result.error = "Interrupted by user (Ctrl-C)."
                result.final_summary = f"Interrupted at turn {turn} — partial work may remain."
                # Capture any tokens the model returned before the interrupt
                try:
                    usage = get_last_token_usage()
                    if usage:
                        result.tokens_used += usage.get("total_tokens", 0)
                except Exception:
                    pass
                if self.checkpoint_path:
                    _save_checkpoint(self.checkpoint_path, messages, result)
                    print(f"\n[SAGE] Checkpoint saved → {self.checkpoint_path}")
                    print("[SAGE] Resume with: sage run --resume")
                return result
            except Exception as exc:
                result.error = f"LLM call failed at turn {turn}: {exc}"
                result.status = "error"
                result.turns = turn
                _emit_insight(insight_sink, "risk", "high",
                              f"Tool loop LLM failure: {exc}", True)
                return result

            messages.append({"role": "assistant", "content": raw_response})

            # Accumulate token usage (ollama_safe tracks last call's usage)
            try:
                from sage.llm.ollama_safe import get_last_token_usage
                usage = get_last_token_usage()
                result.tokens_used += usage.get("total_tokens", 0)
            except Exception:
                pass

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
                # Clean up checkpoint on successful completion
                if self.checkpoint_path and self.checkpoint_path.exists():
                    try:
                        self.checkpoint_path.unlink()
                    except Exception:
                        pass
                return result

            # ── Execute tool ──────────────────────────────────────────────
            args = tool_call.get("args", {})

            # Cache: serve repeated read_file calls from memory — no disk round-trip
            if tool_name == "read_file":
                cache_key = str(args.get("path", ""))
                if cache_key in self._read_cache:
                    cached_out = self._read_cache[cache_key]
                    tool_result = ToolResult(
                        tool="read_file",
                        success=True,
                        output=f"[cached]\n{cached_out}",
                    )
                    messages.append({"role": "user", "content": tool_result.to_message()})
                    _stream_turn(turn, self.max_turns, tool_name, args, tool_result)
                    result.history.append(TurnRecord(
                        turn=turn, tool=tool_name, args=args,
                        success=True, output_preview=cached_out[:300],
                    ))
                    # Accumulate tokens even for cached reads (prompt still grows)
                    try:
                        usage = get_last_token_usage()
                        if usage:
                            result.tokens_used += usage.get("total_tokens", 0)
                    except Exception:
                        pass
                    continue

            try:
                tool_result = self.registry.dispatch(tool_call)
            except KeyboardInterrupt:
                result.status = "interrupted"
                result.turns = turn
                result.error = "Interrupted by user (Ctrl-C) during tool execution."
                result.final_summary = f"Interrupted at turn {turn} while running {tool_name!r}."
                return result

            # Populate read cache for successful reads
            if tool_name == "read_file" and tool_result.success:
                cache_key = str(args.get("path", ""))
                if cache_key:
                    self._read_cache[cache_key] = tool_result.output

            # Invalidate cache for any tool that mutates files
            if tool_name in ("write_file", "edit_file", "search_replace", "append_file", "delete_file"):
                stale = str(args.get("path", ""))
                self._read_cache.pop(stale, None)
            elif tool_name == "move_file":
                self._read_cache.pop(str(args.get("source", "")), None)
                self._read_cache.pop(str(args.get("destination", "")), None)

            # Smart truncation for verbose command/grep output only.
            # Never truncate read_file — the model needs exact content to edit accurately.
            _TRUNCATE_TOOLS = ("run_command", "run_tests", "grep_code", "git_log", "git_diff", "git_status")
            if tool_name in _TRUNCATE_TOOLS and len(tool_result.output) > _MAX_TOOL_OUTPUT_CHARS:
                tool_result = ToolResult(
                    tool=tool_result.tool,
                    success=tool_result.success,
                    output=_smart_truncate(tool_result.output),
                    error=tool_result.error,
                )

            # Track mutations
            if tool_name == "write_file" and tool_result.success:
                path = str(args.get("path", ""))
                if path and path not in result.files_written:
                    result.files_written.append(path)
            elif tool_name in ("edit_file", "search_replace", "append_file") and tool_result.success:
                path = str(args.get("path", ""))
                if path and path not in result.files_edited:
                    result.files_edited.append(path)
            elif tool_name == "move_file" and tool_result.success:
                src = str(args.get("source", ""))
                dst = str(args.get("destination", ""))
                if src and src not in result.files_edited:
                    result.files_edited.append(src)
                if dst and dst not in result.files_written:
                    result.files_written.append(dst)
            elif tool_name in ("run_command", "run_tests") and tool_result.success:
                cmd = str(args.get("command", "") or args.get("path", "") or "run_tests")
                result.commands_run.append(cmd)

            # Track history
            result.history.append(TurnRecord(
                turn=turn,
                tool=tool_name,
                args=args,
                success=tool_result.success,
                output_preview=tool_result.output[:300],
            ))

            # Feed result back to model
            result_msg = tool_result.to_message()
            messages.append({"role": "user", "content": result_msg})

            _stream_turn(turn, self.max_turns, tool_name, args, tool_result)
            logger.debug(
                "Tool loop turn %d/%d: %s → %s",
                turn, self.max_turns, tool_name,
                "ok" if tool_result.success else f"ERROR: {tool_result.error[:80]}",
            )

            # Persist checkpoint after every turn so crashes are recoverable
            if self.checkpoint_path:
                result.turns = turn
                _save_checkpoint(self.checkpoint_path, messages, result)

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


def _stream_turn(
    turn: int,
    max_turns: int,
    tool_name: str,
    args: dict,
    result: ToolResult,
) -> None:
    """Print a one-line update per tool call so users see real-time progress."""
    import sys
    if not sys.stdout.isatty() and not os.environ.get("SAGE_FORCE_STREAM"):
        return
    _ARG_PRIORITY = ("path", "source", "command", "query", "pattern", "old_string", "message", "url")
    key_arg = ""
    for k in _ARG_PRIORITY:
        if k in args:
            val = str(args[k])
            key_arg = f" {val[:60]}" if val else ""
            break
    status = "ok" if result.success else f"ERROR: {result.error[:50]}"
    print(f"  [{turn:02d}/{max_turns}] {tool_name}{key_arg} → {status}", flush=True)


def _save_checkpoint(path: Path, messages: list[dict], result: "LoopResult") -> None:
    """Persist loop state to disk (gzipped JSON) so interrupted runs can be resumed."""
    import gzip
    payload = {
        "turns": result.turns,
        "files_written": result.files_written,
        "files_edited": result.files_edited,
        "commands_run": result.commands_run,
        "tokens_used": result.tokens_used,
        "messages": messages,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(path) + ".tmp")
        with gzip.open(str(tmp), "wt", encoding="utf-8") as f:
            json.dump(payload, f)
        # Atomic rename — tmp is only promoted once fully written
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Could not save checkpoint: %s", exc)


def _load_checkpoint(path: Path) -> dict | None:
    """Load a checkpoint saved by _save_checkpoint. Returns None on failure."""
    import gzip
    try:
        with gzip.open(str(path), "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    # Try plain JSON fallback
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _smart_truncate(text: str, head: int = 60, tail: int = 60) -> str:
    """Keep first `head` + last `tail` lines with an omission notice in between."""
    lines = text.splitlines()
    total = len(lines)
    if total <= head + tail:
        return text
    omitted = total - head - tail
    kept_head = "\n".join(lines[:head])
    kept_tail = "\n".join(lines[-tail:])
    return f"{kept_head}\n… [{omitted} lines omitted] …\n{kept_tail}"


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

def make_ollama_chat_fn(timeout_s: float | None = None, stream: bool = False):
    """
    Returns a chat_fn compatible with ToolLoopEngine using ollama.

    When stream=True and stdout is a TTY (or SAGE_FORCE_STREAM is set), tokens are
    printed in real-time so the user sees the model "thinking". The full accumulated
    response string is returned for parsing.
    """
    from sage.llm.ollama_safe import chat_with_timeout, stream_chat

    def chat_fn(messages: list[dict], model: str, options: dict) -> str:
        use_stream = stream and (sys.stdout.isatty() or os.environ.get("SAGE_FORCE_STREAM"))
        if use_stream:
            chunks: list[str] = []
            sys.stdout.write("\033[2m  ⟳ \033[0m")
            sys.stdout.flush()
            try:
                for chunk in stream_chat(model=model, messages=messages, options=options):
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                    chunks.append(chunk)
            finally:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return "".join(chunks)

        response = chat_with_timeout(
            model=model,
            messages=messages,
            options=options,
            timeout_s=timeout_s,
        )
        if isinstance(response, dict):
            msg = response.get("message") or {}
            if isinstance(msg, dict):
                return str(msg.get("content") or "")
            return str(msg)
        return str(response)

    return chat_fn
