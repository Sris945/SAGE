# Reviewer Instructions

TASK: {task_description}
FILE: {file_path}

FILE CONTENT:
{file_content}

SCOPE (critical — read first):

- Judge **only** whether the file **implements the TASK** above (description + intent).
- **Do NOT** require FastAPI, Flask, Django, or any framework **unless the TASK text explicitly names it**.
- **Do NOT** copy failure reasons from the EXAMPLES below; those show JSON shape only, not requirements.
- Planning-only or documentation tasks may PASS with Markdown/text that addresses the task — no web framework required.

RULES:

- verdict must be exactly ONE of: PASS, FAIL
- score: float 0.0-1.0 (1.0 = perfect, 0.0 = unusable)
- issues: list of specific problems (empty list [] if none)
- suggestion: one sentence improvement if FAIL, empty string "" if PASS
- PASS if: file is non-empty, plausibly implements the TASK, valid Python (if .py) or appropriate format
- FAIL if: file is empty, **clearly wrong for this TASK**, syntax error (Python), or totally off-topic

EXAMPLE OUTPUT (shape only):
{"verdict":"PASS","score":0.85,"issues":[],"suggestion":""}

EXAMPLE FAIL (shape only — issues must match the actual TASK, not this example):
{"verdict":"FAIL","score":0.2,"issues":["File is empty"],"suggestion":"Add content that addresses the task description."}

NOW OUTPUT THE JSON VERDICT:
