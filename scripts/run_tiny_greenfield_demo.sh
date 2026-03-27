#!/usr/bin/env bash
# Optional: run a *very* small greenfield prompt with real Ollama (not mocked).
# Uses hardware-aware prep reminder; does NOT set SAGE_MODEL_PROFILE=test.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x "$ROOT/.venv/bin/sage" ]; then
  SAGE="$ROOT/.venv/bin/sage"
else
  SAGE="${SAGE_BIN:-sage}"
fi

echo "=== SAGE tiny greenfield demo (real Ollama) ==="
echo "Unset SAGE_MODEL_PROFILE for production-quality routing; for smoke tests only, export SAGE_MODEL_PROFILE=test"
echo ""

$SAGE prep --disk-budget "${DISK_BUDGET:-18}" || true

DEMO="${TMPDIR:-/tmp}/sage-greenfield-demo-$$"
mkdir -p "$DEMO"
cd "$DEMO"

echo "Working in: $DEMO"
$SAGE init
export SAGE_WORKSPACE_ROOT="$(pwd)"
export SAGE_SESSION_ID="${SAGE_SESSION_ID:-demo-$(date +%s)}"

# One minimal task; --auto skips interactive checkpoints
$SAGE run "Create hello.py with def hello(): return 'ok'. Keep it under 20 lines." --auto

echo ""
echo "Done. Inspect: $DEMO"
ls -la "$DEMO" || true
