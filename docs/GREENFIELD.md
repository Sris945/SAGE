# Greenfield projects in SAGE

**Greenfield** means: you run SAGE **without** `--repo` (or with an empty repo path). The workflow detects `repo_mode=greenfield` and **skips** the codebase-intel node (`codebase_intel` + post-scan checkpoint). The graph goes:

`load_memory` → `detect_mode` → **`prompt_middleware`** → `route_model` → `planner` → …

So yes — **SAGE can build a project from greenfield** per the orchestrator design: the planner breaks the goal into tasks, workers execute them (coder / architect / reviewer / test_engineer), tools apply patches under workspace policy, and memory is saved at the end.

## Revalidation in CI

- **Mocked full pipeline (no Ollama):** `tests/e2e/test_greenfield_pipeline_mocked.py`  
  Runs `app.invoke` with `repo_path=""`, `mode=auto`, and mocks planner/coder/reviewer/test_engineer. Asserts `hello.py` and `tests/test_hello.py` are created.

```bash
pytest tests/e2e/test_greenfield_pipeline_mocked.py -v
# or:
sage eval e2e
```

## Run a tiny real project on your machine

Use **hardware-aware** routing (not the test profile) unless you only want smoke speed:

```bash
sage prep
# optional: sage setup apply && sage setup pull
unset SAGE_MODEL_PROFILE   # real work: use models.yaml / prep suggestions
cd ~/somewhere
mkdir tiny-demo && cd tiny-demo
sage init
sage run "Create a single hello.py that defines hello() returning 'ok'. Add tests/test_hello.py." --auto
```

For a **smallest** real run, keep the prompt one task and use `--auto` to skip human checkpoints.

**Note:** A full real run exercises **Ollama** (planner, coder, reviewer, test_engineer, etc.). That is **not** the same as the mocked e2e test; both are valid.

## What “entire SAGE” means

- **Everything in one run:** the mocked e2e covers the **greenfield graph + worker + tool + verification gate + test file + save memory** path. It does **not** hit cloud APIs, Qdrant, or optional RL policy unless those code paths are triggered.
- **Optional features** (RL routing, sim, bench, RL export) are separate commands or env flags.

See also `docs/LOCAL_PROJECT_PREP.md` and `docs/TRUST_AND_SCALE.md`.
