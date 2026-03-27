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

EXAMPLE OUTPUT (copy this exact structure, change the values):
<!-- markdownlint-disable MD034 -->
{"file":"src/app.py","operation":"edit","patch":"from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n","reason":"Fixed missing return statement in health route","suspected_cause":"missing return statement (0.95)","epistemic_flags":[]}
<!-- markdownlint-enable MD034 -->

NOW OUTPUT THE JSON FIX:
