#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PY="$ROOT/python/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Missing venv python: $PY"
  echo "Run: $ROOT/bin/setup.sh"
  exit 1
fi

if ! "$PY" -m pytest --version >/dev/null 2>&1; then
  "$PY" -m pip install -r "$ROOT/python/requirements.txt"
fi

PYTHONPATH="$ROOT/python" "$PY" -m pytest "$ROOT/python/tests" "$@"
