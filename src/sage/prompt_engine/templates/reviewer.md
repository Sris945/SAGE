# Reviewer Instructions

TASK: {task_description}
FILE: {file_path}

FILE CONTENT:
{file_content}

RULES:

- verdict must be exactly ONE of: PASS, FAIL
- score: float 0.0-1.0 (1.0 = perfect, 0.0 = unusable)
- issues: list of specific problems (empty list [] if none)
- suggestion: one sentence improvement if FAIL, empty string "" if PASS
- PASS if: file is non-empty, implements the task, has no obvious bugs
- FAIL if: file is empty, wrong content, syntax error, or completely off-task

EXAMPLE OUTPUT:
{"verdict":"PASS","score":0.85,"issues":[],"suggestion":""}

EXAMPLE FAIL:
{"verdict":"FAIL","score":0.2,"issues":["Missing FastAPI import","Route decorator is wrong"],"suggestion":"Add 'from fastapi import FastAPI' and use @app.get('/health')"}

NOW OUTPUT THE JSON VERDICT:
