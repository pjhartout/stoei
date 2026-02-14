#!/bin/bash
# Record VHS demo tapes and add animated captions with ffmpeg.
#
# Pipeline: VHS → raw MP4 → captioned MP4 → GIF (two-pass palette)
#
# Usage:
#   ./demo/record.sh            # Record all 6 demo tapes
#   ./demo/record.sh jobs       # Record a specific tape by name
#   ./demo/record.sh --no-captions jobs  # Record without captions
#
# Prerequisites:
#   brew install vhs ffmpeg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEMO_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

if ! command -v vhs &>/dev/null; then
    echo "Error: vhs is not installed. Install with: brew install vhs"
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "Error: ffmpeg is not installed. Install with: brew install ffmpeg"
    exit 1
fi

# Caption style constants
FONT_SIZE=20
FONT_COLOR="white"
BOX_COLOR="black@0.6"
BOX_BORDER=8

# Build a drawtext filter for a single timed caption
# Args: $1=start_time $2=end_time $3=text
caption_filter() {
    local start="$1" end="$2" text="$3"
    echo "drawtext=text='${text}':fontsize=${FONT_SIZE}:fontcolor=${FONT_COLOR}:box=1:boxcolor=${BOX_COLOR}:boxborderw=${BOX_BORDER}:x=(w-text_w)/2:y=16:enable='between(t,${start},${end})'"
}

# Convert MP4 to GIF using two-pass palette for quality
# Args: $1=input_mp4 $2=output_gif
mp4_to_gif() {
    local input="$1" output="$2"
    local palette
    palette="$(mktemp /tmp/palette-XXXXXX.png)"

    # Pass 1: generate optimal palette
    ffmpeg -y -i "$input" -vf "fps=15,scale=-1:-1:flags=lanczos,palettegen=stats_mode=diff" "$palette" 2>/dev/null

    # Pass 2: encode GIF with palette
    ffmpeg -y -i "$input" -i "$palette" -lavfi "fps=15,scale=-1:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5" "$output" 2>/dev/null

    rm -f "$palette"
}

# Record a single tape, add captions, and produce GIF
record_tape() {
    local tape="$1"
    local name
    name="$(basename "$tape" .tape)"
    local raw_mp4="$DEMO_DIR/${name}-raw.mp4"
    local captioned_mp4="$DEMO_DIR/${name}.mp4"
    local final_gif="$DEMO_DIR/${name}.gif"

    echo "Recording: $name"

    # Temporarily change the tape output to the raw file
    local tmp_tape
    tmp_tape="$(mktemp)"
    sed "s|Output \"demo/${name}\.mp4\"|Output \"demo/${name}-raw.mp4\"|" "$tape" > "$tmp_tape"

    vhs "$tmp_tape"
    rm -f "$tmp_tape"

    # Add captions to MP4
    if [ "$ADD_CAPTIONS" = "true" ]; then
        local filters
        filters="$(get_captions "$name")"
        if [ -n "$filters" ]; then
            echo "  Adding captions..."
            ffmpeg -y -i "$raw_mp4" -vf "$filters" -c:v libx264 -preset fast -crf 18 -an "$captioned_mp4" 2>/dev/null
        else
            cp "$raw_mp4" "$captioned_mp4"
        fi
    else
        cp "$raw_mp4" "$captioned_mp4"
    fi

    # Convert to GIF
    echo "  Converting to GIF..."
    mp4_to_gif "$captioned_mp4" "$final_gif"

    # Clean up intermediate files
    rm -f "$raw_mp4" "$captioned_mp4"

    echo "  Done: demo/${name}.gif"
}

# Map tape names to their caption filters
# Durations are based on the playback speed (1.5x) — real time is shorter
get_captions() {
    local name="$1"
    case "$name" in
        install)
            local c1 c2
            c1="$(caption_filter 0 4 'Install as a uv tool')"
            c2="$(caption_filter 4 9 'Launch stoei \· loads cluster data automatically')"
            echo "${c1},${c2}"
            ;;
        jobs)
            local c1 c2 c3
            c1="$(caption_filter 0 1.5 'Jobs Tab \· your running and pending jobs')"
            c2="$(caption_filter 1.5 4 'Navigate rows \· j/k or arrow keys')"
            c3="$(caption_filter 4 7 'Sort columns \· press o')"
            echo "${c1},${c2},${c3}"
            ;;
        nodes)
            local c1 c2
            c1="$(caption_filter 0 1.5 'Nodes Tab \· press 2')"
            c2="$(caption_filter 1.5 4 'Sort by any column \· press o')"
            echo "${c1},${c2}"
            ;;
        users)
            local c1 c2
            c1="$(caption_filter 0 1.5 'Users Tab \· press 3')"
            c2="$(caption_filter 1.5 5 'Toggle views \· r Running  p Pending  e Energy')"
            echo "${c1},${c2}"
            ;;
        priority)
            local c1 c2
            c1="$(caption_filter 0 1.5 'Priority Tab \· press 4')"
            c2="$(caption_filter 1.5 5 'Toggle views \· u Users  a Accounts  j Jobs')"
            echo "${c1},${c2}"
            ;;
        filtering)
            local c1 c2 c3
            c1="$(caption_filter 0 1 'Quick Filter \· press /')"
            c2="$(caption_filter 1 3.5 'Type filter expression \· e.g. state:RUNNING')"
            c3="$(caption_filter 3.5 6 'Clear filter \· press Escape')"
            echo "${c1},${c2},${c3}"
            ;;
        *)
            echo ""
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
