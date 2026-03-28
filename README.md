<div align="center">

# SAGE

### Self-improving Autonomous Generation Engine

*prompt → production*

**Turn a plain-English goal into a plan, code, tests, and verification.**

<br/>

<img src="images/SAGE" alt="SAGE — autonomous run overview" width="92%" />

<br/>

</div>

SAGE is a **Python CLI** built around a **LangGraph-style orchestrator**: specialized agents (planner, coder, reviewer, test engineer, …), a **model router** (`models.yaml`), multi-layer **memory**, and optional **Ollama** for local LLMs. Drive it from a **TTY shell** (slash commands, chat threads, intent routing) or headless with `sage run`.

---

## Screenshots

| Interactive shell · `/commands` | Model routing & profiles |
|:--:|:--:|
| <img src="images/Commands" alt="Slash commands and shell" width="100%" /> | <img src="images/Model" alt="Model routing" width="100%" /> |
| **Skills & `/skill` discovery** | **`sage memory` — memory layers** |
| <img src="images/Skills" alt="Skills panel" width="100%" /> | <img src="images/Memory" alt="SAGE memory layers listing" width="100%" /> |

Five static assets live in [`images/`](images/) (`Commands`, `Memory`, `Model`, `SAGE`, `Skills`).

---

## What you can do

| | |
|--|--|
| **Run the full pipeline** | `sage run "Add JWT auth to the API"` — planner → DAG → code → review → tests → verify → memory. |
| **Human checkpoints** | Default **`--research`**: review the plan (`a` / `r` / `e` for approve / reject / edit plan file), then continue. **`--auto`** — fewer interactive gates; **`--silent`** — autonomous, skips failed tasks. **`--no-clarify`** skips planner Q&A. |
| **Bootstrap a project folder** | `sage init` — creates `.sage/`, `memory/`, default rules, `pytest.ini` hints. Run it **in the repo you want SAGE to edit** (not necessarily the SAGE source tree). |
| **Use the interactive shell** | Run `sage` with no args — `/` opens a command menu, `/chat` starts a local LLM thread (saved under `.sage/chat_sessions/`). |
| **Configure models** | Per-role primary/fallback: **`~/.config/sage/models.yaml`** (or `$SAGE_MODELS_YAML`), or bundled defaults — see **`docs/models.md`**. |
| **Rules & memory** | `sage rules` / `sage rules validate` / `sage rules add "…"`; `sage memory` / `sage memory digest` — see **`docs/CLI.md`**. |
| **Benchmark & RL** | `sage bench`; `sage rl export`, `train-bc`, `train-cql`; `scripts/train_routing_policy.py` — see **`docs/getting_started.md`**. |
| **Hardware & models** | `sage prep` or `sage setup scan|suggest|apply|pull`; `sage config show|validate|set|migrate` — see **`docs/CLI.md`**. |
| **Ops & trust** | `sage session` (reset/handoff), `sage cron weekly-memory-optimizer`, `sage eval golden|e2e|smoke` |

---

## Requirements

