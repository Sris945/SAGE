"""Test routing profile for laptop-friendly runs."""


def test_maybe_apply_test_profile_noop(monkeypatch):
    monkeypatch.delenv("SAGE_MODEL_PROFILE", raising=False)
    monkeypatch.delenv("SAGE_FORCE_LOCAL_MODEL", raising=False)
    from sage.llm.test_profile import maybe_apply_test_profile

    cfg = {"routing": {"coder": {"primary": "x", "fallback": "y", "fallback_triggers": ["a"]}}}
    out = maybe_apply_test_profile(cfg)
    assert out["routing"]["coder"]["primary"] == "x"


def test_maybe_apply_test_profile_forces_single_model(monkeypatch):
    monkeypatch.setenv("SAGE_MODEL_PROFILE", "test")
    from sage.llm import test_profile as tp
    from sage.llm.test_profile import maybe_apply_test_profile

    cfg = {"routing": {"coder": {"primary": "x", "fallback": "y", "fallback_triggers": ["a"]}}}
    out = maybe_apply_test_profile(cfg)
    assert out["routing"]["coder"]["primary"] == tp.DEFAULT_TEST_MODEL
    assert out["routing"]["coder"]["fallback"] == tp.DEFAULT_TEST_MODEL
    assert out["routing"]["coder"]["fallback_triggers"] == []


def test_force_local_model_override(monkeypatch):
    monkeypatch.setenv("SAGE_FORCE_LOCAL_MODEL", "tinyllama:latest")
    from sage.llm.test_profile import maybe_apply_test_profile

    cfg = {"routing": {"planner": {"primary": "x", "fallback": "y"}}}
    out = maybe_apply_test_profile(cfg)
    assert out["routing"]["planner"]["primary"] == "tinyllama:latest"
