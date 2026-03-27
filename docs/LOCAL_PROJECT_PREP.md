# Prepare a local project on your laptop

This is the workflow we discussed: **hardware-aware model picks** for real work, **without** forcing the tiny “test” profile that pins one small model everywhere.

## Greenfield vs existing repo

- **Greenfield** (no `--repo`): SAGE skips codebase scan and starts from `prompt_middleware` → planner. See **`docs/GREENFIELD.md`**.
- **Existing repo** (`--repo /path`): runs codebase intel first.

## 1. One-time: recommended models for *your* machine

```bash
sage prep
# or machine-readable:
sage prep --json
```

This runs the same logic as `sage setup suggest`: RAM/VRAM (when detectable) → a **tier** (minimal / light / balanced / …) → a **pull list** that fits `--disk-budget` (default ~18 GiB).

**Apply** the suggested routing into your user `models.yaml`:

```bash
sage setup apply --disk-budget 18
```

Then pull what you need:

```bash
sage setup pull --disk-budget 18
# or: ollama pull <tag>   # for each tag from `sage prep`
```

**Important — “hardware should not throttle” in plain terms**

| Mechanism | What it does |
|-----------|----------------|
| **`sage prep` / `setup suggest`** | Recommends models that **fit** your RAM/VRAM/disk. It does **not** slow the CPU or cap FPS; it only suggests tags. |
| **`SAGE_MODEL_PROFILE=test`** | For **pytest / CI / `sage eval smoke` only**. Forces **one tiny model** for every role. **Do not** export this for your own project work if you want quality routing. |
| **`SAGE_BENCH=1`** | Used by **`sage bench`** to **extend Ollama timeouts** so large models can finish. **Do not** set for normal `sage run` unless you are benchmarking. |

So: **real project** = use **`prep` + `setup apply`** and leave `SAGE_MODEL_PROFILE` unset. **Tests** = `SAGE_MODEL_PROFILE=test` or `sage eval smoke`.

## 2. Project folder

```bash
mkdir ~/work/my-app && cd ~/work/my-app
sage init
sage doctor
```

Edit `.sage/rules.md` with your conventions.

## 3. Run SAGE on your spec

```bash
sage run "your goal" --auto
# or interactive checkpoints:
sage run "your goal"
```

Review `.sage/last_plan.json` when the workflow pauses (research mode).

## 4. Verify traces and regression

```bash
sage eval golden    # ordering: MODEL_ROUTING_DECISION → CONTEXT_CLAMPED → TOKEN_USAGE (mocked)
sage eval smoke       # planner + real Ollama (optional)
pytest tests/ -q
```

Optional correlation across terminals: `export SAGE_TRACE_ID=$(uuidgen)` (or any string) before commands.

## 5. What we did *not* put in OSS

Hosted **authZ**, multi-tenant isolation, and a full **review UI** stay out of this repo; see `docs/TRUST_AND_SCALE.md`.
