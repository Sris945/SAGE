#!/usr/bin/env bash
# Bootstrap SAGE: venv + editable install (Linux / macOS).
# Usage: ./startup.sh   OR   bash startup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[SAGE] ERROR: '$PYTHON' not found. Install Python 3.10+ or set PYTHON=/path/to/python3" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "[SAGE] Creating .venv with $PYTHON ..."
  "$PYTHON" -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install -U pip wheel setuptools
python -m pip install -e ".[dev]"

echo ""
echo "[SAGE] OK — virtualenv ready at $ROOT/.venv"
echo "    source .venv/bin/activate"
echo "    sage doctor"
echo "    sage                    # interactive shell"
echo ""
echo "Optional: export SAGE_REPO_URL=https://github.com/your-org/your-fork"
echo "          (so /help and /commands show correct doc links)."
