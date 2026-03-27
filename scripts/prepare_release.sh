#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="${PYTHON:-$ROOT/.venv/bin/python}"
  SAGE_BIN="${SAGE_BIN:-$ROOT/.venv/bin/sage}"
else
  PY="${PYTHON:-python}"
  SAGE_BIN="${SAGE_BIN:-sage}"
fi

run_step() {
  local label="$1"
  shift
  echo "[prepare_release] $label"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  DRY-RUN: $*"
    return 0
  fi
  "$@"
}

require_file() {
  local p="$1"
  if [ ! -f "$p" ]; then
    echo "[prepare_release] missing required file: $p" >&2
    exit 1
  fi
}

echo "[prepare_release] validating required release docs"
require_file "README.md"
require_file "CONTRIBUTING.md"
require_file "CHANGELOG.md"
require_file "docs/final_checklist.md"
require_file "docs/research_notes.md"
require_file "docs/verification_matrix.md"
require_file "docs/release_checklist.md"

run_step "pytest" "$PY" -m pytest tests/ -q
run_step "verify local matrix" "$ROOT/scripts/verify_local.sh"
run_step "doctor preflight" "$SAGE_BIN" doctor --json
run_step "config validation" "$SAGE_BIN" config validate
run_step "bench smoke artifact" "$SAGE_BIN" bench --out memory/benchmarks/release_smoke.json

echo "[prepare_release] release preflight passed"

