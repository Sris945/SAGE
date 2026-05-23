## Architecture

Canonical design notes live in this repo under **`docs/`**:

- **[`architecture_diagram.md`](architecture_diagram.md)** — Visual overview
- **[`event_bus.md`](event_bus.md)** — Event processing
- **[`models.md`](models.md)** — Model routing and Ollama

### Implementation entrypoints

| Area | Location |
|------|----------|
| Orchestrator workflow | `src/sage/orchestrator/workflow.py` |
| Model routing | `src/sage/orchestrator/model_router.py` |
| Execution + verification | `src/sage/execution/executor.py`, `src/sage/execution/verifier.py` |
| **Tool-use loop (ReAct)** | `src/sage/execution/tool_loop.py` |
| **Coder agent** | `src/sage/agents/coder.py` |
| **Context compressor** | `src/sage/memory/context_compressor.py` |
| Benchmarks | `src/sage/benchmarks/runner.py`, `src/sage/benchmarks/tasks/*.yaml` |

For offline RL and simulator flows, see **`docs/getting_started.md`** and **`docs/research_notes.md`**.

---

### Tool-use loop (`ToolLoopEngine`)

The coder agent runs a **ReAct loop** (max 24 turns by default):

1. LLM emits a JSON tool call → engine dispatches → result appended to messages.
2. Loop ends when the model emits a `done` call or the turn budget is exhausted.

Key subsystems inside `tool_loop.py`:

| Subsystem | Detail |
|-----------|--------|
| **Streaming** | `make_ollama_chat_fn(stream=True)` — tokens print to stdout as they arrive via a dim `⟳` prefix. |
| **Read-file cache** | `_read_cache: dict[str, str]` — repeated reads of the same file skip the disk; invalidated automatically on any write, edit, move, or delete. |
| **Smart truncation** | Long output from `run_command`, `grep_code`, `git_log`, `git_diff`, `git_status` is truncated to `head=60 / tail=60` lines. `read_file` is never truncated so `edit_file` always sees exact content. |
| **Plan mode** | When `plan_mode=True`, the engine asks the model for a step-by-step plan before the first tool call and pauses for human confirmation (`y` / `n`). |
| **Checkpoint / resume** | After every tool turn the engine gzips the full message list + loop metadata to `.sage/loop_checkpoint.bin`. `resume=True` loads it at startup; the file is deleted on successful `done`. |
| **Token tracking** | `get_last_token_usage()` is called after each LLM response; totals are accumulated in `LoopResult.tokens_used` and surfaced in the run report Outcome panel. |
| **Context budget management** | At 80 % of the model's context window, the engine inserts a warning. At 90 %, it either hard-prunes old turns or calls the LLM to auto-compact (`SAGE_AUTO_COMPACT=1`). Context window size is read from `models.yaml` then a built-in fallback table. |
| **Incremental index updates** | After every `write_file`, `edit_file`, or `move_file` tool call, `_trigger_index_update()` fires a background Qdrant re-index for the affected paths. |

### Context compressor (`context_compressor.py`)

Before injecting codebase context into a task prompt, the compressor selects only the most relevant code chunks using a three-tier strategy (degrading gracefully):

1. **Qdrant semantic search** — if a code index has been built (`sage index`).
2. **BM25 / TF-IDF keyword matching** — no embeddings required; fast.
3. **Grep exact-token match** — always available as a last resort.

Key parameters: `MAX_CONTEXT_CHARS` (~4 K tokens), `MAX_CHUNKS`, `CHUNK_SIZE`.

### Hardware-aware model selection

At install time (or `sage setup`), SAGE runs a hardware scan and allocation wizard:

1. **Scan** (`scan_hardware()`) — reads RAM from `/proc/meminfo` (Linux) or `sysctl` (macOS), VRAM from `nvidia-smi` / `rocm-smi`, CPU cores, and free disk under the Ollama model dir. Falls back to `fastfetch` / `neofetch` if direct reads fail.
2. **Wizard** (`run_allocation_wizard()`) — interactive Rich UI; headless mode picks the middle option.
3. **Tier selection** (`suggest_ollama_stack()`) — maps `(ram_budget_gib, quality_preference)` to a tier; writes model names per role into `models.yaml`.
4. **Pull** (`pull_ollama_tags()`) — downloads only missing models; displays per-model progress.

Results persisted to **`.sage/hardware.json`**.

### Cross-task working memory

`workflow.py` accumulates a `working_memory: dict[str, list[dict]]` key in workflow state, recording which task wrote or edited each file. Before each coder task starts, the relevant portion of this log is appended to the coder's system prompt so agents don't duplicate or conflict with earlier work.

### Grep-based file pre-loading (`CoderAgent._preload_files`)

Before the loop starts, the coder agent scans the task description for file paths and identifiers (CamelCase / snake_case), dispatches `read_file` and `grep_code` calls, and injects a **PRE-LOADED FILES** block into the system prompt. This gives the model relevant context without waiting for it to ask.
