#!/bin/bash
# Record VHS demo tape(s).
#
# Usage:
#   ./demo/record.sh        # Record demo.tape
#   ./demo/record.sh demo   # Record a specific tape by name
#
# Prerequisites:
#   brew install vhs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEMO_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

if ! command -v vhs &>/dev/null; then
    echo "Error: vhs is not installed. Install with: brew install vhs"
    exit 1
fi

record_tape() {
    local tape="$1"
    local name
    name="$(basename "$tape" .tape)"
    echo "Recording: $name"
    vhs "$tape"
    echo "Done: demo/${name}.gif + demo/${name}.mp4"
}

if [ $# -gt 0 ]; then
    for name in "$@"; do
        tape="$DEMO_DIR/${name}.tape"
        [ ! -f "$tape" ] && { echo "Error: $tape not found"; exit 1; }
        record_tape "$tape"
    done
else
    record_tape "$DEMO_DIR/demo.tape"
fi
