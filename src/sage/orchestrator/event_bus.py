"""
SAGE Event Bus
-------------
Strict, single-consumer event bus.

Why this exists:
- LangGraph can run nodes concurrently, so we must guarantee that event handlers
  are executed strictly in enqueue order and never concurrently.
- Phase 3 spec calls this out as "Async event bus strict processing".

Implementation:
- A dedicated worker thread dequeues events from a FIFO queue.
- `emit_sync()` blocks until all handlers for that event finish.
- `emit()` is non-blocking for the caller (awaits handler completion only when
  awaited by the caller).
"""

from __future__ import annotations

import asyncio
import threading
from queue import Queue
from typing import Any, Callable

from sage.protocol.schemas import Event


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], Any]]] = {}
        self._queue: Queue[tuple[Event, threading.Event]] = Queue()
        self._worker_thread: threading.Thread | None = None
        self._worker_started = threading.Event()
        # RLock: handlers may call emit_sync() re-entrantly (e.g. TASK_COMPLETED → MEMORY_CHECKPOINT).
        self._dispatch_lock = threading.RLock()

    def subscribe(self, event_type: str, handler: Callable[[Event], Any]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def _ensure_worker_started(self) -> None:
        if self._worker_thread is not None:
            return

        def _worker() -> None:
            # Worker owns the FIFO dequeue + sequential handler dispatch.
            self._worker_started.set()
            while True:
                event, done = self._queue.get()
                try:
                    handlers = list(self._handlers.get(event.type, []))
                    # Extra guard: ensure a handler can't be executed concurrently
                    # even if future refactors call into this worker incorrectly.
                    with self._dispatch_lock:
                        for handler in handlers:
                            try:
                                result = handler(event)
                                # Best-effort: if a handler is async, run it to completion.
                                if asyncio.iscoroutine(result):
                                    asyncio.run(result)
                            except Exception as exc:
                                # Log the failure but continue processing — a broken
                                # handler must not stall the event bus or crash the
                                # orchestration thread.
                                import logging as _logging

                                _logging.getLogger(__name__).error(
                                    "EventBus handler %r failed for event %r: %s",
                                    getattr(handler, "__name__", repr(handler)),
                                    event.type,
                                    exc,
                                    exc_info=True,
                                )
                finally:
                    done.set()

        self._worker_thread = threading.Thread(target=_worker, daemon=True)
        self._worker_thread.start()
        self._worker_started.wait(timeout=2.0)

    async def emit(self, event: Event) -> None:
        """
        Async emit: enqueue event and complete only after handlers finish.
        (The strict processing guarantee is preserved; callers can choose not
        to await this in order to make it fully fire-and-forget.)
        """
        self._ensure_worker_started()
        done = threading.Event()
        self._queue.put((event, done))
        # Wait in a thread so we don't block the caller event loop.
        await asyncio.get_running_loop().run_in_executor(None, done.wait)

    async def process(self) -> None:
        """
        Back-compat: the worker thread already processes events forever.
        This coroutine just waits for the worker to be ready.
        """
        self._ensure_worker_started()
        await asyncio.sleep(0)

    def emit_sync(self, event: Event) -> None:
        """
        Synchronous emit for LangGraph nodes.
        Blocks until all handlers for this event finish.
        """
        self._ensure_worker_started()
        # Re-entrancy guard: handlers may themselves emit more events using
        # emit_sync() (e.g. TASK_COMPLETED -> MEMORY_CHECKPOINT). If we queue
        # and wait while already in the worker thread, we'd deadlock.
        if threading.current_thread() is self._worker_thread:
            handlers = list(self._handlers.get(event.type, []))
            with self._dispatch_lock:
                for handler in handlers:
                    try:
                        result = handler(event)
                        if asyncio.iscoroutine(result):
                            asyncio.run(result)
                    except Exception as exc:
                        import logging as _logging

                        _logging.getLogger(__name__).error(
                            "EventBus handler %r failed for event %r (re-entrant): %s",
                            getattr(handler, "__name__", repr(handler)),
                            event.type,
                            exc,
                            exc_info=True,
                        )
            return

        done = threading.Event()
        self._queue.put((event, done))
        done.wait()
