# Contributing to SAGE

## Development

Run unit tests (default for every PR):

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

**Live / shipping bar (real Ollama, not stubs):** see **[`docs/LIVE_TESTING.md`](docs/LIVE_TESTING.md)** and run `./scripts/live_verify.sh` locally. CI runs a **`live`** job that installs Ollama and executes `pytest tests/integration -m ollama` plus `sage eval smoke`.

Mocked greenfield wiring-only test: `pytest tests/e2e/` — fast regression, **not** a substitute for live verification.

Run benchmark suite (Phase 4 contract):

```bash
PYTHONPATH=src ./.venv/bin/python -m sage.cli.main bench
```

Quick smoke run:

```bash
PYTHONPATH=src ./.venv/bin/python -m sage.cli.main run "health check" --auto --silent
```

## Adding new spec compliance checks

Prefer adding unit tests that validate:

- events emitted to the session journal (via `log_event`),
- workflow routing correctness (HITL, scheduler termination),
- and deterministic fallbacks when Ollama is unavailable.

Files to look at:

- `src/sage/orchestrator/workflow.py`
- `src/sage/observability/trajectory_logger.py`
- `src/sage/benchmarks/runner.py`

## Models

Users (and contributors) swap Ollama models via `src/sage/config/models.yaml`. See [`docs/models.md`](docs/models.md) for recommended tiers and benchmark-only timeout variables (`SAGE_BENCH*`).

## Event bus

Strict FIFO event processing: [`docs/event_bus.md`](docs/event_bus.md), implementation in `src/sage/orchestrator/event_bus.py`. Unit coverage: `tests/test_event_bus_strict_unit.py`.

## Roadmap after v1 (optional)

- **SAGE fine-tuned weights:** ship as another Ollama tag (or HTTP adapter) and point `models.yaml` at it — same plug-and-play mechanism as any user model.
- **Phase 5 offline RL:** requires sufficient logged trajectories and training pipeline work; see `plan final/SAGE_v1_FINAL.md` §26.1.

## CI and release hygiene

- CI workflow: `.github/workflows/ci.yml`
- Docker simulator smoke: `.github/workflows/docker-sim-smoke.yml`
- Local reproducibility matrix: `docs/verification_matrix.md`
- Release process checklist: `docs/release_checklist.md`
