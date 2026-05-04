"""
Unit tests for the surgical_edit operation in ToolExecutionEngine
and the legacy PatchRequest -> executor path.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from sage.execution.executor import ToolExecutionEngine
from sage.protocol.schemas import PatchRequest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        textwrap.dedent("""\
            def greet(name: str) -> str:
                return f"Hello, {name}!"

            def add(a: int, b: int) -> int:
                return a + b
        """),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def engine(workspace: Path) -> ToolExecutionEngine:
    return ToolExecutionEngine(workspace_roots=[workspace])


class TestSurgicalEdit:
    def test_replaces_unique_string(self, engine: ToolExecutionEngine, workspace: Path):
        patch_spec = json.dumps({
            "old_string": 'return f"Hello, {name}!"',
            "new_string": 'return f"Hi, {name}!"',
        })
        req = PatchRequest(
            file=str(workspace / "src" / "app.py"),
            operation="surgical_edit",
            patch=patch_spec,
            reason="update greeting",
        )
        result = engine.execute(req)
        assert result["status"] == "ok"
        content = (workspace / "src" / "app.py").read_text()
        assert 'Hi, {name}' in content
        assert 'Hello, {name}' not in content

    def test_missing_old_string_returns_error(self, engine: ToolExecutionEngine, workspace: Path):
        patch_spec = json.dumps({
            "old_string": "this string does not exist in the file",
            "new_string": "replacement",
        })
        req = PatchRequest(
            file=str(workspace / "src" / "app.py"),
            operation="surgical_edit",
            patch=patch_spec,
            reason="test",
        )
        result = engine.execute(req)
        assert result["status"] == "error"
        assert "not found" in result.get("error", "").lower()

    def test_duplicate_old_string_returns_error(self, engine: ToolExecutionEngine, workspace: Path):
        # Write a file with a repeated line
        dup = workspace / "dup.py"
        dup.write_text("x = 1\nx = 1\n", encoding="utf-8")
        patch_spec = json.dumps({
            "old_string": "x = 1",
            "new_string": "x = 2",
        })
        req = PatchRequest(
            file=str(dup),
            operation="surgical_edit",
            patch=patch_spec,
            reason="test",
        )
        result = engine.execute(req)
        assert result["status"] == "error"
        assert "2" in result.get("error", "")

    def test_empty_old_string_returns_error(self, engine: ToolExecutionEngine, workspace: Path):
        patch_spec = json.dumps({"old_string": "", "new_string": "x"})
        req = PatchRequest(
            file=str(workspace / "src" / "app.py"),
            operation="surgical_edit",
            patch=patch_spec,
            reason="test",
        )
        result = engine.execute(req)
        assert result["status"] == "error"

    def test_missing_file_returns_error(self, engine: ToolExecutionEngine, workspace: Path):
        patch_spec = json.dumps({"old_string": "x", "new_string": "y"})
        req = PatchRequest(
            file=str(workspace / "ghost.py"),
            operation="surgical_edit",
            patch=patch_spec,
            reason="test",
        )
        result = engine.execute(req)
        assert result["status"] == "error"

    def test_invalid_json_patch_returns_error(self, engine: ToolExecutionEngine, workspace: Path):
        req = PatchRequest(
            file=str(workspace / "src" / "app.py"),
            operation="surgical_edit",
            patch="this is not json",
            reason="test",
        )
        result = engine.execute(req)
        assert result["status"] == "error"
        assert "json" in result.get("error", "").lower()

    def test_outside_workspace_rejected(self, engine: ToolExecutionEngine):
        patch_spec = json.dumps({"old_string": "x", "new_string": "y"})
        req = PatchRequest(
            file="/etc/passwd",
            operation="surgical_edit",
            patch=patch_spec,
            reason="test",
        )
        result = engine.execute(req)
        assert result["status"] == "error"
        assert "workspace" in result.get("error", "").lower()


class TestCreateEditLegacy:
    """Verify original create/edit operations still work correctly."""

    def test_create_new_file(self, engine: ToolExecutionEngine, workspace: Path):
        req = PatchRequest(
            file=str(workspace / "new_file.py"),
            operation="create",
            patch="x = 42\n",
            reason="test create",
        )
        result = engine.execute(req)
        assert result["status"] == "ok"
        assert (workspace / "new_file.py").read_text() == "x = 42\n"

    def test_edit_overwrites_file(self, engine: ToolExecutionEngine, workspace: Path):
        req = PatchRequest(
            file=str(workspace / "src" / "app.py"),
            operation="edit",
            patch="# completely replaced\n",
            reason="test edit",
        )
        result = engine.execute(req)
        assert result["status"] == "ok"
        assert (workspace / "src" / "app.py").read_text() == "# completely replaced\n"

    def test_delete_file(self, engine: ToolExecutionEngine, workspace: Path):
        to_delete = workspace / "temp.py"
        to_delete.write_text("temp\n")
        req = PatchRequest(
            file=str(to_delete),
            operation="delete",
            patch="",
            reason="cleanup",
        )
        result = engine.execute(req)
        assert result["status"] == "ok"
        assert not to_delete.exists()
