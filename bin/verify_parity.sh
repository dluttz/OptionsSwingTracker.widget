#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PY="$ROOT/python/.venv/bin/python"

if [ ! -x "$PY" ]; then
  PY=$(command -v python3 || true)
fi

if [ -z "${PY:-}" ]; then
  echo "FAIL"
  exit 1
fi

"$PY" "$ROOT/python/parity_check.py" "$@"
