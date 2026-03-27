# Coder Instructions

TASK: {task_description}
PROJECT CONTEXT: {project_memory_summary}

RULES:

- operation must be exactly ONE of: create, edit, delete, run_command
- file: the relative path to write (for example "src/app.py")
- patch: the COMPLETE file content (for create/edit) or the shell command (for run_command)
- reason: one sentence explaining why
- epistemic_flags: list of strings like ["INFERRED"] if you are guessing; empty list [] if confident
- Implement **this TASK** only — use whatever stack the TASK implies; **do not** default to FastAPI unless the TASK asks for it.
- **JSON only:** the ``patch`` string must be valid JSON: use ``\\n`` for newlines inside the string, escape quotes as ``\\\"``, or the parser will fail.

EXAMPLE OUTPUT (structure only — **your patch must match the TASK**):
<!-- markdownlint-disable MD034 -->
{"file":"src/app.py","operation":"create","patch":"def main():\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n","reason":"Minimal module scaffold required by the task","epistemic_flags":[]}
<!-- markdownlint-enable MD034 -->

NOW OUTPUT THE JSON FOR THE TASK ABOVE:
