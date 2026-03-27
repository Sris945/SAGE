## Architecture (Spec-parity)

Canonical spec: `plan final/SAGE_v1_FINAL.md`.

High-signal docs in this repo:

- `docs/architecture_diagram.md`
- `docs/event_bus.md`
- `docs/models.md`

Key implementation entrypoints:

- Orchestrator workflow: `src/sage/orchestrator/workflow.py`
- Routing: `src/sage/orchestrator/model_router.py`
- Execution + verification: `src/sage/execution/executor.py`, `src/sage/execution/verifier.py`
- Benchmarks: `src/sage/benchmarks/runner.py` + `src/sage/benchmarks/tasks/*.yaml`

