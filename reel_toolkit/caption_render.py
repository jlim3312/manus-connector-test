"""Render caption text to a transparent PNG, sized to the output frame.

Why not ffmpeg's drawtext filter? drawtext requires ffmpeg to have been
compiled with libfreetype (`--enable-libfreetype`), and that is *not*
guaranteed -- notably, as of writing, Homebrew's default `ffmpeg` formula
on macOS ships without it, so `brew install ffmpeg` gives you a binary
where drawtext simply doesn't exist ("No such filter: 'drawtext'").
Rendering the text ourselves with Pillow and compositing it with ffmpeg's
`overlay` filter (which every ffmpeg build has) sidesteps that entirely.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import CaptionSpec

# Common bold sans-serif fonts, checked in order, across macOS/Linux/Windows.
# The first one that exists on this machine is used; if none do, Pillow's
# built-in bitmap font is the last resort (readable but not pretty).
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",    # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",                          # Windows
    "C:\\Windows\\Fonts\\arial.ttf",
]

_NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "orange": (255, 165, 0), "gray": (128, 128, 128), "grey": (128, 128, 128),
}


def _find_font(explicit_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    for path in ([explicit_path] if explicit_path else []) + _FONT_CANDIDATES:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def parse_ffmpeg_color(spec: str, default_alpha: int = 255) -> Tuple[int, int, int, int]:
    """Parse ffmpeg-style color strings ('white', 'black@0.55', '#ff8800')
    into an RGBA tuple, since these EditOptions/CaptionSpec fields were
    originally written for ffmpeg's drawtext color syntax.
    """
    if "@" in spec:
        name, alpha_str = spec.split("@", 1)
        try:
            alpha = max(0, min(255, round(float(alpha_str) * 255)))
        except ValueError:
            alpha = default_alpha
    else:
        name, alpha = spec, default_alpha
    name = name.strip().lower()
    if name.startswith("#") and len(name) >= 7:
        r, g, b = int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)
    else:
        r, g, b = _NAMED_COLORS.get(name, (255, 255, 255))
    return (r, g, b, alpha)


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_caption_png(caption: CaptionSpec, width: int, height: int, out_path: str) -> None:
    """Draw `caption` (word-wrapped, on a translucent box) onto a
    width x height transparent RGBA canvas and save it as a PNG at
    out_path. The canvas matches the final video frame size, so ffmpeg
    only needs a plain `overlay=0:0` to composite it -- all positioning
    happens here in Python.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _find_font(caption.font_path, caption.font_size)

    max_text_width = int(width * 0.86)
    lines = _wrap_lines(draw, caption.text, font, max_text_width)

    line_spacing = max(4, caption.font_size // 8)
    line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [b[3] - b[1] for b in line_boxes]
    line_widths = [b[2] - b[0] for b in line_boxes]
    total_text_height = sum(line_heights) + line_spacing * (len(lines) - 1)

    box_padding = 24
    box_width = min(max(line_widths) + box_padding * 2, width - 20)
    box_height = total_text_height + box_padding * 2
    box_x0 = (width - box_width) / 2

    if caption.position == "top":
        box_y0 = caption.margin_px
    else:
        box_y0 = height - caption.margin_px - box_height
    box_y0 = max(0, min(box_y0, height - box_height))

    box_rgba = parse_ffmpeg_color(caption.box_color, default_alpha=140)
    draw.rounded_rectangle(
        [box_x0, box_y0, box_x0 + box_width, box_y0 + box_height],
        radius=16, fill=box_rgba,
    )

    text_rgba = parse_ffmpeg_color(caption.font_color, default_alpha=255)
    y = box_y0 + box_padding
    for line, lh, lw in zip(lines, line_heights, line_widths):
        x = (width - lw) / 2
        draw.text((x, y), line, font=font, fill=text_rgba)
        y += lh + line_spacing

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
