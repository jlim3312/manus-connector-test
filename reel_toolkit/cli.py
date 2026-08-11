"""Command-line interface for reel_toolkit.

    python -m reel_toolkit.cli probe footage.mp4
    python -m reel_toolkit.cli suggest-cuts footage.mp4 --out cuts.json
    python -m reel_toolkit.cli split footage.mp4 cuts.json --out-dir clips/
    python -m reel_toolkit.cli edit clips/01-hook.mp4 --out final/01-reel.mp4 \\
        --caption-top "Watch this dent disappear" --watermark assets/logo.png
    python -m reel_toolkit.cli stitch clips/01.mp4 clips/02.mp4 clips/03.mp4 \\
        --out final/combined-reel.mp4 --transition fade --transition-duration 0.5
    python -m reel_toolkit.cli batch project_config.json
"""
from __future__ import annotations

import argparse
import json
import sys

from . import ffmpeg_utils, pipeline, splitter, stitcher
from .editor import edit_clip
from .models import CaptionSpec, EditOptions, WatermarkSpec, format_timecode


def cmd_probe(args: argparse.Namespace) -> None:
    ffmpeg_utils.require_ffmpeg()
    p = ffmpeg_utils.probe(args.source)
    print(f"duration: {format_timecode(p.duration)} ({p.duration:.2f}s)")
    print(f"resolution: {p.width}x{p.height}")
    print(f"aspect: {'vertical (9:16-ish)' if p.height > p.width else 'horizontal/square'}")
    print(f"has audio: {p.has_audio}")


def cmd_suggest_cuts(args: argparse.Namespace) -> None:
    cuts = splitter.suggest_cuts_from_scenes(
        args.source, threshold=args.threshold, min_length=args.min_length, max_length=args.max_length,
    )
    payload = [{"start": round(c.start, 2), "end": round(c.end, 2), "label": c.label} for c in cuts]
    text = json.dumps(payload, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {len(cuts)} candidate cuts to {args.out}")
        print("Review/trim this list by hand before splitting -- auto scene detection")
        print("over-triggers on camera shake, sparks, and reflections off paint.")
    else:
        print(text)


def cmd_split(args: argparse.Namespace) -> None:
    if args.auto_segment_seconds:
        probe = ffmpeg_utils.probe(args.source)
        cuts = splitter.auto_segments(probe.duration, segment_length=args.auto_segment_seconds)
    else:
        if not args.cuts:
            print("error: pass either a cuts.json file or --auto-segment-seconds", file=sys.stderr)
            sys.exit(2)
        cuts = splitter.load_cut_list(args.cuts)
    clips = splitter.split_video(args.source, cuts, args.out_dir, fast_copy=args.fast)
    for c in clips:
        print(f"{c.path}  ({c.duration:.1f}s)")


def _build_edit_options(args: argparse.Namespace) -> EditOptions:
    captions = []
    if args.caption_top:
        captions.append(CaptionSpec(text=args.caption_top, position="top"))
    if args.caption_bottom:
        captions.append(CaptionSpec(text=args.caption_bottom, position="bottom"))
    watermark = WatermarkSpec(path=args.watermark, position=args.watermark_position) if args.watermark else None
    return EditOptions(
        fit_mode=args.fit_mode,
        max_duration=args.max_duration,
        captions=captions,
        watermark=watermark,
        music_path=args.music,
        music_volume_db=args.music_volume_db,
        normalize_loudness=not args.no_loudness_normalize,
        fade_seconds=args.fade_seconds,
        auto_enhance=args.auto_enhance,
        saturation=args.saturation,
        contrast=args.contrast,
        brightness=args.brightness,
        color_temperature=args.warmth,
    )


def _add_color_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auto-enhance", action="store_true",
                         help="analyze the footage and auto-correct color/levels -- no numbers needed")
    parser.add_argument("--saturation", type=float, default=1.0, help="1.0=unchanged, 0=grayscale, >1=more vivid")
    parser.add_argument("--contrast", type=float, default=1.0, help="1.0=unchanged")
    parser.add_argument("--brightness", type=float, default=0.0, help="-1.0..1.0, 0=unchanged")
    parser.add_argument("--warmth", type=int, default=None, metavar="KELVIN",
                         help="color temperature, e.g. 4500=warmer, 8500=cooler (omit for unchanged)")


def cmd_edit(args: argparse.Namespace) -> None:
    opts = _build_edit_options(args)
    clip = edit_clip(args.source, args.out, opts)
    print(f"wrote {clip.path} ({clip.duration:.1f}s)")


def cmd_stitch(args: argparse.Namespace) -> None:
    import tempfile
    opts = _build_edit_options(args)
    with tempfile.TemporaryDirectory(prefix="reel_toolkit_stitch_") as tmp_dir:
        stitched_path = f"{tmp_dir}/stitched.mp4"
        clip = stitcher.stitch_and_polish(
            args.clips, stitched_path, args.out, opts,
            transition=args.transition, transition_duration=args.transition_duration,
        )
    print(f"wrote {clip.path} ({clip.duration:.1f}s, {len(args.clips)} clips joined with '{args.transition}')")


