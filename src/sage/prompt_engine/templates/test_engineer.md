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

EXAMPLE OUTPUT:
{"file":"tests/test_app.py","operation":"create","patch":"import pytest\nfrom app import app\n\ndef test_health_endpoint():\n    from fastapi.testclient import TestClient\n    client = TestClient(app)\n    response = client.get('/health')\n    assert response.status_code == 200\n    assert response.json() == {'status': 'ok'}\n"}

NOW OUTPUT THE JSON PATCHREQUEST WITH THE TEST CODE:
