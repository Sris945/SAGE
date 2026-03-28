# SAGE CLI — shell, `sage run`, rules, memory

## Interactive shell (slash commands)

SAGE’s default UX when you run `sage` in a TTY is a **persistent REPL**: one process stays open and reads **line-oriented** input via **Python Prompt Toolkit** (not `input()`), so completion, key bindings, and the bottom status bar work reliably.

### How “slash” works (vs plain `input()`)

| Mechanism | Role |
|-----------|------|
| **PromptSession** | Keeps the prompt active; maintains history and layout. |
| **Buffer** | Holds the current line; updates on each keystroke **before** Enter. |
| **Custom completer** (`_SageSlashCompleter`) | Treats the last token as the prefix, including a leading `/`. |
| **Key binding on `/`** | Inserts `/` and calls `start_completion` so the menu opens immediately. |
| **Enter** | Submits the **whole line** to SAGE for parsing (`/run …`, NL, etc.). |

### Environment variables (shell)

| Variable | Effect |
|----------|--------|
| `SAGE_SHELL_SIMPLE_INPUT=1` | Disable prompt_toolkit; plain `input()` — **no** `/` menu. |
| `SAGE_SHELL_COLUMN_COMPLETIONS=1` | Floating column completion menu (full terminal). |
| `SAGE_SHELL_READLINE_COMPLETIONS=1` | List-style completions (Linux console / some SSH). |
| `SAGE_SHELL_NO_STATUSBAR=1` | Hide the bottom status block. |
| `SAGE_SHELL_INTENT` | `heuristic` \| `ollama` \| `off` — NL routing before `run`. |
| `SAGE_REPO_URL` | Base URL for repo/doc links printed after `/commands`. |
| `SAGE_VERIFY_TIMEOUT_S` | Cap for **planner verification** subprocesses (seconds). **Unset** = no cap. `0` = unlimited. |
| `SAGE_RUN_OUTPUT` | **`summary`** (default) — end-of-run **Goal / Plan / Files / Outcome** panels. **`full`** — short verify labels + metrics line (`.sage/last_run_metrics.json`, checkpoint/intervention counts). **`debug`** — verbose `[Verify] Running: …` lines. |

After **`sage run`** (including `/run` from the shell), the CLI prints a structured Rich report.

---

## Headless run (`sage run`)

```text
sage run "your goal" [--research | --auto | --silent] [--no-clarify] [--plan-only] [--dry-run]
                       [--repo PATH] [--explain-routing] [--fresh] [--include GLOB ...]
```

| Mode / flag | Behavior |
|-------------|----------|
| **`--research`** (default) | Human checkpoints: post-plan approval (**`a`** approve / **`r`** reject / **`e`** edit `.sage/last_plan.json` then another `sage run "…"` **without** `--fresh`), escalation when the intel feed requires review, destructive tool apply confirmations where applicable. |
| **`--auto`** | Fewer interactive checkpoints (still logs). |
| **`--silent`** | Most autonomous; skips failed tasks per policy. |
| **`--no-clarify`** | Planner does not ask TTY clarifying questions (`SAGE_NO_CLARIFY=1` same). |
| **`--plan-only`** | Prints planner DAG and writes `.sage/last_plan.json`; no tool execution. |
| **`--dry-run`** | Does not apply file patches (verification may still run where applicable). |
| **`--repo PATH`** | Point at an existing repo for codebase intelligence (indexing / retrieval). |
| **`--explain-routing`** | After the run, print a routing decision summary for the session. |
| **`--fresh`** | Ignore `memory/handoff.json` (no resume from interrupt snapshot). |
| **`--include GLOB`** | Repeatable planner scope hints (e.g. `src/**/*.py`). |

Non-interactive automation: set **`SAGE_NON_INTERACTIVE=1`** so plan checkpoints default to approve without blocking on stdin.

**Interrupt resume:** If `memory/handoff.json` exists, the next `sage run "your goal"` loads it unless you pass **`--fresh`**. (Some messages still say `sage run --resume`; there is no separate `--resume` flag.)

### Run / session environment (selection)

