"""Debugger JSON normalisation — list-shaped model output must not crash."""

from __future__ import annotations

import pytest

from sage.agents import debugger as dbg


def test_normalise_patch_request_list() -> None:
    raw = [
        {"file": "src/hello.py", "patch": "def greet():\n    return 'hello'\n", "operation": "edit"}
    ]
    d = dbg._normalise_data(raw)
    assert d["file"] == "src/hello.py"
    pr = dbg._to_patch_request(d)
    assert pr.file == "src/hello.py"


def test_normalise_json_patch_add() -> None:
    raw = [{"op": "add", "path": "src/x.py", "value": "print(1)\n"}]
    d = dbg._normalise_data(raw)
    assert d["operation"] == "create"
    assert "x.py" in d["file"]


def test_normalise_bad_list_raises_instead_of_attrerror() -> None:
    with pytest.raises(ValueError, match="list"):
        dbg._normalise_data([1, 2, 3])
