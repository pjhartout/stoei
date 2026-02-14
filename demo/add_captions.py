#!/usr/bin/env python3
"""Add timed text captions to animated GIFs.

Usage:
    python demo/add_captions.py <input.gif> <output.gif> '<json_captions>'

The captions JSON is an array of objects with "start", "end", and "text" keys.
Times are in seconds. Example:

    python demo/add_captions.py demo/jobs.gif demo/jobs-captioned.gif \
        '[{"start":0,"end":2,"text":"Jobs Tab"},{"start":2,"end":5,"text":"Navigate · j/k"}]'
"""

from __future__ import annotations

import json
import sys

from PIL import Image, ImageDraw, ImageFont

# Caption bar style
BAR_HEIGHT = 28
BAR_COLOR = (0, 0, 0, 153)  # black @ 60% opacity
TEXT_COLOR = (255, 255, 255, 255)  # white
FONT_SIZE = 14
BAR_Y = 38  # below the window bar


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a monospace font, falling back to default if unavailable."""
    font_paths = [
        "/System/Library/Fonts/SFMono-Regular.otf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.dfont",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def add_captions(
    input_path: str,
    output_path: str,
    captions: list[dict[str, float | str]],
) -> None:
    """Add timed captions to an animated GIF.

    Args:
        input_path: Path to the input GIF.
        output_path: Path to write the captioned GIF.
        captions: List of caption dicts with "start", "end", "text" keys.
    """
    img = Image.open(input_path)
    font = get_font(FONT_SIZE)

    frames: list[Image.Image] = []
    durations: list[int] = []
    elapsed = 0.0

    n_frames = getattr(img, "n_frames", 1)

    for i in range(n_frames):
        img.seek(i)
        frame = img.convert("RGBA")

        # Get frame duration in ms (default 100ms)
        duration = img.info.get("duration", 100)
        durations.append(duration)

        # Find caption for this timestamp
        time_s = elapsed / 1000.0
        caption_text = None
        for cap in captions:
            if cap["start"] <= time_s < cap["end"]:
                caption_text = str(cap["text"])
                break

        if caption_text:
            # Draw semi-transparent bar
            overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            draw.rectangle(
                [(0, BAR_Y), (frame.width, BAR_Y + BAR_HEIGHT)],
                fill=BAR_COLOR,
            )

            # Draw text centered in the bar
            bbox = draw.textbbox((0, 0), caption_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = (frame.width - text_w) // 2
            text_y = BAR_Y + (BAR_HEIGHT - text_h) // 2
            draw.text((text_x, text_y), caption_text, fill=TEXT_COLOR, font=font)

            frame = Image.alpha_composite(frame, overlay)

        # Convert back to palette mode for GIF
        frames.append(frame.convert("P", palette=Image.ADAPTIVE, colors=256))
        elapsed += duration

    # Save
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )
    print(f"  Captioned: {output_path} ({n_frames} frames)")


EXPECTED_ARGC = 4


def main() -> None:
    """Entry point."""
    if len(sys.argv) != EXPECTED_ARGC:
        print(f"Usage: {sys.argv[0]} <input.gif> <output.gif> '<json_captions>'")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    captions = json.loads(sys.argv[3])
    add_captions(input_path, output_path, captions)


if __name__ == "__main__":
    main()
