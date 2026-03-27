# SAGE interactive shell (slash commands)

SAGE’s default UX when you run `sage` in a TTY is a **persistent REPL**: one process stays open and reads **line-oriented** input via **Python Prompt Toolkit** (not `input()`), so completion, key bindings, and the bottom status bar work reliably.

## How “slash” works (vs plain `input()`)

| Mechanism | Role |
|-----------|------|
| **PromptSession** | Keeps the prompt active; maintains history and layout. |
| **Buffer** | Holds the current line; updates on each keystroke **before** Enter. |
| **Custom completer** (`_SageSlashCompleter`) | Treats the last token as the prefix, including a leading `/`, so `/prep` and `/help` match correctly. |
| **Key binding on `/`** | Inserts `/` and calls `start_completion` so the menu opens immediately (OpenClaw-style). |
| **Enter** | Submits the **whole line** to SAGE for parsing (`/run …`, NL, etc.). |

So: the CLI **does** react to `/` **before** Enter for **menu filtering**; it does **not** dispatch the command until you press Enter (same model as Claude Code / most terminal UIs).

## Environment variables (shell)

| Variable | Effect |
|----------|--------|
| `SAGE_SHELL_SIMPLE_INPUT=1` | Disable prompt_toolkit; plain `input()` — **no** `/` menu. |
| `SAGE_SHELL_COLUMN_COMPLETIONS=1` | Floating column completion menu (full terminal). |
| `SAGE_SHELL_READLINE_COMPLETIONS=1` | List-style completions (Linux console / some SSH). |
| `SAGE_SHELL_NO_STATUSBAR=1` | Hide the bottom status block. |
| `SAGE_SHELL_INTENT` | `heuristic` \| `ollama` \| `off` — NL routing before `run`. |
| `SAGE_REPO_URL` | Base URL for repo/doc links printed after `/commands`. |

See also **INSTALL.md** for bootstrap and **README.md** for the project overview.

## Commands (summary)

Run `sage` then type `/commands` or see the Rich table printed after `/help`. Notable entries:

- **`run`** — Full pipeline (planner → agents → verify).
- **`chat` / `start chat`** — Local Ollama chat thread; logs under `.sage/chat_sessions/`.
- **`agent` / `agent clear`** — Reminder for build mode; clear attachment context for the next run.
- **`doctor`, `init`, `prep`, `setup`, `config`, …** — See catalog in the shell.

## Documentation links in the terminal

After `/commands`, the shell prints links derived from **`SAGE_REPO_URL`** (or `git remote origin` when unset). Set:

```bash
export SAGE_REPO_URL=https://github.com/your-org/your-fork
```

so links point at your canonical repo.