def cmd_batch(args: argparse.Namespace) -> None:
    manifest = pipeline.run_project(args.config)
    print(f"processed {len(manifest['clips'])} clip(s) into {manifest['output_dir']}")
    for entry in manifest["clips"]:
        print(f"  {entry['label']}: {entry['final_clip']} ({entry['duration_seconds']}s)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reel_toolkit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="print duration/resolution/audio info for a video")
    p_probe.add_argument("source")
    p_probe.set_defaults(func=cmd_probe)

    p_sc = sub.add_parser("suggest-cuts", help="auto-detect candidate cut points via scene detection")
    p_sc.add_argument("source")
    p_sc.add_argument("--threshold", type=float, default=0.4, help="scene-change sensitivity, 0-1 (default 0.4)")
    p_sc.add_argument("--min-length", type=float, default=3.0)
    p_sc.add_argument("--max-length", type=float, default=90.0)
    p_sc.add_argument("--out", help="write candidate cuts as JSON to this path (default: print to stdout)")
    p_sc.set_defaults(func=cmd_suggest_cuts)

    p_split = sub.add_parser("split", help="cut a source video into clips")
    p_split.add_argument("source")
    p_split.add_argument("cuts", nargs="?", help="path to a cuts.json list (omit if using --auto-segment-seconds)")
    p_split.add_argument("--out-dir", required=True)
    p_split.add_argument("--auto-segment-seconds", type=float, default=None,
                          help="instead of a cuts.json, split into equal segments of this length")
    p_split.add_argument("--fast", action="store_true", help="stream-copy cut (instant, keyframe-snapped preview)")
    p_split.set_defaults(func=cmd_split)

    p_edit = sub.add_parser("edit", help="make one clip Reels-ready (crop, captions, watermark, music)")
    p_edit.add_argument("source")
    p_edit.add_argument("--out", required=True)
    p_edit.add_argument("--fit-mode", choices=["crop", "pad"], default="crop")
    p_edit.add_argument("--max-duration", type=float, default=90.0)
    p_edit.add_argument("--caption-top", default=None)
    p_edit.add_argument("--caption-bottom", default=None)
    p_edit.add_argument("--watermark", default=None, help="path to a logo PNG (transparent background recommended)")
    p_edit.add_argument("--watermark-position", default="bottom_right",
                         choices=["top_left", "top_right", "bottom_left", "bottom_right", "center"])
    p_edit.add_argument("--music", default=None, help="path to a background music track to mix in quietly")
    p_edit.add_argument("--music-volume-db", type=float, default=-18.0)
    p_edit.add_argument("--no-loudness-normalize", action="store_true")
    p_edit.add_argument("--fade-seconds", type=float, default=0.4)
    _add_color_args(p_edit)
    p_edit.set_defaults(func=cmd_edit)

    p_stitch = sub.add_parser(
        "stitch",
        help="combine 2+ clips into one Reel with a transition at each cut (e.g. before -> process -> after)",
    )
    p_stitch.add_argument("clips", nargs="+", help="2 or more clip files, in order")
    p_stitch.add_argument("--out", required=True)
    p_stitch.add_argument("--transition", default=stitcher.DEFAULT_TRANSITION,
                           help=f"ffmpeg xfade transition name, e.g. {', '.join(stitcher.COMMON_TRANSITIONS)}")
    p_stitch.add_argument("--transition-duration", type=float, default=0.5)
    p_stitch.add_argument("--fit-mode", choices=["crop", "pad"], default="crop")
    p_stitch.add_argument("--max-duration", type=float, default=90.0)
    p_stitch.add_argument("--caption-top", default=None)
    p_stitch.add_argument("--caption-bottom", default=None)
    p_stitch.add_argument("--watermark", default=None, help="path to a logo PNG (transparent background recommended)")
    p_stitch.add_argument("--watermark-position", default="bottom_right",
                           choices=["top_left", "top_right", "bottom_left", "bottom_right", "center"])
    p_stitch.add_argument("--music", default=None, help="path to a background music track to mix in quietly")
    p_stitch.add_argument("--music-volume-db", type=float, default=-18.0)
    p_stitch.add_argument("--no-loudness-normalize", action="store_true")
    p_stitch.add_argument("--fade-seconds", type=float, default=0.4)
    _add_color_args(p_stitch)
    p_stitch.set_defaults(func=cmd_stitch)

    p_batch = sub.add_parser("batch", help="run split+edit end-to-end from a project config JSON")
    p_batch.add_argument("config")
    p_batch.set_defaults(func=cmd_batch)

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ffmpeg_utils.FfmpegNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except ffmpeg_utils.FfmpegError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
