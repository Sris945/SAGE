# Event bus (strict processing)

The orchestrator uses `sage.orchestrator.event_bus.EventBus` for decoupled side effects (e.g. task completion → optional memory checkpoint).

## Guarantees

- **FIFO:** Events are processed in **enqueue order**.
- **Single consumer:** One worker thread dequeues and runs handlers **sequentially** (no concurrent handler execution for the bus).
- **Re-entrancy:** If a handler calls `emit_sync()` again (e.g. `TASK_COMPLETED` → `MEMORY_CHECKPOINT`), the inner emit runs **inline** on the worker thread so the queue cannot deadlock. Handler dispatch uses an `RLock` so nested handler runs do not self-deadlock.

## Spec lifecycle hooks vs code

The architecture spec describes five **conceptual** hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd). In the current codebase, equivalent behavior is split across LangGraph nodes (`load_memory`, `prompt_middleware`, `tool_executor`, `save_memory`, etc.) and **structured logging**, not only `EventBus` events. The bus today is intentionally narrow; extend it when you need cross-cutting subscribers without tangling the graph.

## When to use

- `emit_sync(Event(...))` from synchronous LangGraph nodes.
- `await emit(Event(...))` from async code if you add it later.

Do not assume handlers run in the same thread as the caller (except for the re-entrant path above).
