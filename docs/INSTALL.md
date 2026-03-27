# Install & bootstrap (Linux / Windows)

## Quick path (recommended)

From the repository root:

### Linux / macOS

```bash
chmod +x startup.sh
./startup.sh
source .venv/bin/activate
sage doctor
sage
```

Or in one line without `chmod`:

```bash
bash startup.sh && source .venv/bin/activate
```

### Windows (PowerShell)

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\startup.ps1
.\.venv\Scripts\Activate.ps1
sage doctor
sage
```

The scripts:

1. Create **`.venv`** next to the repo if missing.
2. **Upgrade pip** and install the package in editable mode with **dev** extras: `pip install -e ".[dev]"`.
3. Print activation hints.

## Requirements

- **Python 3.10+** on `PATH` (`python3` on Linux, `python` on Windows).
- Optional: **Ollama** for local models (see `README.md` and `docs/models.md`).

## Environment variables (optional)

| Variable | Purpose |
|----------|---------|
| `SAGE_REPO_URL` | Base URL for repo/doc links in the CLI (`sage` shell help footer). |
| `PYTHON` | Linux only: override interpreter for `startup.sh` (default `python3`). |

## Manual install (no scripts)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip wheel
pip install -e ".[dev]"
```

Entry point: `sage` (see `pyproject.toml` `[project.scripts]`).

## Next steps

- **Getting started:** `docs/getting_started.md`
- **Interactive CLI:** `docs/CLI.md`
- **Models / Ollama:** `docs/models.md`
