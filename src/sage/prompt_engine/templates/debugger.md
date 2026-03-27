# Debugger Instructions

ERROR REPORT: {error_report}
FAILED FILE: {failed_file}
ORIGINAL TASK: {task_description}

RULES:

- operation must be exactly ONE of: edit, create, run_command
- file: the relative path of the file to fix
- patch: the COMPLETE corrected file content (for edit/create) or shell command (for run_command)
- reason: one sentence root cause explanation
- suspected_cause: most likely cause with confidence 0-1 (for example "missing import (0.9)")
- epistemic_flags: ["INFERRED"] if guessing, [] if confident
- Fix what **failed** for **this TASK** — do not assume FastAPI or any stack unless the TASK requires it.

EXAMPLE OUTPUT (structure only — **your patch must fix the actual error and match the TASK**):
<!-- markdownlint-disable MD034 -->
{"file":"src/app.py","operation":"edit","patch":"def add(a, b):\n    return a + b\n","reason":"Replaced placeholder with logic required by the task","suspected_cause":"incomplete implementation (0.85)","epistemic_flags":[]}
<!-- markdownlint-enable MD034 -->

NOW OUTPUT THE JSON FIX:
