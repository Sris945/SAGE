"""
Safe Ollama wrapper with optional timeouts and a TTY loading indicator.

Local models can take minutes on first load or under load; strict short timeouts
were causing spurious failures. Default is **no** per-call cap unless
``SAGE_OLLAMA_CHAT_TIMEOUT_S`` is set to a positive number.

If the HTTP call truly hangs (dead server), rely on OS/network or set a finite
timeout via env — do not use tiny hardcoded seconds in agents.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
import threading
from typing import Any, Optional

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None


class OllamaTimeout(RuntimeError):
    pass


def default_chat_timeout_s() -> float | None:
    """
    Global default for ``ollama.chat`` wait time (passed to ``Future.result``).

    Env:
      SAGE_OLLAMA_CHAT_TIMEOUT_S — positive seconds; **empty or 0 or negative = unlimited**
    """
    raw = (os.environ.get("SAGE_OLLAMA_CHAT_TIMEOUT_S") or "").strip()
    if raw == "":
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


def default_embed_timeout_s() -> float | None:
    """Same pattern for embeddings (often faster; still allow unlimited)."""
    raw = (os.environ.get("SAGE_OLLAMA_EMBED_TIMEOUT_S") or "").strip()
    if raw == "":
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


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


def effective_ollama_timeout(timeout_s: float | None, *, kind: str = "chat") -> float | None:
    """
    When SAGE_BENCH=1 (set by `sage bench` / run_benchmarks), scale short per-call
    timeouts so large local models can return before the client gives up.

    ``timeout_s is None`` means unlimited (no Future timeout).

    Env:
      SAGE_BENCH=1 — enable scaling
      SAGE_BENCH_TIMEOUT_MULT — multiplier (default 3.0)
      SAGE_BENCH_CHAT_MAX_S — cap for chat/embeddings chat (default 180)
      SAGE_BENCH_EMBED_MAX_S — cap for embeddings (default 15)
    """
    if timeout_s is None:
        return None
    if not _bench_mode_active():
        return float(timeout_s)
    mult = float(os.environ.get("SAGE_BENCH_TIMEOUT_MULT", "3.0"))
    scaled = float(timeout_s) * mult
    if kind == "embeddings":
        cap = float(os.environ.get("SAGE_BENCH_EMBED_MAX_S", "15.0"))
    else:
        cap = float(os.environ.get("SAGE_BENCH_CHAT_MAX_S", "180.0"))
    return min(cap, scaled)


def _spinner_should_run() -> bool:
    if os.environ.get("SAGE_DISABLE_OLLAMA_SPINNER", "").strip():
        return False
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def _wait_future_with_sage_spinner(
    fut: concurrent.futures.Future[Any],
    timeout_s: float | None,
    *,
    label: str = "ollama",
) -> Any:
    """
    Block on ``fut`` with optional timeout; show a small teal SAGE-style spinner on stderr.
    """
    if not _spinner_should_run():
        return fut.result(timeout=timeout_s)

    stop = threading.Event()
    frames = ("◐", "◓", "◑", "◒")

    def _spin() -> None:
        i = 0
        while not stop.wait(0.11):
            sys.stderr.write(
                f"\r\x1b[36m[SAGE]\x1b[0m \x1b[2m{label}\x1b[0m "
                f"\x1b[33m{frames[i % len(frames)]}\x1b[0m loading…"
                + " " * 4
            )
            sys.stderr.flush()
            i += 1

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        return fut.result(timeout=timeout_s)
    finally:
        stop.set()
        t.join(timeout=0.3)
        sys.stderr.write("\r" + " " * 88 + "\r")
        sys.stderr.flush()


def chat_with_timeout(
    *,
    model: str,
    messages: list[dict[str, Any]],
    options: Optional[dict[str, Any]] = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    if ollama is None:
        raise RuntimeError("ollama module not installed")

    if timeout_s is None:
        timeout_s = default_chat_timeout_s()
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
            raw = _wait_future_with_sage_spinner(fut, t, label="ollama.chat")
            resp = _normalize_chat_response(raw)
            try:
                usage = resp.get("usage") if isinstance(resp, dict) else None
                if usage and isinstance(usage, dict):
                    from sage.observability.structured_logger import log_event

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
            ts = f"{t}s" if t is not None else "?"
            raise OllamaTimeout(f"ollama.chat timeout after {ts}") from e
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def embeddings_with_timeout(
    *,
    model: str,
    prompt: str,
    timeout_s: float | None = None,
) -> list[float]:
    if ollama is None:
        raise RuntimeError("ollama module not installed")

    if timeout_s is None:
        timeout_s = default_embed_timeout_s()
    t = effective_ollama_timeout(timeout_s, kind="embeddings")

    def _call() -> list[float]:
        result = ollama.embeddings(model=model, prompt=prompt)
        return result["embedding"]

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(_call)
        try:
            return _wait_future_with_sage_spinner(fut, t, label="ollama.embeddings")
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
            ts = f"{t}s" if t is not None else "?"
            raise OllamaTimeout(f"ollama.embeddings timeout after {ts}") from e
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
