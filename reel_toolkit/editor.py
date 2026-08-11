"""Turn a cut clip into a publish-ready vertical Reel.

Applies, in order: crop/pad to 9:16, fade in/out, caption text burn-in,
logo watermark, loudness normalization, and an optional background music
mix -- then clamps to Instagram's Reels duration window.
"""
from __future__ import annotations

import os
from typing import List, Optional

from . import ffmpeg_utils
from .models import CaptionSpec, Clip, EditOptions, WatermarkSpec


def _escape_drawtext(text: str) -> str:
    # ffmpeg drawtext treats : and \ and ' and % specially inside the filter string.
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", r"\'")
    text = text.replace("%", "\\%")
    return text


def _scale_crop_filter(target_w: int, target_h: int) -> str:
    """Fill the target 9:16 frame, cropping any overflow (default -- looks
    intentional for social, unlike letterboxing).
    """
    return (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}"
    )


def _scale_pad_filter(target_w: int, target_h: int) -> str:
    """Fit the whole source frame inside 9:16 with a blurred, scaled-up copy
    of itself filling the bars -- use when you can't afford to crop any of
    the shot (e.g. a wide two-person interview) but still want the frame
    full instead of black bars.
    """
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},gblur=sigma=20[bg];"
        f"[fg]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def _caption_filter(caption: CaptionSpec) -> str:
    y = f"{caption.margin_px}" if caption.position == "top" else f"h-text_h-{caption.margin_px}"
    font_arg = f"fontfile='{caption.font_path}':" if caption.font_path else ""
    text = _escape_drawtext(caption.text)
    return (
        f"drawtext={font_arg}text='{text}':fontcolor={caption.font_color}:"
        f"fontsize={caption.font_size}:box=1:boxcolor={caption.box_color}:"
        f"boxborderw=20:x=(w-text_w)/2:y={y}:line_spacing=6"
    )


_POSITION_EXPR = {
    "top_left": "{margin}:{margin}",
    "top_right": "W-w-{margin}:{margin}",
    "bottom_left": "{margin}:H-h-{margin}",
    "bottom_right": "W-w-{margin}:H-h-{margin}",
    "center": "(W-w)/2:(H-h)/2",
}


def _video_chain(opts: EditOptions, clip_duration: Optional[float]) -> List[str]:
    """The ordered list of video filters, before any watermark overlay."""
    chain = [_scale_crop_filter(opts.target_width, opts.target_height)
             if opts.fit_mode == "crop"
             else _scale_pad_filter(opts.target_width, opts.target_height)]

    if opts.fade_seconds > 0:
        chain.append(f"fade=t=in:st=0:d={opts.fade_seconds}")
        if clip_duration:
            effective_duration = min(clip_duration, opts.max_duration) if opts.max_duration else clip_duration
            out_start = max(0.0, effective_duration - opts.fade_seconds)
            chain.append(f"fade=t=out:st={out_start:.3f}:d={opts.fade_seconds}")

    for caption in opts.captions:
        chain.append(_caption_filter(caption))

    return chain


def build_filter_graph(opts: EditOptions, clip_duration: Optional[float] = None) -> tuple:
    """Return (graph: str, uses_filter_complex: bool, extra_video_inputs: List[str]).

    Pure string-building, no subprocess -- unit-testable without ffmpeg
    installed. `clip_duration`, if known, lets the fade-out land at the
    right timestamp instead of always assuming full clip length.
    """
    video_chain_parts = _video_chain(opts, clip_duration)

    if opts.watermark is None:
        return ",".join(video_chain_parts), False, []

    # Watermark needs filter_complex because it's a second input overlaid
    # on top of the main chain.
    wm = opts.watermark
    pos = _POSITION_EXPR[wm.position].format(margin=wm.margin_px)
    wm_chain = []
    if wm.scale_width_px:
        wm_chain.append(f"scale={wm.scale_width_px}:-1")
    if wm.opacity < 1.0:
        wm_chain.append(f"format=rgba,colorchannelmixer=aa={wm.opacity}")
    wm_filter = ",".join(wm_chain) if wm_chain else "null"

    main_chain = ",".join(video_chain_parts)
    filter_complex = (
        f"[0:v]{main_chain}[base];"
        f"[1:v]{wm_filter}[wm];"
        f"[base][wm]overlay={pos}[vout]"
    )
    return filter_complex, True, [wm.path]


def build_edit_cmd(
    input_path: str,
    output_path: str,
    opts: EditOptions,
    clip_duration: Optional[float] = None,
) -> List[str]:
    """Build the full ffmpeg command for one edit pass."""
    graph, uses_filter_complex, extra_inputs = build_filter_graph(opts, clip_duration)

    cmd = ["ffmpeg", "-y", "-i", input_path]
    for extra in extra_inputs:
        cmd += ["-i", extra]

    music_input_idx = None
    if opts.music_path:
        music_input_idx = 1 + len(extra_inputs)
        cmd += ["-i", opts.music_path]

    filter_complex_pieces = [graph] if uses_filter_complex else []
    video_map = "[vout]" if uses_filter_complex else None

    if opts.music_path:
        orig_audio_label = "[0:a]"
        if opts.duck_original_audio_db:
            filter_complex_pieces.append(f"[0:a]volume={opts.duck_original_audio_db}dB[a0]")
            orig_audio_label = "[a0]"
        filter_complex_pieces.append(f"[{music_input_idx}:a]volume={opts.music_volume_db}dB[am]")
        filter_complex_pieces.append(
            f"{orig_audio_label}[am]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = "0:a?"

    if filter_complex_pieces:
        cmd += ["-filter_complex", ";".join(filter_complex_pieces)]
        cmd += ["-map", video_map or "0:v"]
        cmd += ["-map", audio_map]
    else:
        # simple case: single -vf, default audio stream mapping
        cmd += ["-vf", graph]
        cmd += ["-map", "0:v", "-map", "0:a?"]

    if opts.normalize_loudness:
        cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]

    if opts.max_duration:
        cmd += ["-t", f"{opts.max_duration:.3f}"]

    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(opts.crf), "-pix_fmt", "yuv420p"]
    if opts.video_bitrate:
        cmd += ["-b:v", opts.video_bitrate]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    cmd.append(output_path)
    return cmd


def edit_clip(input_path: str, output_path: str, opts: EditOptions) -> Clip:
    ffmpeg_utils.require_ffmpeg()
    probe = ffmpeg_utils.probe(input_path)
    duration = probe.duration
    if opts.max_duration:
        duration = min(duration, opts.max_duration)
    cmd = build_edit_cmd(input_path, output_path, opts, clip_duration=probe.duration)
    ffmpeg_utils.run(cmd)
    return Clip(path=output_path, label=os.path.basename(output_path), duration=duration, source=input_path)
