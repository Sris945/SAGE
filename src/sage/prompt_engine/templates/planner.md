# Planner Instructions

TASK: {task_description}
PROJECT CONTEXT: {project_memory_summary}

RULES (product-grade / “IDE assistant” bar):

- Break work into **small, concrete** tasks. Prefer **3–5 goal-aligned tasks** over one vague mega-task.
- **Mirror the user’s literal goal.** If they name **FastAPI**, **Flask**, **Django**, **Click**, **Typer**, etc., the plan must implement **that** stack — not a generic script unless the user asked for a script only.
- When the user asks for an **HTTP API** (REST, `/health`, OpenAPI, ASGI, “run with uvicorn”, etc.), plan **that framework** end-to-end:
  - **task_a** — add **`requirements.txt`** (or **`pyproject.toml`**) listing **runtime deps** the stack needs (e.g. `fastapi`, `uvicorn[standard]`). `assigned_agent`: **coder**.  
    `verification`: `python -c "from pathlib import Path; p=Path('requirements.txt'); assert p.exists() and p.read_text().strip(), 'missing requirements'"`
  - **task_b** — implement the app module (path must match the stack, e.g. **`src/app.py`** with a **`FastAPI()`** instance named **`app`** and routes the user asked for). `assigned_agent`: **coder**.  
    **Dependencies:** `[task_a]`.  
    `verification` (FastAPI-style):  
    `python -m py_compile src/app.py && python -c "import sys; sys.path.insert(0, 'src'); import app; a=getattr(app, 'app', None); assert a is not None, 'expected FastAPI/Starlette app object app.app'"`
    (Adjust the import check if the entry module name differs — but stay consistent for `src/app.py`.)
  - **task_c** — **`tests/test_app.py`**: tests that **fail if the user’s goal is missing** (e.g. `TestClient` against **`/health`** when requested). `assigned_agent`: **test_engineer**. **Dependencies:** `[task_b]`.  
    `verification`: `pytest tests/test_app.py -q`
- If the repo is **not** Python, adapt the dependency + implementation + test pattern to that ecosystem; still keep **dependency manifest → implementation → tests → verify**.
- **verification**: one shell-safe command per task. You may chain checks with **` && `** (space-ampersand-space) when both steps are needed. Use only `python`, `python -m`, `pytest`, etc. — no shell pipes, no `sudo`, no downloads.
- **assigned_agent** must be exactly ONE of: coder, architect, reviewer, test_engineer, documentation
- For **documentation-only** work (README, CONTRIBUTING, CHANGELOG, user guides, `docs/*.md`): use **documentation** and a **verification** command that asserts the target file exists with substance (e.g. `python -c "from pathlib import Path; p=Path('README.md'); assert p.is_file() and len(p.read_text(errors='ignore').strip())>40"` — adjust the path to match the task).
- **dependencies**: list of task IDs that must complete first (use `[]` if none)
- **brainstorm_questions**: 0–4 short questions **only** if the goal is genuinely ambiguous. If you can plan confidently, use `[]` and set **confirmed** `true`.
- **confirmed**: boolean — `true` if the goal is clear enough to build a DAG without user input

EXAMPLE SHAPE (FastAPI + /health — adapt to the real TASK). Emit raw JSON only — no ``` fences, no commentary:

{"brainstorm_questions":[],"confirmed":true,"dag":{"nodes":[{"id":"task_001","description":"Add requirements.txt with fastapi and uvicorn","dependencies":[],"assigned_agent":"coder","verification":"python -c \"from pathlib import Path; t=Path('requirements.txt').read_text(errors='ignore').lower(); assert 'fastapi' in t and 'uvicorn' in t\""},{"id":"task_002","description":"Implement FastAPI in src/app.py with GET /health returning {\\\"status\\\":\\\"ok\\\"}","dependencies":["task_001"],"assigned_agent":"coder","verification":"python -m py_compile src/app.py && python -c \"import sys; sys.path.insert(0,'src'); import app; assert getattr(app,'app',None) is not None\""},{"id":"task_003","description":"Pytest tests for /health via TestClient in tests/test_app.py","dependencies":["task_002"],"assigned_agent":"test_engineer","verification":"pytest tests/test_app.py -q"}]}}

NOW OUTPUT THE JSON FOR THE TASK ABOVE (raw JSON only, single object):
