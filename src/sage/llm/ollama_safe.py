"""
Safe Ollama wrapper with timeouts.

The project is designed to run even when the local Ollama server is absent.
If the HTTP call hangs, we raise promptly so the orchestrator can circuit-break.
"""

from __future__ import annotations

import os
from typing import Any, Optional
import concurrent.futures

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None


class OllamaTimeout(RuntimeError):
    pass


def _normalize_chat_response(resp: Any) -> dict[str, Any]:
    """
    Newer ``ollama`` Python clients may return a typed response object instead of
    a dict. Agents expect ``response['message']['content']``.
    """
    if isinstance(resp, dict):
        return resp
    try:
        msg = getattr(resp, "message", None)
        content = ""
        role = "assistant"
        if msg is not None:
            content = getattr(msg, "content", "") or ""
            role = getattr(msg, "role", None) or "assistant"
        out: dict[str, Any] = {"message": {"role": role, "content": content}}
        usage = getattr(resp, "usage", None)
        if usage is not None:
            if isinstance(usage, dict):
                out["usage"] = usage
            else:
                out["usage"] = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
        return out
    except Exception:
        return {"message": {"role": "assistant", "content": str(resp)}}


def _bench_mode_active() -> bool:
    return os.environ.get("SAGE_BENCH", "").strip().lower() in ("1", "true", "yes")


def effective_ollama_timeout(timeout_s: float, *, kind: str = "chat") -> float:
    """
    When SAGE_BENCH=1 (set by `sage bench` / run_benchmarks), scale short per-call
    timeouts so large local models (e.g. Codestral 22B) can return before the
    client gives up. Does not affect normal `sage run` unless SAGE_BENCH is set.

    Env:
      SAGE_BENCH=1 — enable scaling
      SAGE_BENCH_TIMEOUT_MULT — multiplier (default 3.0)
      SAGE_BENCH_CHAT_MAX_S — cap for chat/embeddings chat (default 180)
      SAGE_BENCH_EMBED_MAX_S — cap for embeddings (default 15)
    """
    if not _bench_mode_active():
        return float(timeout_s)
    mult = float(os.environ.get("SAGE_BENCH_TIMEOUT_MULT", "3.0"))
    scaled = float(timeout_s) * mult
    if kind == "embeddings":
        cap = float(os.environ.get("SAGE_BENCH_EMBED_MAX_S", "15.0"))
    else:
        cap = float(os.environ.get("SAGE_BENCH_CHAT_MAX_S", "180.0"))
    return min(cap, scaled)


def chat_with_timeout(
    *,
    model: str,
    messages: list[dict[str, Any]],
    options: Optional[dict[str, Any]] = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    if ollama is None:
        raise RuntimeError("ollama module not installed")

    t = effective_ollama_timeout(timeout_s, kind="chat")

    from sage.llm.token_budget import clamp_messages_chars, max_prompt_chars_total

    cap = max_prompt_chars_total()
    original_total = sum(len(str(m.get("content") or "")) for m in messages)
    if cap > 0:
        messages = clamp_messages_chars(messages, cap)
        new_total = sum(len(str(m.get("content") or "")) for m in messages)
        if new_total < original_total:
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "CONTEXT_CLAMPED",
                    payload={
                        "model": model,
                        "original_chars": original_total,
                        "after_chars": new_total,
                        "cap": cap,
                    },
                )
            except Exception:
                pass

    def _call() -> Any:
        return ollama.chat(model=model, messages=messages, options=options or {})

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(_call)
        try:
            raw = fut.result(timeout=t)
            resp = _normalize_chat_response(raw)
            # Best-effort token usage logging if the Ollama server provides it.
            try:
                usage = resp.get("usage") if isinstance(resp, dict) else None
                if usage and isinstance(usage, dict):
                    from sage.observability.structured_logger import log_event

                    # Keep payload bounded: only common token fields.
                    payload = {
                        "operation": "chat",
                        "model": model,
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                    }
                    if any(v is not None for v in payload.values()):
                        log_event("TOKEN_USAGE", payload=payload)
            except Exception:
                pass
            return resp
        except concurrent.futures.TimeoutError as e:
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "OLLAMA_TIMEOUT",
                    payload={
                        "operation": "chat",
                        "model": model,
                        "timeout_s": t,
                        "bench": _bench_mode_active(),
                    },
                )
            except Exception:
                pass
            raise OllamaTimeout(f"ollama.chat timeout after {t}s") from e
    finally:
        # Do not wait: the underlying Ollama request may be stuck, and we
        # must not block orchestration cleanup on that thread.
        ex.shutdown(wait=False, cancel_futures=True)


def embeddings_with_timeout(
    *,
    model: str,
    prompt: str,
    timeout_s: float = 20.0,
) -> list[float]:
    if ollama is None:
        raise RuntimeError("ollama module not installed")

    t = effective_ollama_timeout(timeout_s, kind="embeddings")

    def _call() -> list[float]:
        result = ollama.embeddings(model=model, prompt=prompt)
        return result["embedding"]

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(_call)
        try:
            return fut.result(timeout=t)
        except concurrent.futures.TimeoutError as e:
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "OLLAMA_TIMEOUT",
                    payload={
                        "operation": "embeddings",
                        "model": model,
                        "timeout_s": t,
                        "bench": _bench_mode_active(),
                    },
                )
            except Exception:
                pass
            raise OllamaTimeout(f"ollama.embeddings timeout after {t}s") from e
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
