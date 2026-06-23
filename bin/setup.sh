#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VENV="$ROOT/python/.venv"
PYTHON_BIN=$(command -v python3)
WIDGETS_DIR="$HOME/Library/Application Support/Übersicht/widgets"
LINK="$WIDGETS_DIR/OptionsSwingTracker.widget"

mkdir -p "$ROOT/cache" "$ROOT/logs" "$WIDGETS_DIR"

if [ ! -f "$ROOT/config.json" ]; then
  if [ ! -f "$ROOT/config.example.json" ]; then
    echo "Setup stopped: missing config.json and config.example.json."
    exit 1
  fi
  cp "$ROOT/config.example.json" "$ROOT/config.json"
fi

"$PYTHON_BIN" - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
config_path = root / "config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
if not isinstance(config, dict):
    raise SystemExit("config.json root must be an object")
runtime = config.setdefault("runtime", {})
if not isinstance(runtime, dict):
    runtime = {}
    config["runtime"] = runtime
runtime["root"] = str(root)
config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$ROOT/python/requirements.txt"

chmod +x "$ROOT/bin/run_widget.sh" "$ROOT/bin/verify_parity.sh" "$ROOT/bin/run_tests.sh" "$ROOT/bin/doctor.sh" "$ROOT/bin/setup.sh" "$ROOT/bin/widget_action.sh"
chmod +x "$ROOT/python/widget_data.py" "$ROOT/python/parity_check.py" "$ROOT/python/widget_action.py"

if [ -L "$LINK" ]; then
  rm "$LINK"
elif [ -e "$LINK" ]; then
  echo "Setup stopped: $LINK already exists and is not a symlink."
  echo "Move or remove that folder, then rerun this script."
  exit 1
fi

ln -s "$ROOT" "$LINK"

echo "Setup complete."
echo "Widget folder: $ROOT"
echo "Übersicht link: $LINK -> $ROOT"
echo "Run: $ROOT/bin/verify_parity.sh"
echo "Tests: $ROOT/bin/run_tests.sh"
