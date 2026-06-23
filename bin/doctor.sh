#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PY="$ROOT/python/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Options Swing Tracker doctor"
  echo "FAIL venv: missing $PY"
  echo "Run: $ROOT/bin/setup.sh"
  echo "RESULT FAIL"
  exit 1
fi

PYTHONPATH="$ROOT/python" "$PY" "$ROOT/python/widget_data.py" doctor "$@"
