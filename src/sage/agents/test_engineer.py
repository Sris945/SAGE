"""
SAGE Test Engineer Agent
------------------------
Runs AFTER the CoderAgent writes a source file.
Generates a matching pytest test file for every implementation artifact.

TDD discipline enforced:
  - Reads the written source file
  - Generates pytest unit tests that validate the implementation
  - Writes to tests/<source_stem>_test.py
  - Returns the test file path for downstream Verification

Input:  written source file path + task dict + session_memory
Output: {"status": "completed"|"failed", "test_file": "tests/test_app.py"}

Primary model: As per model_router "test_engineer" role.
"""

import json
from pathlib import Path

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.agents.llm_parse import parse_json_object
from sage.cli.branding import print_agent_line
from sage.orchestrator.model_router import ModelRouter
from sage.llm.ollama_safe import chat_with_timeout, OllamaTimeout
from sage.protocol.schemas import AgentInsight

TEMPLATE_PATH = Path(__file__).parent.parent / "prompt_engine" / "templates" / "test_engineer.md"
TESTS_DIR = Path("tests")
MAX_SOURCE_LINES = 200  # cap to avoid prompt overload


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text()
    return ""


def _normalize_test_output_path(path_str: str) -> str:
    """Collapse accidental ``tests/tests/...`` (model path bugs) to ``tests/...``."""
    p = Path(path_str)
    parts = p.parts
    if len(parts) >= 2 and parts[0] == "tests" and parts[1] == "tests":
        return str(Path("tests").joinpath(*parts[2:]))
    return path_str


def _derive_test_path(source_file: str) -> str:
    """Derive test file path: 'src/app.py' → 'tests/test_app.py'."""
    stem = Path(source_file).stem
    return str(TESTS_DIR / f"test_{stem}.py")


def _read_source(source_file: str) -> str:
    p = Path(source_file)
    if not p.exists():
        return ""
    lines = p.read_text().splitlines()
    return "\n".join(lines[:MAX_SOURCE_LINES])


class TestEngineerAgent:
    def __init__(self):
        self.router = ModelRouter()
        self.template = _load_template()

    def run(
        self,
        source_file: str,
        task: dict,
        memory: dict,
        failure_count: int = 0,
        universal_prefix: str = "",
        insight_sink=None,
    ) -> dict:
        """
        Generate pytest tests for source_file.

        Returns:
          {
            "status": "patch_ready" | "failed" | "skipped",
            "test_file": str,
            "patch_request": {... PatchRequest fields ...},
          }
        """

        # Small helper: emit AgentInsight packets if an orchestrator sink exists.
        def _emit(
            insight_type: str,
            *,
            severity: str,
            content: str,
            requires_orchestrator_action: bool = False,
        ) -> None:
            if insight_sink is None:
                return
            try:
                insight_sink.ingest(
                    AgentInsight(
                        agent="test_engineer",
                        task_id=str(task.get("id", "")),
                        insight_type=insight_type,
                        content=(content or "")[:2000],
                        severity=severity,
                        requires_orchestrator_action=requires_orchestrator_action,
                    )
                )
            except Exception:
                return

        # Skip non-Python files
        if not source_file.endswith(".py"):
            print_agent_line("TestEngineer", f"Skipping non-Python file: {source_file}")
            _emit(
                "observation",
                severity="low",
                content=f"Skipping non-Python file for test gen: {source_file}",
            )
            return {"status": "skipped", "test_file": ""}

        test_file = _derive_test_path(source_file)
        source_content = _read_source(source_file)
        if not source_content.strip():
            print_agent_line(
                "TestEngineer", f"Source file empty or missing: {source_file} — skipping."
            )
            _emit(
                "observation",
                severity="low",
                content=f"Source empty/missing; skipping test gen: {source_file}",
            )
            return {"status": "skipped", "test_file": ""}

        model = self.router.select(
            "test_engineer",
            task_complexity_score=float(task.get("task_complexity_score", 0.0) or 0.0),
            failure_count=failure_count,
        )
        print_agent_line("TestEngineer", f"Using model: {model}")
        print_agent_line("TestEngineer", f"Generating tests for: {source_file}")

        _emit(
            "decision",
            severity="low",
            content=f"Test engineer selected model={model} for test generation.",
        )

        system = (
            self.template.replace("{task_description}", task.get("description", ""))
            .replace("{source_file}", source_file)
            .replace("{source_content}", source_content)
            .replace("{test_file}", test_file)
        )
        if universal_prefix:
            system = universal_prefix + "\n\n" + system

        try:
            response = chat_with_timeout(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Generate pytest tests for {source_file}.\n"
                            f"TASK: {task.get('description', '')}\n\n"
                            "Return ONLY a JSON PatchRequest with the test code. No prose."
                        ),
                    },
                ],
                options={"temperature": 0.1},
                timeout_s=None,
            )
        except (OllamaTimeout, RuntimeError, Exception) as e:
            print_agent_line("TestEngineer", f"Model call failed/timeout: {e} — failing.")
            _emit(
                "risk",
                severity="high",
                content=f"Test generation model call failed/timeout: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return {"status": "failed", "test_file": test_file}

        msg = response.get("message") or {}
        raw = msg.get("content", "") if isinstance(msg, dict) else ""
        try:
            data = parse_json_object(raw)
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            print_agent_line("TestEngineer", f"Parse failed: {e} — skipping.")
            _emit(
                "risk",
                severity="high",
                content=f"Failed to parse test_engineer response into PatchRequest: {str(e)[:1200]}",
                requires_orchestrator_action=True,
            )
            return {"status": "skipped", "test_file": ""}

        # Allow model to override test_file path
        out_file = _normalize_test_output_path(str(data.get("file", test_file)))
        code = data.get("patch") or data.get("content") or data.get("code") or data.get("value", "")
        if not isinstance(code, str):
            code = json.dumps(code, indent=2) if code is not None else ""
        if not code.strip():
            print_agent_line("TestEngineer", "Model returned empty test code — skipping.")
            _emit(
                "observation",
                severity="low",
                content=f"Empty test code returned; skipping. source={source_file}",
            )
            return {"status": "skipped", "test_file": ""}

        patch_request = {
            "file": out_file,
            "operation": "create",
            "patch": code,
            "reason": f"Auto-generated tests for {source_file}",
            "epistemic_flags": [],
        }

        print_agent_line("TestEngineer", f"PatchRequest ready → {out_file}")
        _emit(
            "observation",
            severity="low",
            content=f"Generated test PatchRequest: file={out_file}",
        )
        return {
            "status": "patch_ready",
            "test_file": out_file,
            "patch_request": patch_request,
        }
