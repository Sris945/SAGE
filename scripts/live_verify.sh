#!/usr/bin/env bash
# Live verification: real Ollama + real agent calls (shipping bar for OSS).
# Mocked e2e (tests/e2e/) is regression only — see docs/LIVE_TESTING.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="${PYTHON:-$ROOT/.venv/bin/python}"
else
  PY="${PYTHON:-python}"
fi

SAGE() { "$PY" -m sage.cli.main "$@"; }

if ! command -v ollama >/dev/null 2>&1; then
  echo "[live] ERROR: ollama not in PATH. Install: https://ollama.com/download"
  exit 1
fi

# Wait for API if user already has `ollama serve` or app running
if ! curl -sSf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  echo "[live] Starting ollama serve (background)..."
  nohup ollama serve >"${TMPDIR:-/tmp}/ollama-live.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -sSf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
fi

export SAGE_MODEL_PROFILE=test
export SAGE_NON_INTERACTIVE=1

echo "[live] pull qwen2.5-coder:1.5b (skip if already present)"
ollama pull qwen2.5-coder:1.5b

echo "[live] pytest tests/integration -m ollama"
"$PY" -m pytest tests/integration -m ollama -v --tb=short

echo "[live] sage eval smoke"
SAGE eval smoke

echo "[live] OK — Ollama-backed integration passed"
