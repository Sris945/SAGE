"""
Behavior cloning baseline for routing (Phase 5): sklearn logistic regression per role.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from sage.rl.export_dataset import load_routing_jsonl
from sage.rl.schema import ROUTING_SCHEMA_VERSION

FEATURE_KEYS = ("task_complexity_score", "primary_failure_count")


def _rows_to_xy(
    rows: list[dict[str, Any]], agent_role: str
) -> tuple[np.ndarray, np.ndarray] | None:
    xs: list[list[float]] = []
    ys: list[int] = []
    for r in rows:
        if r.get("agent_role") != agent_role:
            continue
        if int(r.get("action_fallback", 0)) not in (0, 1):
            continue
        xs.append(
            [
                float(r.get("task_complexity_score", 0.0)),
                float(r.get("primary_failure_count", 0)),
            ]
        )
        ys.append(int(r.get("action_fallback", 0)))
    if len(xs) < 4:
        return None
    return np.array(xs, dtype=np.float64), np.array(ys, dtype=np.int64)


def train_bc_joblib(
    data_path: Path,
    out_path: Path,
    *,
    test_fraction: float = 0.2,
    seed: int = 42,
) -> dict[str, Any]:
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score
    except ImportError as e:
        raise ImportError(
            "Behavior cloning requires scikit-learn. Install: pip install scikit-learn "
            "or pip install 'sage[rl]'"
        ) from e

    rows = load_routing_jsonl(data_path)
    if not rows:
        raise ValueError(f"No rows in {data_path}")

    roles = sorted({str(r.get("agent_role", "")) for r in rows if r.get("agent_role")})
    models: dict[str, Any] = {}
    metrics: dict[str, Any] = {}

    rng = np.random.RandomState(seed)
    for role in roles:
        xy = _rows_to_xy(rows, role)
        if xy is None:
            continue
        X, y = xy
        if len(X) < 6:
            X_train, y_train = X, y
            X_test, y_test = X, y
        else:
            uniq = np.unique(y)
            strat = y if len(uniq) > 1 and len(X) >= 10 else None
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_fraction, random_state=rng, stratify=strat
            )
        clf = LogisticRegression(max_iter=200, random_state=seed)
        clf.fit(X_train, y_train)
        models[role] = clf
        pred = clf.predict(X_test)
        metrics[role] = {
            "accuracy": float(accuracy_score(y_test, pred)),
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
        }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import joblib

        joblib.dump(
            {
                "schema_version": ROUTING_SCHEMA_VERSION,
                "kind": "bc_sklearn_logistic",
                "feature_keys": FEATURE_KEYS,
                "models": models,
                "metrics": metrics,
            },
            out_path,
        )
    except ImportError:
        import pickle

        out_path.write_bytes(
            pickle.dumps(
                {
                    "schema_version": ROUTING_SCHEMA_VERSION,
                    "kind": "bc_sklearn_logistic",
                    "feature_keys": FEATURE_KEYS,
                    "models": models,
                    "metrics": metrics,
                }
            )
        )

    report = {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "output": str(out_path),
        "roles_trained": list(models.keys()),
        "metrics": metrics,
    }
    report_path = out_path.with_suffix(out_path.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
