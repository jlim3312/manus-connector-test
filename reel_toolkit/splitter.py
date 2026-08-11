"""Cut a raw source video into Reels-length clips."""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from . import ffmpeg_utils
from .models import (
    Clip,
    CutSpec,
    REELS_MAX_SECONDS,
    REELS_MIN_SECONDS,
    parse_timecode,
)


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "clip"


def load_cut_list(json_path: str) -> List[CutSpec]:
    """Load an explicit list of cuts from a JSON file:

        [
          {"start": "00:12", "end": "00:41", "label": "hook-and-teardown"},
          {"start": 95, "end": 130, "label": "primer-coat"}
        ]
    """
    with open(json_path, "r") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("cut list JSON must be a top-level array of {start, end, label} objects")
    return [CutSpec.from_dict(item) for item in raw]


def auto_segments(
    duration: float,
    segment_length: float = 45.0,
    max_length: float = REELS_MAX_SECONDS,
    min_length: float = REELS_MIN_SECONDS,
    label_prefix: str = "segment",
) -> List[CutSpec]:
    """Split `duration` seconds into equal-ish segments, e.g. for turning an
    unedited long recording into a handful of candidate reels without
    picking timestamps by hand. The last segment is dropped if it would be
    shorter than `min_length` (merged into the previous one instead).
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    segment_length = min(segment_length, max_length)
    if segment_length < min_length:
        raise ValueError("segment_length must be >= min_length")

    cuts: List[CutSpec] = []
    start = 0.0
    index = 1
    while start < duration:
        end = min(start + segment_length, duration)
        remaining_after = duration - end
        # If what's left after this cut is too short to stand alone, fold it
        # into the current segment instead of emitting a tiny trailing clip.
        if 0 < remaining_after < min_length:
            end = duration
        end = min(end, start + max_length)
        cuts.append(CutSpec(start=start, end=end, label=f"{label_prefix}-{index}"))
        start = end
        index += 1
    return cuts


def suggest_cuts_from_scenes(
    source_path: str,
    threshold: float = 0.4,
    min_length: float = REELS_MIN_SECONDS,
    max_length: float = REELS_MAX_SECONDS,
    label_prefix: str = "scene",
) -> List[CutSpec]:
    """Detect scene changes and turn them into candidate CutSpecs. This is a
    *starting point* for review, not a final cut list -- handheld shop
    footage triggers false positives on camera shake, sparks, reflections
    off paint, etc. Always preview before batch-editing.
    """
    ffmpeg_utils.require_ffmpeg()
    probe = ffmpeg_utils.probe(source_path)
    boundaries = [0.0] + sorted(set(ffmpeg_utils.detect_scene_changes(source_path, threshold))) + [probe.duration]
    cuts: List[CutSpec] = []
    index = 1
    i = 0
    while i < len(boundaries) - 1:
        start = boundaries[i]
        end = boundaries[i + 1]
        # merge forward while segment is under min_length
        j = i + 1
        while (end - start) < min_length and j < len(boundaries) - 1:
            j += 1
            end = boundaries[j]
        end = min(end, start + max_length)
        if end - start >= min_length:
            cuts.append(CutSpec(start=start, end=end, label=f"{label_prefix}-{index}"))
            index += 1
        i = j
    return cuts


def split_video(
    source_path: str,
    cuts: List[CutSpec],
    out_dir: str,
    fast_copy: bool = False,
    filename_prefix: Optional[str] = None,
) -> List[Clip]:
    """Cut `source_path` into one file per CutSpec, written to out_dir.

    fast_copy=True is good for quickly previewing candidate cuts; leave it
    False (the default) for the final pass so cut points land on the exact
    frame instead of the nearest keyframe.
    """
    ffmpeg_utils.require_ffmpeg()
    os.makedirs(out_dir, exist_ok=True)
    prefix = f"{filename_prefix}-" if filename_prefix else ""
    clips: List[Clip] = []
    for i, cut in enumerate(cuts, start=1):
        label = cut.label or f"clip-{i}"
        filename = f"{prefix}{i:02d}-{_slugify(label)}.mp4"
        out_path = os.path.join(out_dir, filename)
        ffmpeg_utils.trim(source_path, out_path, cut.start, cut.end, fast_copy=fast_copy)
        clips.append(Clip(path=out_path, label=label, duration=cut.duration, source=source_path))
    return clips
