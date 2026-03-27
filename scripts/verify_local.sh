#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="${PYTHON:-$ROOT/.venv/bin/python}"
  SAGE_BIN="${SAGE_BIN:-$ROOT/.venv/bin/sage}"
else
  PY="${PYTHON:-python}"
  SAGE_BIN="${SAGE_BIN:-sage}"
fi

echo "[verify] pytest"
$PY -m pytest tests/ -q

echo "[verify] Phase 5: collect+export"
$SAGE_BIN rl collect-synth --rows 650 >/dev/null
$SAGE_BIN rl export --output datasets/routing_v1.jsonl >/dev/null

echo "[verify] Phase 5: reward report"
$SAGE_BIN rl analyze-rewards --data datasets/routing_v1.jsonl --out datasets/reward_report.json >/dev/null

echo "[verify] Phase 5: train BC + CQL"
$SAGE_BIN rl train-bc  --data datasets/routing_v1.jsonl --out memory/rl/policy_bc.joblib >/dev/null
$SAGE_BIN rl train-cql --data datasets/routing_v1.jsonl --out memory/rl/policy_cql.joblib >/dev/null

echo "[verify] Phase 5: offline eval"
$SAGE_BIN rl eval-offline --data datasets/routing_v1.jsonl --checkpoint memory/rl/policy_cql.joblib --out datasets/offline_eval_cql.json >/dev/null

echo "[verify] Bench artifact"
$SAGE_BIN bench --out memory/benchmarks/bench.json >/dev/null || true

echo "[verify] Phase 6: sim generate+run"
$SAGE_BIN sim generate --count 1000 --out datasets/sim_tasks.jsonl >/dev/null
$SAGE_BIN sim run --tasks datasets/sim_tasks.jsonl --workers 2 --limit 20 >/dev/null

echo "[verify] done"

