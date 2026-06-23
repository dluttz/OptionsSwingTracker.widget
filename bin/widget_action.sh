#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PY="$ROOT/python/.venv/bin/python"
ACTION="$ROOT/python/widget_action.py"
ERR="$ROOT/logs/widget.err.log"

mkdir -p "$ROOT/logs" "$ROOT/cache"

if [ ! -x "$PY" ]; then
  printf '{"ok":false,"error":"Python venv missing. Run bin/setup.sh."}\n'
  exit 0
fi

OUT=$("$PY" "$ACTION" "$@" 2>>"$ERR")
STATUS=$?
if [ "$STATUS" -ne 0 ] || [ -z "$OUT" ]; then
  printf '{"ok":false,"error":"Widget action failed. See logs/widget.err.log."}\n'
  exit 0
fi

printf '%s\n' "$OUT"
