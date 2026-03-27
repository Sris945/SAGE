"""
Load BC checkpoint and predict primary vs fallback (Phase 5).
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

DEFAULT_CHECKPOINT = Path("memory") / "rl" / "policy_bc.joblib"
DEFAULT_MIN_CONFIDENCE = 0.55

_policy_loaded: bool = False
_cached_policy: RoutingPolicy | None = None


class RoutingPolicy:
    """Wraps sklearn models per agent_role."""

    def __init__(
        self,
        models: dict[str, Any],
        *,
        feature_keys: tuple[str, ...],
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        self._models = models
        self.feature_keys = feature_keys
        self.min_confidence = float(min_confidence)

    def predict_proba_fallback(
        self,
        agent_role: str,
        task_complexity_score: float,
        failure_count: int,
    ) -> tuple[float, float]:
        """
        Returns (p_fallback, confidence) where confidence is distance from 0.5
        or max class probability when available.
        """
        clf = self._models.get(agent_role)
        if clf is None:
            return 0.0, 0.0
        X = [[float(task_complexity_score), float(failure_count)]]
        try:
            proba = clf.predict_proba(X)[0]
            # classes_ order: typically [0, 1] for fallback
            classes = list(getattr(clf, "classes_", [0, 1]))
            p_fb = float(proba[classes.index(1)] if 1 in classes else proba[-1])
            conf = abs(p_fb - 0.5) * 2.0
            return p_fb, min(1.0, conf)
        except Exception:
            pred = int(clf.predict(X)[0])
            p_fb = 1.0 if pred == 1 else 0.0
            return p_fb, 0.6

    def should_use_fallback(
        self,
        agent_role: str,
        task_complexity_score: float,
        failure_count: int,
    ) -> tuple[bool, float]:
        p_fb, conf = self.predict_proba_fallback(agent_role, task_complexity_score, failure_count)
        if conf < self.min_confidence:
            return False, conf
        return p_fb >= 0.5, conf


def load_routing_policy(path: Path | None = None) -> RoutingPolicy | None:
    path = Path(path or os.environ.get("SAGE_RL_CHECKPOINT", str(DEFAULT_CHECKPOINT)))
    if not path.exists():
        return None
    try:
        try:
            import joblib

            payload = joblib.load(path)
        except ImportError:
            payload = pickle.loads(path.read_bytes())
    except Exception:
        return None
    if not isinstance(payload, dict) or "models" not in payload:
        return None
    if payload.get("kind") == "cql_ridge":
        return _load_cql_ridge_policy(payload)
    return RoutingPolicy(
        payload["models"],
        feature_keys=tuple(
            payload.get("feature_keys") or ("task_complexity_score", "primary_failure_count")
        ),
        min_confidence=float(os.environ.get("SAGE_RL_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)),
    )


def _load_cql_ridge_policy(payload: dict[str, Any]) -> RoutingPolicy | None:
    """
    Adapt a conservative Q-estimator checkpoint (kind=cql_ridge) into fallback probabilities.

    We compute Q0, Q1 and map their margin into a pseudo-probability.
    """
    try:
        models = payload["models"]
        feature_keys = tuple(
            payload.get("feature_keys") or ("task_complexity_score", "primary_failure_count")
        )
        lamb = float(payload.get("pessimism_lambda", 0.15))
    except Exception:
        return None

    class _CQLAdapter(RoutingPolicy):
        def __init__(self) -> None:
            super().__init__(
                {},
                feature_keys=feature_keys,
                min_confidence=float(
                    os.environ.get("SAGE_RL_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
                ),
            )

        def predict_proba_fallback(
            self, agent_role: str, task_complexity_score: float, failure_count: int
        ) -> tuple[float, float]:
            m = models.get(agent_role) if isinstance(models, dict) else None
            if not isinstance(m, dict):
                return 0.0, 0.0
            qm = m.get("q_models") or {}
            counts = m.get("counts") or {}
            q0 = qm.get(0)
            q1 = qm.get(1)
            if q0 is None or q1 is None:
                return 0.0, 0.0
            x = [[float(task_complexity_score), float(failure_count)]]
            try:
                v0 = float(q0.predict(x)[0])
                v1 = float(q1.predict(x)[0])
            except Exception:
                return 0.0, 0.0

            # Conservative penalty: downweight under-sampled actions.
            c0 = float(counts.get(0, 0) or 0)
            c1 = float(counts.get(1, 0) or 0)
            v0c = v0 - lamb * (1.0 / max(c0, 1.0) ** 0.5)
            v1c = v1 - lamb * (1.0 / max(c1, 1.0) ** 0.5)

            margin = v1c - v0c
            # Map margin to p_fallback via logistic; confidence is |p-0.5| scaled.
            try:
                import math

                p_fb = 1.0 / (1.0 + math.exp(-margin))
            except Exception:
                p_fb = 1.0 if margin > 0 else 0.0
            conf = abs(p_fb - 0.5) * 2.0
            return float(p_fb), float(min(1.0, conf))

    return _CQLAdapter()


def get_routing_policy() -> RoutingPolicy | None:
    global _policy_loaded, _cached_policy
    if not _policy_loaded:
        _cached_policy = load_routing_policy()
        _policy_loaded = True
    return _cached_policy


def clear_routing_policy_cache() -> None:
    global _policy_loaded, _cached_policy
    _policy_loaded = False
    _cached_policy = None
