"""Tests for reel_toolkit. Everything here avoids needing the real ffmpeg
binary: subprocess boundaries (ffmpeg_utils.run/probe/detect_scene_changes,
splitter.split_video's call to ffmpeg_utils.trim, editor.edit_clip's call to
ffmpeg_utils.probe/run) are monkeypatched, and the rest is pure logic /
string-building that's tested directly.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from reel_toolkit import ffmpeg_utils, splitter
from reel_toolkit.editor import build_edit_cmd, build_filter_graph
from reel_toolkit.models import (
    CaptionSpec,
    CutSpec,
    EditOptions,
    WatermarkSpec,
    format_timecode,
    parse_timecode,
)
from reel_toolkit.pipeline import _edit_options_from_dict, run_project


# ---------------------------------------------------------------- models --

def test_parse_timecode_variants():
    assert parse_timecode(12.5) == 12.5
    assert parse_timecode("12") == 12.0
    assert parse_timecode("01:30") == 90.0
    assert parse_timecode("00:01:30.5") == 90.5
    assert parse_timecode("1:02:03") == 3723.0


def test_parse_timecode_rejects_garbage():
    with pytest.raises(ValueError):
        parse_timecode("1:2:3:4")
    with pytest.raises(TypeError):
        parse_timecode(None)


def test_format_timecode_roundish():
    assert format_timecode(90.0) == "01:30.000"
    assert format_timecode(3723.0).startswith("01:02:03")


def test_cutspec_rejects_backwards_range():
    with pytest.raises(ValueError):
        CutSpec(start=10, end=5, label="oops")


def test_cutspec_duration():
    c = CutSpec(start=10, end=25, label="x")
    assert c.duration == 15


def test_watermark_spec_validates_position_and_opacity():
    with pytest.raises(ValueError):
        WatermarkSpec(path="logo.png", position="middle-ish")
    with pytest.raises(ValueError):
        WatermarkSpec(path="logo.png", opacity=1.5)


def test_caption_spec_validates_position():
    with pytest.raises(ValueError):
        CaptionSpec(text="hi", position="left")


def test_edit_options_validates_fit_mode():
    with pytest.raises(ValueError):
        EditOptions(fit_mode="stretch")


# -------------------------------------------------------------- splitter --

def test_auto_segments_covers_full_duration_without_gaps():
    cuts = splitter.auto_segments(100, segment_length=30, min_length=5)
    assert cuts[0].start == 0
    assert cuts[-1].end == 100
    for a, b in zip(cuts, cuts[1:]):
        assert a.end == b.start  # no gaps, no overlap


def test_auto_segments_folds_short_tail_into_previous():
    # 100s at 45s segments -> naive split gives 45/45/10; the trailing 10s
    # is below min_length=15 so it should be folded into the prior segment.
    cuts = splitter.auto_segments(100, segment_length=45, min_length=15)
    assert len(cuts) == 2
    assert cuts[-1].end == 100
    assert cuts[-1].duration > 45  # absorbed the short tail


def test_auto_segments_respects_max_length_cap():
    cuts = splitter.auto_segments(200, segment_length=120, max_length=90, min_length=5)
    assert all(c.duration <= 90 for c in cuts)


def test_auto_segments_rejects_bad_input():
    with pytest.raises(ValueError):
        splitter.auto_segments(0)
    with pytest.raises(ValueError):
        splitter.auto_segments(100, segment_length=2, min_length=5)


def test_load_cut_list(tmp_path):
    cuts_file = tmp_path / "cuts.json"
    cuts_file.write_text(json.dumps([
        {"start": "00:05", "end": "00:20", "label": "Intro Shot!"},
        {"start": 20, "end": 45, "label": "b-roll"},
    ]))
    cuts = splitter.load_cut_list(str(cuts_file))
    assert len(cuts) == 2
    assert cuts[0].start == 5.0
    assert cuts[0].end == 20.0


def test_load_cut_list_requires_top_level_array(tmp_path):
    cuts_file = tmp_path / "cuts.json"
    cuts_file.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError):
        splitter.load_cut_list(str(cuts_file))


def test_slugify_produces_filesystem_safe_names():
    assert splitter._slugify("Intro Shot!") == "intro-shot"
    assert splitter._slugify("") == "clip"


def test_split_video_calls_trim_per_cut_and_names_files(tmp_path):
    cuts = [CutSpec(start=0, end=5, label="Hook"), CutSpec(start=5, end=12, label="Reveal")]
    with patch.object(ffmpeg_utils, "require_ffmpeg"), patch.object(ffmpeg_utils, "trim") as mock_trim:
        clips = splitter.split_video("source.mp4", cuts, str(tmp_path))
    assert mock_trim.call_count == 2
    assert clips[0].label == "Hook"
    assert clips[0].duration == 5
    assert "01-hook" in clips[0].path
    assert "02-reveal" in clips[1].path


def test_suggest_cuts_from_scenes_merges_short_segments():
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch.object(ffmpeg_utils, "detect_scene_changes") as mock_scenes:
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=30.0, width=1080, height=1920, has_audio=True)
        mock_scenes.return_value = [10.0, 10.5, 20.0]  # 10.0-10.5 is a too-short false positive
        cuts = splitter.suggest_cuts_from_scenes("source.mp4", min_length=3.0)
    assert cuts[0].start == 0.0
    assert all(c.duration >= 3.0 for c in cuts)
    assert cuts[-1].end == 30.0


# ---------------------------------------------------------------- editor --

def test_build_filter_graph_crop_mode_no_extras():
    opts = EditOptions(fit_mode="crop", fade_seconds=0)
    graph, uses_fc, extra_inputs = build_filter_graph(opts)
    assert "scale=1080:1920" in graph
    assert "crop=1080:1920" in graph
    assert uses_fc is False
    assert extra_inputs == []


def test_build_filter_graph_pad_mode_uses_blur_background():
    opts = EditOptions(fit_mode="pad", fade_seconds=0)
    graph, uses_fc, _ = build_filter_graph(opts)
    assert "gblur" in graph
    assert uses_fc is False


def test_build_filter_graph_includes_fade_out_at_correct_timestamp():
    opts = EditOptions(fade_seconds=0.5, max_duration=None)
    graph, _, _ = build_filter_graph(opts, clip_duration=10.0)
    assert "fade=t=in:st=0:d=0.5" in graph
    assert "fade=t=out:st=9.500:d=0.5" in graph


def test_build_filter_graph_fade_out_respects_max_duration_cap():
    opts = EditOptions(fade_seconds=0.5, max_duration=6.0)
    graph, _, _ = build_filter_graph(opts, clip_duration=20.0)
    # clip is longer than max_duration, so fade-out should be anchored to
    # the 6s cap, not the full 20s source length.
    assert "fade=t=out:st=5.500:d=0.5" in graph


def test_build_filter_graph_captions_are_escaped_and_positioned():
    opts = EditOptions(
        fade_seconds=0,
        captions=[
            CaptionSpec(text="Before: totaled", position="top"),
            CaptionSpec(text="Call us: 555-1234", position="bottom"),
        ],
    )
    graph, _, _ = build_filter_graph(opts)
    assert "drawtext" in graph
    assert "Call us\\: 555-1234" in graph  # colon escaped for ffmpeg filter syntax
    assert graph.count("drawtext") == 2


def test_build_filter_graph_watermark_uses_filter_complex_and_extra_input():
    opts = EditOptions(fade_seconds=0, watermark=WatermarkSpec(path="logo.png", position="bottom_right"))
    graph, uses_fc, extra_inputs = build_filter_graph(opts)
    assert uses_fc is True
    assert extra_inputs == ["logo.png"]
    assert "[1:v]" in graph
    assert "overlay=W-w-32:H-h-32[vout]" in graph


def test_build_edit_cmd_simple_case_has_expected_shape():
    opts = EditOptions(fade_seconds=0, max_duration=60)
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=90)
    assert cmd[0] == "ffmpeg"
    assert "-vf" in cmd
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "60.000"
    assert cmd[-1] == "out.mp4"
    assert "-map" in cmd and "0:a?" in cmd


def test_build_edit_cmd_with_music_builds_amix_and_maps_music_input():
    opts = EditOptions(fade_seconds=0, music_path="music.mp3", music_volume_db=-20, duck_original_audio_db=-6)
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30)
    assert "music.mp3" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "amix=inputs=2" in fc
    assert "volume=-20dB" in fc
    assert "volume=-6dB" in fc  # ducking applied to original track
    assert "[aout]" in cmd


def test_build_edit_cmd_with_watermark_and_music_together():
    opts = EditOptions(
        fade_seconds=0,
        watermark=WatermarkSpec(path="logo.png"),
        music_path="music.mp3",
    )
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30)
    # inputs: 0=video, 1=watermark, 2=music
    assert cmd.count("-i") == 3
    assert "-map" in cmd
    video_map_idx = cmd.index("-map") + 1
    assert cmd[video_map_idx] == "[vout]"


def test_edit_clip_requires_ffmpeg(tmp_path):
    with patch.object(ffmpeg_utils, "require_ffmpeg", side_effect=ffmpeg_utils.FfmpegNotFoundError("nope")):
        from reel_toolkit.editor import edit_clip
        with pytest.raises(ffmpeg_utils.FfmpegNotFoundError):
            edit_clip("in.mp4", str(tmp_path / "out.mp4"), EditOptions())


# -------------------------------------------------------------- pipeline --

def test_edit_options_from_dict_builds_nested_specs():
    opts = _edit_options_from_dict({
        "fit_mode": "pad",
        "max_duration": 45,
        "captions": [{"text": "hi", "position": "top"}],
        "watermark": {"path": "logo.png", "position": "top_left"},
    })
    assert opts.fit_mode == "pad"
    assert opts.max_duration == 45
    assert len(opts.captions) == 1
    assert opts.captions[0].text == "hi"
    assert opts.watermark.position == "top_left"


def test_run_project_with_explicit_cuts(tmp_path):
    config = {
        "source": "raw.mp4",
        "output_dir": str(tmp_path / "out"),
        "cuts": [
            {"start": 0, "end": 10, "label": "a"},
            {"start": 10, "end": 20, "label": "b"},
        ],
        "edit": {"max_duration": 60},
        "clip_overrides": {"b": {"captions": [{"text": "Second clip", "position": "top"}]}},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    def fake_split_video(source, cuts, out_dir, fast_copy=False, filename_prefix=None):
        os.makedirs(out_dir, exist_ok=True)
        from reel_toolkit.models import Clip
        clips = []
        for i, c in enumerate(cuts, start=1):
            p = os.path.join(out_dir, f"{i:02d}-{c.label}.mp4")
            open(p, "w").close()
            clips.append(Clip(path=p, label=c.label, duration=c.duration, source=source))
        return clips

    def fake_edit_clip(input_path, output_path, opts):
        from reel_toolkit.models import Clip
        open(output_path, "w").close()
        return Clip(path=output_path, label=os.path.basename(output_path), duration=opts.max_duration or 10, source=input_path)

    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch("reel_toolkit.pipeline.splitter.split_video", side_effect=fake_split_video), \
         patch("reel_toolkit.pipeline.edit_clip", side_effect=fake_edit_clip):
        manifest = run_project(str(config_path))

    assert len(manifest["clips"]) == 2
    assert os.path.exists(os.path.join(str(tmp_path / "out"), "manifest.json"))
    labels = [c["label"] for c in manifest["clips"]]
    assert labels == ["a", "b"]


def test_run_project_requires_cuts_or_auto_segment(tmp_path):
    config = {"source": "raw.mp4", "output_dir": str(tmp_path / "out")}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    with patch.object(ffmpeg_utils, "require_ffmpeg"):
        with pytest.raises(ValueError):
            run_project(str(config_path))


# -------------------------------------------------------------------- cli --

def test_cli_parser_builds_edit_options_from_flags():
    from reel_toolkit.cli import build_parser, _build_edit_options
    parser = build_parser()
    args = parser.parse_args([
        "edit", "in.mp4", "--out", "out.mp4",
        "--caption-top", "Hello", "--watermark", "logo.png",
        "--fit-mode", "pad", "--max-duration", "30",
    ])
    opts = _build_edit_options(args)
    assert opts.fit_mode == "pad"
    assert opts.max_duration == 30
    assert opts.captions[0].text == "Hello"
    assert opts.watermark.path == "logo.png"


def test_cli_parser_requires_subcommand():
    from reel_toolkit.cli import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