- **Python 3.10+**
- **Optional:** [Ollama](https://ollama.com/) for local models (tags must match `ollama list` and your `models.yaml`)

---

## Install (SAGE repository clone)

**`startup.sh` and `startup.ps1` live only in the SAGE repository root** — not inside arbitrary project directories. Clone or unpack SAGE, then:

### Option A — bootstrap script (easiest)

| Platform | Steps |
|----------|--------|
| **Linux / macOS** | From the repo root: `bash startup.sh` then `source .venv/bin/activate` |
| **Windows** | `.\startup.ps1` then `.\.venv\Scripts\Activate.ps1` |

Creates `.venv`, installs the package in editable mode with dev deps (`pip install -e ".[dev,tui]"`).

### Option B — manual

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip wheel setuptools && pip install -e ".[dev,tui]"
```

(`[tui]` adds **Textual** for `sage tui`; omit for minimal install: `pip install -e .`)

### Pull models (Ollama)

```bash
ollama pull qwen2.5-coder:1.5b
ollama pull nomic-embed-text
```

Tiers, VRAM, and **404 model not found** → **[`docs/models.md`](docs/models.md)**.

---

## Your project directory (typical flow)

SAGE edits **the current working directory**. For a new sandbox:

```bash
mkdir -p ~/myproject && cd ~/myproject
sage init          # .sage/, memory/, rules scaffold
export SAGE_MODEL_PROFILE=test   # optional: one small Ollama model for every role (laptop/CI)
sage doctor        # Python, venv hint, Ollama, models.yaml
sage run "Create src/hello.py with greet() and tests/test_hello.py" --auto
```

- **`SAGE_MODEL_PROFILE=test`** — forces the test profile in bundled/user `models.yaml` (good when you want a single small local model).
- After each run, metrics are written to **`.sage/last_run_metrics.json`** (session id, task counts, model histogram, etc.). Set **`SAGE_RUN_OUTPUT=full`** for more detail in the end-of-run report; **`debug`** prints verbose verify lines.

Full env reference → **[`docs/CLI.md`](docs/CLI.md)**. Install details → **[`docs/INSTALL.md`](docs/INSTALL.md)**.

---

## First steps (after install)

```bash
cd /path/to/SAGE          # your clone
source .venv/bin/activate
sage doctor               # environment + optional Ollama checks
sage                      # interactive shell — try /commands
sage run "Scaffold a minimal FastAPI app with /health" --auto
sage status               # session snapshot (memory/system_state.json)
```

**Doc links in the shell:** set `export SAGE_REPO_URL=https://github.com/your-org/your-fork` so `/commands` footer URLs point at your fork.

---

## Interactive shell (high level)

- Built on **prompt_toolkit**: type **`/`** for completions; **Enter** submits the line.
- **`/chat`** — multi-turn local LLM thread; can attach to the next run via **`SAGE_CHAT_ATTACH_TO_RUN`** (see **`docs/CLI.md`**).
- **`agent`** / **`agent clear`** — build mode reminders and clearing attached chat context.

---

## Architecture (at a glance)

- **Orchestrator:** `src/sage/orchestrator/workflow.py`
- **Routing:** `src/sage/orchestrator/model_router.py`
- **Agents:** `src/sage/agents/`
- **Execution:** `src/sage/execution/`
- **Memory & RAG:** `src/sage/memory/`
- **CLI:** `src/sage/cli/`

**Spec vs shipped features:** **[`docs/ARCHITECTURE_STATUS.md`](docs/ARCHITECTURE_STATUS.md)** — use this for implementation truth vs long-form architecture docs.

Diagrams → **[`docs/architecture.md`](docs/architecture.md)**, **[`docs/architecture_diagram.md`](docs/architecture_diagram.md)**. Events → **[`docs/event_bus.md`](docs/event_bus.md)**.

---

## Documentation map

| Guide | What it covers |
|-------|----------------|
| **[`docs/README.md`](docs/README.md)** | **Full index** of every file in `docs/` (grouped by topic) |
| **[`docs/INSTALL.md`](docs/INSTALL.md)** | Bootstrap scripts, Windows vs Linux, pip |
| **[`docs/CLI.md`](docs/CLI.md)** | Shell, env vars, rules, memory digest, run output |
| **[`docs/models.md`](docs/models.md)** | `models.yaml`, Ollama tags, VRAM, bench timeouts |
| **[`docs/getting_started.md`](docs/getting_started.md)** | `bench`, `rl`, `sim`, training script |
| **[`docs/ARCHITECTURE_STATUS.md`](docs/ARCHITECTURE_STATUS.md)** | Spec parity / feature status |
| **[`docs/architecture.md`](docs/architecture.md)** | Design entrypoints |
| **[`docs/architecture_diagram.md`](docs/architecture_diagram.md)** | Diagrams |
| **[`docs/event_bus.md`](docs/event_bus.md)** | Event bus semantics |
| **[`docs/TRUST_AND_SCALE.md`](docs/TRUST_AND_SCALE.md)** | Policy, trust |
| **[`docs/LIVE_TESTING.md`](docs/LIVE_TESTING.md)** | Live Ollama, `scripts/live_verify.sh` |
| **[`docs/release_checklist.md`](docs/release_checklist.md)** | Release candidate checklist |
| **[`CONTRIBUTING.md`](CONTRIBUTING.md)** | Tests, **Ruff**, Mypy (CI), CI workflows |

**Architecture spec (design contract):** [`sage plan/SAGE_ARCHITECTURE_V1_FINAL.md`](sage%20plan/SAGE_ARCHITECTURE_V1_FINAL.md).

---

## Repository layout

```
src/sage/          # Application package (CLI, orchestrator, agents, memory, rl, …)
docs/              # Guides
images/            # README screenshots (this folder)
tests/             # pytest
scripts/           # Helpers (e.g. train_routing_policy.py)
pyproject.toml     # Packaging
startup.sh / .ps1  # Run from repo root only
```

Full tree → **[`project_structure.md`](project_structure.md)**.

---


If SAGE fits your workflow, show support with a **star** on the repository — it helps others discover the project.

## Star History

<a href="https://www.star-history.com/?repos=S.A.G.E%2FS.A.G.E&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=S.A.G.E/S.A.G.E&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=S.A.G.E/S.A.G.E&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=S.A.G.E/S.A.G.E&type=date&legend=top-left" />
 </picture>
</a>

If SAGE fits your workflow, show support with a **star** on the repository — it helps others discover the project.

---

## Contributing

See **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — unit tests, **`ruff check` / `ruff format`**, Mypy allowlist, benchmarks, live Ollama bar.
