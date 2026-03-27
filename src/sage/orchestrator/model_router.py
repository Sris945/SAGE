"""
SAGE Model Router
-----------------
Every task type has a designated model with explicit fallback chain.
No agent randomly selects a model.
"""

import os
import yaml
from pathlib import Path

from sage.config.paths import bundled_models_yaml, resolved_models_yaml_path
from sage.llm.test_profile import maybe_apply_test_profile

DEFAULT_CONFIG = bundled_models_yaml()


class ModelRouter:
    def __init__(self, config_path: Path | None = None):
        path = config_path or resolved_models_yaml_path()
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.config = maybe_apply_test_profile(raw if isinstance(raw, dict) else {})

    def _eval_fallback_trigger(self, expr: str, ctx: dict[str, float | int]) -> bool:
        """
        Evaluate a *single* simple fallback trigger expression.

        Supported forms (no boolean operators; each trigger is a standalone
        condition):
          - `var > number`
          - `var >= number`
          - `var < number`
          - `var <= number`
          - `var == number`
          - `var != number`
        """
        import re

        expr = (expr or "").strip()
        m = re.fullmatch(
            r"(?P<var>[a-zA-Z_][a-zA-Z0-9_]*)\s*(?P<op>>=|<=|==|!=|>|<)\s*(?P<num>[0-9]+(?:\.[0-9]+)?)",
            expr,
        )
        if not m:
            # Unknown expression: safest behavior is "don't trigger".
            return False

        var = m.group("var")
        op = m.group("op")
        num_raw = m.group("num")

        ctx_val = ctx.get(var, 0)
        num_val = float(num_raw) if "." in num_raw else int(num_raw)

        left = float(ctx_val)
        right = float(num_val)
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        return False

    def should_use_fallback(
        self,
        agent_role: str,
        *,
        task_complexity_score: float = 0.0,
        failure_count: int = 0,
    ) -> bool:
        """
        Evaluate YAML fallback_triggers for (agent_role, task_complexity_score, failure_count).
        """
        routing = self.config.get("routing", {}).get(agent_role, {})
        triggers = routing.get("fallback_triggers") or []

        # Spec variables:
        # - task_complexity_score is evaluated directly
        # - primary_failure_count is mapped from failure_count (we don't track
        #   separate primary-model failures in MVP).
        ctx: dict[str, float | int] = {
            "task_complexity_score": float(task_complexity_score),
            "primary_failure_count": int(failure_count),
            "failure_count": int(failure_count),
        }

        if triggers:
            return any(self._eval_fallback_trigger(t, ctx) for t in triggers)

        # Back-compat fallback if no triggers exist.
        return failure_count >= 2 or float(task_complexity_score) > 0.8

    def select(
        self,
        agent_role: str,
        task_complexity_score: float = 0.0,
        failure_count: int = 0,
    ) -> str:
        """Return the appropriate model ID for this agent + context."""
        routing = self.config.get("routing", {}).get(agent_role, {})
        primary = routing.get("primary", "llama3:8b")
        fallback = routing.get("fallback", "claude-sonnet-4-5")

        # Evaluate YAML fallback triggers for observability.
        triggers = routing.get("fallback_triggers") or []
        ctx: dict[str, float | int] = {
            "task_complexity_score": float(task_complexity_score),
            "primary_failure_count": int(failure_count),
            "failure_count": int(failure_count),
        }
        matched_triggers: list[str] = []
        for t in triggers:
            if self._eval_fallback_trigger(t, ctx):
                matched_triggers.append(str(t))

        use_fallback = self.should_use_fallback(
            agent_role,
            task_complexity_score=task_complexity_score,
            failure_count=failure_count,
        )
        selected = fallback if use_fallback else primary
        policy_source = "yaml"

        if os.environ.get("SAGE_RL_POLICY") == "1":
            try:
                from sage.rl.policy import get_routing_policy

                pol = get_routing_policy()
                if pol is not None:
                    p_fb, conf = pol.predict_proba_fallback(
                        agent_role,
                        float(task_complexity_score),
                        int(failure_count),
                    )
                    if conf >= pol.min_confidence:
                        selected = fallback if p_fb >= 0.5 else primary
                        policy_source = "learned"
            except Exception as e:
                try:
                    from sage.observability.structured_logger import log_event

                    log_event(
                        "ROUTING_POLICY_ERROR",
                        payload={
                            "agent_role": agent_role,
                            "error": str(e),
                            "fallback_to_yaml": True,
                        },
                    )
                except Exception:
                    pass

        # Observability: record routing decision with matched triggers.
        try:
            from sage.observability.structured_logger import log_event

            log_event(
                "MODEL_ROUTING_DECISION",
                payload={
                    "agent_role": agent_role,
                    "task_complexity_score": float(task_complexity_score),
                    "primary_failure_count": int(failure_count),
                    "primary_model": primary,
                    "fallback_model": fallback,
                    "selected_model": selected,
                    "matched_fallback_triggers": matched_triggers,
                    "policy_source": policy_source,
                },
            )
        except Exception:
            pass

        return selected

    def get_primary_fallback(self, agent_role: str) -> tuple[str, str]:
        """
        Return (primary, fallback) model IDs for an agent role.
        Used by Tier 1 RL to define discrete strategy keys.
        """
        routing = self.config.get("routing", {}).get(agent_role, {})
        primary = routing.get("primary", "llama3:8b")
        fallback = routing.get("fallback", "claude-sonnet-4-5")
        return primary, fallback
