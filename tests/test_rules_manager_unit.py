"""Unit tests for prompt_engine.rules_manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage.prompt_engine.rules_manager import (
    load_merged_rules,
    load_rule_layers,
    validate_rule_layers,
)


def test_validate_detects_requests_contradiction(tmp_path: Path) -> None:
    from sage.prompt_engine.rules_manager import RulesLayer

    layers = [
        RulesLayer(label="a", path=tmp_path / "a.md", text="Always use requests for HTTP."),
        RulesLayer(label="b", path=tmp_path / "b.md", text="Never use requests."),
    ]
    w = validate_rule_layers(layers)
    assert any("requests" in x.lower() for x in w)


def test_load_merged_orders_global_before_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".sage").mkdir(parents=True)
    (home / ".sage" / "rules.md").write_text("GLOBAL", encoding="utf-8")
    proj = tmp_path / "proj"
    (proj / ".sage").mkdir(parents=True)
    (proj / ".sage" / "rules.md").write_text("PROJECT", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    merged = load_merged_rules(agent_role="coder", base_dir=proj)
    assert "GLOBAL" in merged and "PROJECT" in merged
    assert merged.index("GLOBAL") < merged.index("PROJECT")


def test_validate_warns_chmod_777(tmp_path: Path) -> None:
    from sage.prompt_engine.rules_manager import RulesLayer

    layers = [
        RulesLayer(
            label="a",
            path=tmp_path / "a.md",
            text="For quick debug, chmod 777 the data dir.",
        )
    ]
    w = validate_rule_layers(layers)
    assert any("777" in x for x in w)


def test_agent_specific_layer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "isohome"
    (home / ".sage").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / ".sage").mkdir(parents=True)
    (tmp_path / ".sage" / "rules.planner.md").write_text("PLANNER ONLY", encoding="utf-8")
    layers = load_rule_layers(agent_role="planner", base_dir=tmp_path)
    assert len(layers) == 1
    assert layers[0].text == "PLANNER ONLY"
