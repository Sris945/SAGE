# Contributing to SAGE

## Development

Install editable with dev tools (same as CI):

```bash
pip install -e ".[dev]"          # matches CI; add `tui` if you use `sage tui` locally
```

### Lint and format (Ruff)

CI runs **Ruff** on `src/sage` and `tests`. Run locally before pushing:

```bash
ruff check src/sage tests
ruff format --check src/sage tests
```

Auto-fix style:

```bash
ruff check src/sage tests --fix
ruff format src/sage tests
```

Config: **`pyproject.toml`** (`[tool.ruff]`).

### Type checking (Mypy)

CI runs **mypy** on an allowlisted set of modules (see the **“Mypy”** step in **`.github/workflows/ci.yml`**). If you touch those files, run the same command locally so CI stays green.

### Tests

Run unit tests (default for every PR):

```bash
pytest tests/ -q
```

**Live / shipping bar (real Ollama, not stubs):** see **[`docs/LIVE_TESTING.md`](docs/LIVE_TESTING.md)** and run `./scripts/live_verify.sh` locally. CI runs a **`live`** job that installs Ollama and executes `pytest tests/integration -m ollama` plus `sage eval smoke`.

Mocked greenfield wiring-only test: `pytest tests/e2e/` — fast regression, **not** a substitute for live verification.

Run benchmark suite (Phase 4 contract):

```bash
sage bench
```

Quick smoke run (with venv activated so `sage` is on `PATH`):

```bash
sage run "health check" --auto --silent
```

If `sage` is not installed on `PATH`, use `python -m sage.cli.main …` from the repo root with `pip install -e ".[dev]"` active.

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
- **Phase 5 offline RL:** requires sufficient logged trajectories and training pipeline work; see `docs/research_notes.md` and `docs/getting_started.md`.

## CI and release hygiene

- CI workflow: `.github/workflows/ci.yml`
- Docker simulator smoke: `.github/workflows/docker-sim-smoke.yml`
- Local reproducibility matrix: `docs/verification_matrix.md`
- Release process checklist: `docs/release_checklist.md`
