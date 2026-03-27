# Coder Instructions

TASK: {task_description}
PROJECT CONTEXT: {project_memory_summary}

RULES:

- operation must be exactly ONE of: create, edit, delete, run_command
- file: the relative path to write (for example "src/app.py")
- patch: the COMPLETE file content (for create/edit) or the shell command (for run_command)
- reason: one sentence explaining why
- epistemic_flags: list of strings like ["INFERRED"] if you are guessing; empty list [] if confident

EXAMPLE OUTPUT (copy this exact structure, change the values):
<!-- markdownlint-disable MD034 -->
{"file":"src/app.py","operation":"create","patch":"from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n","reason":"Creates the main FastAPI application with a health endpoint","epistemic_flags":[]}
<!-- markdownlint-enable MD034 -->

NOW OUTPUT THE JSON FOR THE TASK ABOVE:
