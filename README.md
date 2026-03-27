# SAGE

**Self-improving Autonomous Generation Engine** — turn a plain-English goal into a plan, code, tests, and verification.

SAGE is a **Python CLI** built around a **LangGraph-style orchestrator**: specialized agents (planner, coder, reviewer, test engineer, …), a **model router** (`models.yaml`), multi-layer **memory**, and optional **Ollama** for local LLMs. You can drive it from a **TTY shell** (slash commands, chat threads, intent routing) or headless with `sage run`.

---

## What you can do

| | |
|--|--|
| **Run the full pipeline** | `sage run "Add JWT auth to the API"` — planner → DAG → code → review → tests → verify → memory. |
| **Skip checkpoints** | `sage run "…" --auto` or `--silent`; `--no-clarify` skips planner Q&A. |
| **Use the interactive shell** | Run `sage` with no args — `/` opens a command menu, `/chat` starts a local LLM thread (saved under `.sage/chat_sessions/`), natural language can route to chat vs build. |
| **Swap models** | Edit `src/sage/config/models.yaml` — per-role primary/fallback (Ollama tags, API models). |
| **Benchmark & RL** | `sage bench`; Phase 5/6: `sage rl …`, `sage sim …` (see **Getting started** below). |

---

## Requirements

- **Python 3.10+**
- **Optional:** [Ollama](https://ollama.com/) for local models (names must match `ollama list` and `models.yaml`)

---

## Install

### Option A — bootstrap script (easiest)

| Platform | Steps |
|----------|--------|
| **Linux / macOS** | `./startup.sh` then `source .venv/bin/activate` |
| **Windows** | `.\startup.ps1` then `.\.venv\Scripts\Activate.ps1` |

Creates `.venv`, installs the package in editable mode with dev deps.

### Option B — manual

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip wheel && pip install -e ".[dev]"
```

### Pull models (Ollama)

After `ollama` is installed, pull tags that match your `models.yaml` (example):

```bash
ollama pull qwen2.5-coder:1.5b
ollama pull nomic-embed-text
```

Tiers, VRAM, and troubleshooting **404 model not found** → **[`docs/models.md`](docs/models.md)**.

---

## First steps

```bash
sage doctor          # environment, optional Ollama checks
sage                 # interactive shell — try /commands
sage run "Scaffold a minimal FastAPI app with /health" --auto
sage status          # last session snapshot (memory/system_state.json)
```

**In-shell doc links:** after `/commands`, SAGE prints links to this repo’s docs. Set:

`export SAGE_REPO_URL=https://github.com/your-org/your-fork`

so those URLs point at your canonical GitHub tree.

---

## Interactive shell (high level)

- Built on **prompt_toolkit**: type **`/`** to open completions, filter commands, **Enter** to submit the line (not “run on every keypress” — the buffer updates live, dispatch is line-based).
- **`/chat`** / **`start chat`** — multi-turn chat with a small local model; transcript can be **prepended** to the next `sage run` / NL build (see **`SAGE_CHAT_ATTACH_TO_RUN`** in **[`docs/CLI.md`](docs/CLI.md)**).
- **`agent`** / **`agent clear`** — reminders for build mode vs clearing attached chat context.

Full list of env vars (`SAGE_SHELL_*`, `SAGE_CHAT_*`, intent routing) → **[`docs/CLI.md`](docs/CLI.md)**.

---

## Architecture (at a glance)

- **Orchestrator:** `src/sage/orchestrator/workflow.py` — main state machine.
- **Routing:** `src/sage/orchestrator/model_router.py` — chooses model per agent role.
- **Agents:** `src/sage/agents/` — planner, coder, reviewer, debugger, architect, test engineer, …
- **Execution:** `src/sage/execution/` — tools, verification.
- **Memory & RAG:** `src/sage/memory/` — layers, docs retrieval where enabled.
- **CLI:** `src/sage/cli/` — `sage` entrypoint, shell, chat, branding.

Diagrams and deeper notes → **[`docs/architecture.md`](docs/architecture.md)** and **[`docs/architecture_diagram.md`](docs/architecture_diagram.md)**. Event bus → **[`docs/event_bus.md`](docs/event_bus.md)**.

---

## Documentation map

Use this repo’s **`docs/`** folder for depth; you don’t need a separate “docs README only” story — the files below are the real guides:

| Guide | What it covers |
|-------|----------------|
| **[`docs/INSTALL.md`](docs/INSTALL.md)** | Bootstrap scripts, Windows vs Linux, pip details |
| **[`docs/CLI.md`](docs/CLI.md)** | Slash REPL, prompt_toolkit, `SAGE_SHELL_*`, chat attach |
| **[`docs/models.md`](docs/models.md)** | `models.yaml`, Ollama tags, VRAM tiers, bench timeouts |
| **[`docs/getting_started.md`](docs/getting_started.md)** | `sage bench`, `sage rl`, `sage sim` command lists |
| **[`docs/architecture.md`](docs/architecture.md)** | Design entrypoints and pointers |
| **[`docs/TRUST_AND_SCALE.md`](docs/TRUST_AND_SCALE.md)** | Policy, trust, scaling notes |
| **[`docs/LIVE_TESTING.md`](docs/LIVE_TESTING.md)** | Real Ollama verification, `scripts/live_verify.sh` |
| **[`CONTRIBUTING.md`](CONTRIBUTING.md)** | Tests, CI, how to contribute |

**[`docs/README.md`](docs/README.md)** is a short index of the same paths for browsing on GitHub.

---

## Repository layout

Abbreviated; full tree → **[`project_structure.md`](project_structure.md)**.

```
src/sage/          # Application package (CLI, orchestrator, agents, memory, rl, sim, …)
docs/              # All guides (architecture, models, CLI, install, …)
tests/             # pytest
scripts/           # Local verification helpers
startup.sh / .ps1  # Optional venv + editable install
```

---

## Contributing

See **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — unit tests, benchmarks, live Ollama bar.

---
