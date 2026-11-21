#!/usr/bin/env bash
# BalteusBelt setup: installs the development dependency (pytest), then EXITS.
# The tool itself needs no third-party packages, no database and no seed step.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON not found; install Python 3.8 or newer first" >&2
    exit 1
fi

echo "==> Upgrading pip, setuptools and wheel"
"$PYTHON" -m pip install --upgrade pip setuptools wheel

echo "==> Installing the test runner from requirements.txt"
"$PYTHON" -m pip install -r requirements.txt

echo "==> Checking that balteusbelt.py imports and runs"
"$PYTHON" -c "import balteusbelt"
"$PYTHON" balteusbelt.py --list-patterns >/dev/null

echo "Setup complete."
echo "Run the tool:  python3 balteusbelt.py --help"
echo "Run the demo:  bash demo.sh"
echo "Run the tests: python3 -m pytest"
