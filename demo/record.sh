#!/bin/bash
# Record VHS demo tapes as GIFs with animated caption overlays.
#
# Pipeline: VHS → raw GIF → captioned GIF (via Pillow) → optimized GIF (gifsicle)
#
# Usage:
#   ./demo/record.sh            # Record all 6 demo tapes
#   ./demo/record.sh jobs       # Record a specific tape by name
#   ./demo/record.sh --no-captions jobs  # Record without captions
#
# Prerequisites:
#   brew install vhs gifsicle
#   uv sync (Pillow dev dependency)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEMO_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

if ! command -v vhs &>/dev/null; then
    echo "Error: vhs is not installed. Install with: brew install vhs"
    exit 1
fi

if ! command -v gifsicle &>/dev/null; then
    echo "Error: gifsicle is not installed. Install with: brew install gifsicle"
    exit 1
fi

# Record a single tape and optionally add captions
record_tape() {
    local tape="$1"
    local name
    name="$(basename "$tape" .tape)"
    local final_gif="$DEMO_DIR/${name}.gif"

    echo "Recording: $name"

    if [ "$ADD_CAPTIONS" = "true" ]; then
        local raw_gif="$DEMO_DIR/${name}-raw.gif"

        # Record to temporary raw file
        local tmp_tape
        tmp_tape="$(mktemp)"
        sed "s|Output \"demo/${name}\.gif\"|Output \"demo/${name}-raw.gif\"|" "$tape" > "$tmp_tape"
        vhs "$tmp_tape"
        rm -f "$tmp_tape"

        # Add captions
        local captions
        captions="$(get_captions "$name")"
        if [ -n "$captions" ] && [ "$captions" != "[]" ]; then
            uv run python "$DEMO_DIR/add_captions.py" "$raw_gif" "$final_gif" "$captions"
        else
            mv "$raw_gif" "$final_gif"
        fi
        rm -f "$raw_gif"
    else
        vhs "$tape"
    fi

    # Optimize: delta compression + reduced palette (TUI has few colors)
    gifsicle -O3 --lossy=30 --colors 64 "$final_gif" -o "$final_gif"
    echo "  Done: demo/${name}.gif ($(du -h "$final_gif" | cut -f1 | xargs))"
}

# Caption definitions per tape (JSON arrays)
# Each caption: {"start": <seconds>, "end": <seconds>, "text": "<description>"}
get_captions() {
    local name="$1"
    case "$name" in
        install)
            cat <<'CAPTIONS'
[{"start":0,"end":5,"text":"Install as a uv tool"},{"start":5.5,"end":12,"text":"Launch stoei \u00b7 loads cluster data automatically"}]
CAPTIONS
            ;;
        jobs)
            cat <<'CAPTIONS'
[{"start":0,"end":1.5,"text":"Jobs Tab \u00b7 your running and pending jobs"},{"start":1.5,"end":4,"text":"Navigate rows \u00b7 j/k or arrow keys"},{"start":4,"end":7,"text":"Sort columns \u00b7 press o"}]
CAPTIONS
            ;;
        nodes)
            cat <<'CAPTIONS'
[{"start":0,"end":1.5,"text":"Nodes Tab \u00b7 press 2"},{"start":1.5,"end":4.5,"text":"Sort by any column \u00b7 press o"}]
CAPTIONS
            ;;
        users)
            cat <<'CAPTIONS'
[{"start":0,"end":2,"text":"Users Tab \u00b7 press 3"},{"start":2,"end":4,"text":"Pending view \u00b7 press p"},{"start":4,"end":6.5,"text":"Energy view \u00b7 press e"}]
CAPTIONS
            ;;
        priority)
            cat <<'CAPTIONS'
[{"start":0,"end":1.5,"text":"Priority Tab \u00b7 press 4"},{"start":1.5,"end":3,"text":"Toggle views \u00b7 u Users  a Accounts  j Jobs"}]
CAPTIONS
            ;;
        filtering)
            cat <<'CAPTIONS'
[{"start":0,"end":1,"text":"Quick Filter \u00b7 press /"},{"start":1,"end":3.5,"text":"Type filter expression \u00b7 e.g. state:RUNNING"},{"start":3.5,"end":5.5,"text":"Clear filter \u00b7 press Escape"}]
CAPTIONS
            ;;
        *)
            echo "[]"
            ;;
    esac
}

# All demo tapes in order
ALL_TAPES=(install jobs nodes users priority filtering)

# Parse flags
ADD_CAPTIONS="true"
TAPES=()

for arg in "$@"; do
    if [ "$arg" = "--no-captions" ]; then
        ADD_CAPTIONS="false"
    else
        TAPES+=("$arg")
    fi
done

# If no tapes specified, record all
if [ ${#TAPES[@]} -eq 0 ]; then
    TAPES=("${ALL_TAPES[@]}")
fi

for name in "${TAPES[@]}"; do
    tape="$DEMO_DIR/${name}.tape"
    [ ! -f "$tape" ] && { echo "Error: $tape not found"; exit 1; }
    record_tape "$tape"
done

echo ""
echo "All recordings complete!"