| Variable | Effect |
|----------|--------|
| `SAGE_SESSION_ID` | Set by the CLI per run; correlates structured logs. |
| `SAGE_TRACE_ID` | Optional correlation id (also in `.sage/last_run_metrics.json`). |
| `SAGE_WORKSPACE_ROOT` | Set by the CLI to the run cwd. |
| `SAGE_MODEL_PROFILE` | e.g. **`test`** — use the `test` profile in `models.yaml` for all roles (small local models in CI/laptop). |
| `SAGE_MODELS_YAML` | Override path to `models.yaml` (default: `~/.config/sage/models.yaml` or bundled). |
| `SAGE_BENCH` | When set by `sage bench`, adjusts timeouts/profile. |
| `SAGE_PARALLEL_CONFLICT_UI` | Default `1` — Rich panel when parallel workers hit file-lock conflicts; set `0` to disable. |

End-of-run metrics JSON: **`.sage/last_run_metrics.json`** (task counts, `models_used`, `prompt_quality_delta`, `local_vs_cloud_ratio`, `human_checkpoints_reached`, …).

---

## Project bootstrap (`sage init`)

Run **`sage init`** in the **project directory** you want SAGE to work in (it does **not** install SAGE — use **`startup.sh`** from the **SAGE repository clone** for that).

`sage init` creates `.sage/`, ensures `memory/`, default **`.sage/rules.md`**, `pytest.ini` hints, and updates `.gitignore`. The CLI prints a **Next** panel with a sample `sage run` and `SAGE_MODEL_PROFILE=test`.

**Note:** **`startup.sh`** exists only in the SAGE repo root, not in each project folder.

---

## User rules (`sage rules`)

Merged **USER_RULES** load in this order (later files append; models see the full stack):

1. `~/.sage/rules.md` (global)
2. `.sage/rules.md` (project)
3. `.sage/rules.<agent>.md` (per agent, e.g. `rules.coder.md`)
4. Legacy `.sage-rules.md` if present

Commands:

- `sage rules` — print merged rules (`--agent`, `--path`, `--repo` as needed).
- `sage rules validate` — heuristic contradiction / safety checks (`--strict` exits non-zero on warnings).
- `sage rules add "Your rule sentence"` — append to `.sage/rules.md` (`--global` for `~/.sage/rules.md`).

---

## Memory

- `sage memory` — list files under `memory/`.
- `sage memory digest` — aggregate session logs + fix patterns into **`memory/weekly_digest.md`** (override with `--out`).

Session state: **`memory/system_state.json`**. Handoff: **`memory/handoff.json`**.

---

## Other commands (summary)

Run `sage commands` or `sage` → `/commands` for the full catalog.

| Command | Purpose |
|---------|---------|
| `sage shell` / bare `sage` (TTY) | Interactive slash-command shell (default when no subcommand) |
| `sage tui` | Full-screen Textual UI (`pip install 'sage[tui]'` or `textual`) |
| `sage doctor` | Environment: Python, venv, Ollama, `models.yaml`, optional Textual for TUI (`--json`) |
| `sage status` | Last saved session snapshot |
| `sage session` | `reset` / `refresh` / `status` / `handoff` (view or `--clear` interrupt handoff) |
| `sage prep` | Hardware scan + recommended Ollama pulls (`--disk-budget`, `--json`) |
| `sage setup` | `scan` \| `suggest` \| `apply` \| `pull` \| `init` — machine-aware Ollama routing |
| `sage config` | `show` \| `validate` \| `migrate` \| `paths` \| `set` — inspect/edit `models.yaml` |
| `sage bench` | Benchmark suite; `--out`, `--run-pack-dir`, `--compare-policy` |
| `sage permissions` | Tool policy; `permissions set …` writes `.sage/policy.json` |
| `sage rl` | `export`, `collect-synth`, `analyze-rewards`, `eval-offline`, `train-bc`, `train-cql` |
| `sage sim` | `generate` (oracle JSONL), `run` (parallel pytest; optional `--docker`) |
| `sage cron` | `weekly-memory-optimizer` — run maintenance jobs on demand |
| `sage eval` | `golden` \| `e2e` \| `smoke` — trust / regression checks (see tests) |

RL and simulator walkthrough → **[getting_started.md](getting_started.md)**.

---

## Documentation links in the terminal

After `/commands`, the shell prints links from **`SAGE_REPO_URL`** (or `git remote origin` when unset):

```bash
export SAGE_REPO_URL=https://github.com/your-org/your-fork
```

See also **`INSTALL.md`** (bootstrap) and **`README.md`** (overview).
