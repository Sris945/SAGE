# Architect Instructions

TASK: {task_description}
PROJECT CONTEXT: {project_memory_summary}

RULES:

- Decide the minimal folder structure and file list needed to complete this task
- tech_decisions: concise key-value map (framework, test_runner, entry_point, etc.) — use **"TBD"** or **"none"** if the TASK does not specify a web framework
- folders: list of directories to create (relative paths, trailing slash optional)
- files: list of source files the Coder will fill (relative paths)
- summary: one-line description of the architecture decision

EXAMPLE OUTPUT (multi-file; adapt to TASK):
{"folders":["src/","tests/"],"files":["src/app.py","tests/test_app.py"],"tech_decisions":{"framework":"TBD","test_runner":"pytest","entry_point":"src/app.py"},"summary":"src/ + tests/ layout; framework chosen to match user task"}

ANOTHER EXAMPLE (simple single-file task):
{"folders":[],"files":["app.py"],"tech_decisions":{"framework":"none","test_runner":"pytest"},"summary":"Single-file script with no sub-folder structure needed"}

NOW OUTPUT THE JSON BLUEPRINT FOR THE TASK ABOVE:
