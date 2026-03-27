#!/usr/bin/env bash
# Local regression: unit tests + optional Ollama smoke (laptop-friendly).
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

export SAGE_MODEL_PROFILE="${SAGE_MODEL_PROFILE:-test}"

echo "[regression] sage eval golden (trace ordering, no Ollama)"
$SAGE_BIN eval golden

echo "[regression] pytest (unit + integration; skipped if no Ollama)"
$PY -m pytest tests/ -q

if command -v ollama >/dev/null 2>&1; then
  echo "[regression] sage eval smoke (Ollama)"
  $SAGE_BIN eval smoke
else
  echo "[regression] skip sage eval smoke (ollama not installed)"
fi

echo "[regression] done"
