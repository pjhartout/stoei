#!/bin/bash
# Record VHS demo tapes as GIFs.
#
# Usage:
#   ./demo/record.sh            # Record all 6 demo tapes
#   ./demo/record.sh jobs       # Record a specific tape by name
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
    echo "  Done: demo/${name}.gif"
}

# All demo tapes in order
ALL_TAPES=(install jobs nodes users priority filtering)

if [ $# -gt 0 ]; then
    TAPES=("$@")
else
    TAPES=("${ALL_TAPES[@]}")
fi

for name in "${TAPES[@]}"; do
    tape="$DEMO_DIR/${name}.tape"
    [ ! -f "$tape" ] && { echo "Error: $tape not found"; exit 1; }
    record_tape "$tape"
done

echo ""
echo "All recordings complete!"
