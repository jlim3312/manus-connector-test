"""Combine multiple clips into one continuous Reel with a transition
between each segment, instead of publishing them as separate files --
e.g. a single before -> process -> after video with a crossfade at each
cut, using ffmpeg's `xfade` (video) and `acrossfade` (audio) filters.

Both filters are built into every standard ffmpeg binary (no compile
flags needed, unlike drawtext).
"""
from __future__ import annotations

import dataclasses
from typing import List

from . import ffmpeg_utils
from .editor import _scale_crop_filter, _scale_pad_filter, color_filters, edit_clip
from .models import Clip, EditOptions

# A representative, visually-distinct subset of ffmpeg's ~50 xfade transition
# names -- enough variety for a CLI/web UI dropdown without overwhelming it.
# Pass any other valid xfade transition name straight through if you want it.
COMMON_TRANSITIONS = [
    "fade", "fadeblack", "fadewhite", "dissolve",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "circleopen", "circleclose", "smoothleft", "smoothright",
]
DEFAULT_TRANSITION = "fade"


def _grade_and_crop_filter(opts: EditOptions) -> str:
    """Per-segment filter chain used before stitching: scale/crop-or-pad to
    the target frame plus color grading -- everything *except* fades and
    overlays, which belong on the combined result, not each segment.
    """
    base = (_scale_crop_filter(opts.target_width, opts.target_height) if opts.fit_mode == "crop"
            else _scale_pad_filter(opts.target_width, opts.target_height))
    parts = [base] + color_filters(opts)
    # settb/fps normalize timebase and frame rate across clips that may have
    # been recorded/encoded slightly differently -- xfade is picky about this.
    parts += ["settb=AVTB", "fps=30"]
    return ",".join(parts)


def build_stitch_cmd(
    clip_paths: List[str],
    durations: List[float],
    output_path: str,
    opts: EditOptions,
    transition: str = DEFAULT_TRANSITION,
    transition_duration: float = 0.5,
) -> List[str]:
    """Build the ffmpeg command that grades/crops each clip and chains them
    together with `transition` at each cut. Pure string-building, no
    subprocess -- unit-testable without ffmpeg or real files.
    """
    if len(clip_paths) < 2:
        raise ValueError("stitching needs at least 2 clips")
    if len(clip_paths) != len(durations):
        raise ValueError("clip_paths and durations must be the same length")
    if transition_duration <= 0:
        raise ValueError("transition_duration must be > 0")
    for d in durations:
        if d <= transition_duration:
            raise ValueError(
                f"every clip must be longer than the transition duration ({transition_duration}s), "
                f"got a {d}s clip"
            )

    grade = _grade_and_crop_filter(opts)
    cmd = ["ffmpeg", "-y"]
    for path in clip_paths:
        cmd += ["-i", path]

    filter_parts = [f"[{i}:v]{grade}[v{i}]" for i in range(len(clip_paths))]

    cumulative = durations[0]
    current_v = "v0"
    for i in range(1, len(clip_paths)):
        offset = cumulative - transition_duration
        out_v = f"v{i}x"
        filter_parts.append(
            f"[{current_v}][v{i}]xfade=transition={transition}:duration={transition_duration}:"
            f"offset={offset:.3f}[{out_v}]"
        )
        current_v = out_v
        cumulative += durations[i] - transition_duration

    current_a = "0:a"
    for i in range(1, len(clip_paths)):
        out_a = f"a{i}x"
        filter_parts.append(f"[{current_a}][{i}:a]acrossfade=d={transition_duration}[{out_a}]")
        current_a = out_a

    cmd += ["-filter_complex", ";".join(filter_parts)]
    cmd += ["-map", f"[{current_v}]", "-map", f"[{current_a}]"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(opts.crf), "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    cmd.append(output_path)
    return cmd


def stitched_duration(durations: List[float], transition_duration: float) -> float:
    """Total length of the combined video -- each transition overlaps (and
    so shortens) the total by transition_duration."""
    return sum(durations) - transition_duration * (len(durations) - 1)


def stitch_clips(
    clip_paths: List[str],
    output_path: str,
    opts: EditOptions,
    transition: str = DEFAULT_TRANSITION,
    transition_duration: float = 0.5,
) -> Clip:
    """Grade/crop and combine clip_paths into one video at output_path with
    a `transition` crossfade at each cut. Captions/watermark/music/final
    fade are NOT applied here -- run the result through editor.edit_clip
    (with color fields neutralized, see polish_options_after_stitch) for
    that, so those effects apply once to the whole combined video instead
    of per segment.
    """
    ffmpeg_utils.require_ffmpeg()
    durations = [ffmpeg_utils.probe(p).duration for p in clip_paths]
    cmd = build_stitch_cmd(clip_paths, durations, output_path, opts, transition, transition_duration)
    ffmpeg_utils.run(cmd)
    return Clip(path=output_path, label="stitched", duration=stitched_duration(durations, transition_duration))


def polish_options_after_stitch(opts: EditOptions) -> EditOptions:
    """A copy of opts with color grading neutralized -- use this for the
    edit_clip() polish pass on an already-stitched video, since color
    grading was already applied once per segment during stitching and
    would otherwise be double-applied.
    """
    return dataclasses.replace(
        opts, auto_enhance=False, saturation=1.0, contrast=1.0, brightness=0.0, color_temperature=None,
    )


def stitch_and_polish(clip_paths: List[str], stitched_path: str, final_path: str, opts: EditOptions,
                       transition: str = DEFAULT_TRANSITION, transition_duration: float = 0.5) -> Clip:
    """Convenience wrapper: stitch clip_paths with transitions, then run
    the normal caption/watermark/music/loudnorm/fade edit pass over the
    combined result. This is what CLI `stitch` and the web UI's "combine
    with transitions" option both call.
    """
    stitch_clips(clip_paths, stitched_path, opts, transition, transition_duration)
    return edit_clip(stitched_path, final_path, polish_options_after_stitch(opts))
