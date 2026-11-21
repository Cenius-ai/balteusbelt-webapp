#!/usr/bin/env bash
# BalteusBelt end-to-end demo - non-interactive, offline, exits 0.
set -uo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

banner() {
    printf '\n=== %s ===\n' "$1"
}

banner "Version"
"$PYTHON" balteusbelt.py --version

banner "Built-in catalogue"
"$PYTHON" balteusbelt.py --list-patterns

banner "Default render (oseberg: grid, swaps, dye count)"
"$PYTHON" balteusbelt.py

banner "Grid only (birka, 8 picks, cyclic turn letters)"
"$PYTHON" balteusbelt.py --pattern birka --picks 8 --show grid

banner "Swap schedule only (hedeby: swap beyond --picks is marked, not applied)"
"$PYTHON" balteusbelt.py --pattern hedeby --show swaps

banner "Dye count only (oseberg, 3 picks: one partial round)"
"$PYTHON" balteusbelt.py --show dye --picks 3

banner "Two-round dye count (mammen, 6 picks)"
"$PYTHON" balteusbelt.py --pattern mammen --show dye --picks 6

banner "JSON pattern file"
"$PYTHON" balteusbelt.py --file examples/oseberg.json --show grid

banner "Plain-text pattern file"
"$PYTHON" balteusbelt.py --file examples/birka.txt --show swaps

banner "Error handling: one line on stderr, exit code 2, empty stdout"
"$PYTHON" balteusbelt.py --picks 0
printf 'exit code: %s\n' "$?"
"$PYTHON" balteusbelt.py --pattern nope
printf 'exit code: %s\n' "$?"
"$PYTHON" balteusbelt.py --show bogus
printf 'exit code: %s\n' "$?"

banner "Demo complete"
