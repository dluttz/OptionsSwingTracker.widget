#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PY="$ROOT/python/.venv/bin/python"
DATA="$ROOT/python/widget_data.py"
ERR="$ROOT/logs/widget.err.log"

mkdir -p "$ROOT/logs" "$ROOT/cache"

if [ ! -x "$PY" ]; then
  printf '{"generated_at":"","source":"widget","cache_status":"setup_required","rows":[],"summary":{"total":0,"ok":0,"stale":0,"errors":1},"error":"Python venv missing. Run bin/setup.sh."}\n'
  exit 0
fi

OUT=$("$PY" "$DATA" render "$@" 2>>"$ERR")
STATUS=$?

if [ "$STATUS" -ne 0 ] || [ -z "$OUT" ]; then
  printf '{"generated_at":"","source":"widget","cache_status":"command_failed","rows":[],"summary":{"total":0,"ok":0,"stale":0,"errors":1},"error":"Widget command failed. See logs/widget.err.log."}\n'
  exit 0
fi

printf '%s\n' "$OUT"
