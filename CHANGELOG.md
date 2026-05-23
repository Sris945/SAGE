# Changelog

All notable changes to this project should be documented in this file.

## Unreleased

### Tool-use loop overhaul
- **Streaming LLM output** — coder tokens print to stdout in real time via `stream=True`; no more blank wait.
- **Read-file cache** — repeated `read_file` calls within a loop turn are served from memory; cache is invalidated on any write, edit, move, or delete.
- **Smart output truncation** — `run_command`, `grep_code`, `git_*` outputs capped at 60 head + 60 tail lines; `read_file` never truncated so edits always see exact content.
- **Plan mode (`--plan`)** — model proposes a step-by-step plan before any tool calls; human confirms `y` / `n`; auto-proceeds in non-TTY.
- **Checkpoint & resume (`--resume`)** — loop state (messages + file lists + token count) gzipped to `.sage/loop_checkpoint.bin` after every turn and on Ctrl-C; `--resume` reloads it.
- **Token tracking** — tokens accumulated from each LLM call into `LoopResult.tokens_used`, propagated through `execute_agent` into workflow state, displayed in the end-of-run Outcome panel as `~N.Nk`.
- **Grep-based file pre-loading** — `CoderAgent._preload_files` extracts paths and identifiers from the task description and injects a PRE-LOADED FILES block before the loop starts.

### `sage run` enhancements
- **`@file` injection** — `@path/to/file` tokens in the prompt are replaced with file content (up to 8 000 chars) before the run starts.
- **`--plan` flag** — enables plan-mode per-task.
- **`--resume` flag** — reloads `.sage/loop_checkpoint.bin`; no-ops if no checkpoint exists.

### CLI additions
- **`sage history`** — Rich table of past task runs from `memory/tasks.db` with `--days`, `--agent`, `--status`, `--limit` filters.
- **`/compact`** shell command — compresses conversation history in-place; prints `Context compressed: N → M messages`.
- **`/history`** shell command — shows last 10 turns of the current session.

### Memory / context
- **Context compressor** (`src/sage/memory/context_compressor.py`) — three-tier codebase context selection: Qdrant semantic search → BM25/TF-IDF → grep fallback.

### Tests
- 428 tests passing (113 tool-loop + registry unit tests; 26 context compressor unit tests; remainder integration).

---

- CLI / docs:
  - `docs/CLI.md`, `docs/INSTALL.md`, `docs/README.md`; `startup.sh` / `startup.ps1` bootstrap.
  - `/commands` footer prints repo + doc deep links (`SAGE_REPO_URL`, optional `git` origin).
  - Removed draft **`plan final/`** specs from the tree; README and `docs/architecture.md` now point at in-repo documentation only.
- Phase 5/6 closure work:
  - Session-scoped RL export with provenance labels.
  - Offline RL artifact pipeline (BC + conservative policy + offline eval).
  - Simulator maturity: 1000+ tasks, docker runner, PPO smoke.
  - Benchmark artifacts (`sage bench --out`) and YAML task suite parity.
  - Verification matrix + local verification script.
- Project readiness:
  - CI workflow and docker sim smoke workflow.
  - Release checklist and final status reconciliation docs.
