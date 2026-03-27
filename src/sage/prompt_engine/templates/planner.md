# Planner Instructions

TASK: {task_description}
PROJECT CONTEXT: {project_memory_summary}

RULES:

- Break work into **small, concrete** tasks (each a few minutes). Prefer **fewer, goal-aligned tasks** over long waterfall checklists.
- **Match the user's goal** (e.g. calculator web app → implement that stack). Do **not** default to FastAPI or any framework unless the user asked for it or it clearly follows from the goal.
- assigned_agent must be exactly ONE of: coder, architect, reviewer, test_engineer
- dependencies is a list of task IDs that must complete first (empty list [] if none)
- verification: a safe shell command (e.g. `python -m py_compile path/to/file.py`, `pytest tests/ -q`). Use "" if not applicable.
- brainstorm_questions: 0–4 short questions **only** if the goal is ambiguous (stack, scope, deployment target, test depth). If you can plan confidently, use [] and set confirmed true.
- confirmed: boolean — true if the goal is clear enough to build a DAG without user input

EXAMPLE OUTPUT (structure only — **replace** nodes with tasks that fit the TASK above; do not copy framework names blindly):
{"brainstorm_questions":[],"confirmed":true,"dag":{"nodes":[{"id":"task_001","description":"Implement the minimal runnable code for the user goal in src/app.py","dependencies":[],"assigned_agent":"coder","verification":"python -m py_compile src/app.py"},{"id":"task_002","description":"Add tests/test_app.py for core behavior","dependencies":["task_001"],"assigned_agent":"test_engineer","verification":"pytest tests/test_app.py -q"}]}}

NOW OUTPUT THE JSON FOR THE TASK ABOVE:
