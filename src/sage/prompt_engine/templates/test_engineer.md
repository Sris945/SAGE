# Test Engineer Instructions

TASK: {task_description}
SOURCE FILE: {source_file}
TEST FILE TO GENERATE: {test_file}

SOURCE CODE:
{source_content}

RULES:

- Generate pytest unit tests that validate the source file above
- Tests must import from the source module correctly (use relative or absolute import based on path)
- Cover: happy path, edge cases, one error case minimum
- Return a JSON PatchRequest with the complete test file content in "patch"
- file: the test file path (use the TEST FILE path above)
- operation: always "create"
- patch: the complete Python test file content as a string
- Match the **actual** implementation (functions, classes, HTTP layer if any). **Do not** assume FastAPI unless the source uses it.

EXAMPLE OUTPUT (shape only):
{"file":"tests/test_app.py","operation":"create","patch":"import pytest\nimport src.app as app_mod\n\ndef test_importable():\n    assert app_mod is not None\n"}

NOW OUTPUT THE JSON PATCHREQUEST WITH THE TEST CODE:
