# Planner Instructions

TASK: {task_description}
PROJECT CONTEXT: {project_memory_summary}

RULES:

- Break tasks into small, concrete steps (each 2-5 min of work)
- assigned_agent must be exactly ONE of: coder, architect, reviewer, test_engineer
- dependencies is a list of task IDs that must complete first (empty list [] if none)
- verification: a safe shell command to verify the output (e.g. "python -c 'import app'" or "pytest tests/test_app.py -x -q"). Use "" if no check is needed.
- brainstorm_questions: ask 0-3 clarifying questions if genuinely unclear; otherwise empty list

EXAMPLE OUTPUT (copy this exact structure, change the values):
{"brainstorm_questions":[],"confirmed":true,"dag":{"nodes":[{"id":"task_001","description":"Create app.py with a FastAPI app instance","dependencies":[],"assigned_agent":"coder","verification":"python -c 'import app'"},{"id":"task_002","description":"Add a GET /health route that returns {\"status\": \"ok\"}","dependencies":["task_001"],"assigned_agent":"coder","verification":"python -c 'import app; r=app.app.routes; print(r)'"}]}}

NOW OUTPUT THE JSON FOR THE TASK ABOVE:
