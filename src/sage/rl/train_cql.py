"""
Conservative offline RL (CQL-style), contextual bandit variant (Phase 5).

For SAGE's current routing data (single-step decisions), we treat offline RL as a
contextual bandit:
  - state features: [task_complexity_score, primary_failure_count]
  - action: {0=primary, 1=fallback}
  - reward: scalar from export pipeline

We implement a conservative value estimator using ridge regression + a simple
count-based pessimism penalty to reduce exploitation of under-sampled actions.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CQLConfig:
    ridge_alpha: float = 1.0
    pessimism_lambda: float = 0.15
    min_samples_per_action: int = 25
    feature_keys: tuple[str, ...] = ("task_complexity_score", "primary_failure_count")


def train_cql_stub(
    data_path: Path,
    out_path: Path,
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Train a conservative contextual-bandit policy and write a checkpoint.

    Output checkpoint is compatible with `sage.rl.policy` loader (kind=cql_ridge).
    """
    from sage.rl.export_dataset import load_routing_jsonl

    cfg = CQLConfig()
    rows = load_routing_jsonl(Path(data_path))
    if not rows:
        raise ValueError(f"No rows in {data_path}")

    # Use sklearn if available for stable ridge; else fallback to numpy.
    try:
        import numpy as np
        from sklearn.linear_model import Ridge
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "CQL ridge policy requires numpy + scikit-learn. Install: pip install 'sage[rl]'"
        ) from e

    rng = np.random.RandomState(seed)

    roles = sorted({str(r.get("agent_role", "")) for r in rows if r.get("agent_role")})
    role_models: dict[str, Any] = {}
    role_stats: dict[str, Any] = {}

    for role in roles:
        role_rows = [r for r in rows if r.get("agent_role") == role]
        if len(role_rows) < (cfg.min_samples_per_action * 2):
            continue

        X = np.array(
            [
                [
                    float(r.get(cfg.feature_keys[0], 0.0)),
                    float(r.get(cfg.feature_keys[1], 0.0)),
                ]
                for r in role_rows
            ],
            dtype=np.float64,
        )
        a = np.array([int(r.get("action_fallback", 0) or 0) for r in role_rows], dtype=np.int64)
        y = np.array([float(r.get("reward", 0.0)) for r in role_rows], dtype=np.float64)

        # Fit separate ridge regressors for each action.
        q_models: dict[int, Any] = {}
        counts: dict[int, int] = {0: int((a == 0).sum()), 1: int((a == 1).sum())}
        for act in (0, 1):
            idx = np.where(a == act)[0]
            if len(idx) < cfg.min_samples_per_action:
                continue
            reg = Ridge(alpha=float(cfg.ridge_alpha), random_state=rng)
            reg.fit(X[idx], y[idx])
            q_models[act] = reg

        if 0 not in q_models or 1 not in q_models:
            continue

        role_models[role] = {"q_models": q_models, "counts": counts}
        role_stats[role] = {"n": int(len(role_rows)), "counts": counts}

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "kind": "cql_ridge",
        "feature_keys": cfg.feature_keys,
        "ridge_alpha": cfg.ridge_alpha,
        "pessimism_lambda": cfg.pessimism_lambda,
        "min_samples_per_action": cfg.min_samples_per_action,
        "models": role_models,
        "stats": role_stats,
    }
    # Use joblib if available.
    try:
        import joblib

        joblib.dump(payload, out_path)
    except Exception:
        out_path.write_bytes(json.dumps({"error": "joblib_dump_failed"}).encode("utf-8"))

    report: dict[str, Any] = {
        "status": "ok",
        "output": str(out_path),
        "roles_trained": sorted(role_models.keys()),
        "stats": role_stats,
    }
    report_path = out_path.with_suffix(out_path.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
