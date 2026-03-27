# Live testing (OSS shipping bar)

SAGE is **not** meant to be validated only with stubs. We use two layers:

| Layer | What it is | When |
|--------|------------|------|
| **Unit + mocked e2e** | Fast, no Ollama, no network | Every PR (`ci.yml` `tests` job) |
| **Live** | Real Ollama, real `chat_with_timeout`, real `PlannerAgent`, real CLI subprocesses | **Required before tagging a release**; runs in CI (`live` job) |

## Mocked regression (not the shipping gate)

- `tests/e2e/test_greenfield_pipeline_mocked.py` — mocks agents to exercise the LangGraph wiring without a model. **Does not replace** live tests.

## Live verification (local)

Requires [Ollama](https://ollama.com) installed and on `PATH`, and a small model pulled (the script pulls `qwen2.5-coder:1.5b`).

```bash
chmod +x scripts/live_verify.sh
./scripts/live_verify.sh
```

This runs:

1. `pytest tests/integration -m ollama` — real planner + real chat tests  
2. `sage eval smoke` — same integration tests via the CLI entrypoint  

Set `SAGE_MODEL_PROFILE=test` for a single small model everywhere during these runs (CI does the same).

## CI

Workflow `.github/workflows/ci.yml` includes a **`live`** job (after unit tests pass) that installs Ollama, pulls `qwen2.5-coder:1.5b`, and runs the live pytest target.

If the live job fails, treat it as **release-blocking** for anything that claims “full stack works.”

## What “full codebase” means

- **Everything in one pytest file:** not realistic — bench, sim, RL, and full `sage run` end-to-end are **separate** entrypoints (`verify_local.sh` covers many of those without Ollama).
- **Full stack for agents:** live job + `verify_local.sh` together cover **CLI + Ollama + planner + optional RL/sim** paths.

See also `docs/TRUST_AND_SCALE.md` and `CONTRIBUTING.md`.
