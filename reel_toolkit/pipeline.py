"""Run split + edit end-to-end from a single JSON project config.

Example config: see reel_toolkit/examples/project_config.json
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from . import ffmpeg_utils, splitter
from .editor import edit_clip
from .models import CaptionSpec, Clip, CutSpec, EditOptions, WatermarkSpec


def _edit_options_from_dict(d: Dict[str, Any]) -> EditOptions:
    d = dict(d)  # don't mutate caller's dict
    captions = [CaptionSpec(**c) for c in d.pop("captions", [])]
    watermark_raw = d.pop("watermark", None)
    watermark = WatermarkSpec(**watermark_raw) if watermark_raw else None
    return EditOptions(captions=captions, watermark=watermark, **d)


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def run_project(config_path: str, work_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run the full pipeline described by a project config JSON file:

        {
          "source": "raw/shop_visit_08_11.mp4",
          "output_dir": "out/2026-08-11",
          "cuts": [ {"start": "00:05", "end": "00:52", "label": "hook-teardown"} ],
          // -- OR, instead of "cuts": --
          "auto_segment_seconds": 45,

          "edit": {                 // global defaults applied to every clip
            "fit_mode": "crop",
            "max_duration": 60,
            "watermark": {"path": "assets/logo.png", "position": "bottom_right"},
            "captions": [{"text": "BEFORE -> AFTER", "position": "top"}]
          },
          "clip_overrides": {        // optional, keyed by cut label
            "hook-teardown": {"captions": [{"text": "Watch this dent disappear", "position": "top"}]}
          }
        }

    Returns a manifest dict (also written to <output_dir>/manifest.json).
    """
    ffmpeg_utils.require_ffmpeg()
    config = load_config(config_path)
    source = config["source"]
    output_dir = config.get("output_dir", "reel_toolkit_out")
    os.makedirs(output_dir, exist_ok=True)

    raw_dir = os.path.join(output_dir, "_raw_cuts")
    final_dir = os.path.join(output_dir, "final")

    if "cuts" in config:
        cuts: List[CutSpec] = [CutSpec.from_dict(c) for c in config["cuts"]]
    elif "auto_segment_seconds" in config:
        probe = ffmpeg_utils.probe(source)
        cuts = splitter.auto_segments(probe.duration, segment_length=config["auto_segment_seconds"])
    else:
        raise ValueError("project config must have either 'cuts' or 'auto_segment_seconds'")

    raw_clips = splitter.split_video(source, cuts, raw_dir, fast_copy=False)

    global_edit = config.get("edit", {})
    overrides = config.get("clip_overrides", {})

    manifest_entries = []
    os.makedirs(final_dir, exist_ok=True)
    for clip, cut in zip(raw_clips, cuts):
        merged = dict(global_edit)
        merged.update(overrides.get(cut.label, {}))
        opts = _edit_options_from_dict(merged)
        out_name = os.path.splitext(os.path.basename(clip.path))[0] + "-reel.mp4"
        out_path = os.path.join(final_dir, out_name)
        final_clip = edit_clip(clip.path, out_path, opts)
        manifest_entries.append({
            "label": cut.label,
            "source_cut": {"start": cut.start, "end": cut.end},
            "raw_clip": clip.path,
            "final_clip": final_clip.path,
            "duration_seconds": round(final_clip.duration, 2),
        })

    manifest = {"source": source, "output_dir": output_dir, "clips": manifest_entries}
    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest
