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
| Benchmarks | `src/sage/benchmarks/runner.py`, `src/sage/benchmarks/tasks/*.yaml` |

For offline RL and simulator flows, see **`docs/getting_started.md`** and **`docs/research_notes.md`**.
