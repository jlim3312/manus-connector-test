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

from PIL import Image

from reel_toolkit import ffmpeg_utils, splitter, stitcher
from reel_toolkit.caption_render import parse_ffmpeg_color, render_caption_png
from reel_toolkit.editor import build_edit_cmd, build_filter_graph, color_filters
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


def test_edit_options_validates_color_grading_ranges():
    with pytest.raises(ValueError):
        EditOptions(saturation=-0.1)
    with pytest.raises(ValueError):
        EditOptions(contrast=-1)
    with pytest.raises(ValueError):
        EditOptions(brightness=1.5)
    with pytest.raises(ValueError):
        EditOptions(color_temperature=500)  # below the 1000K floor
    with pytest.raises(ValueError):
        EditOptions(color_temperature=50000)  # above the 40000K ceiling
    EditOptions(saturation=1.3, contrast=1.1, brightness=-0.2, color_temperature=4500)  # should not raise


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


def test_build_trim_cmd_reencode_uses_accurate_seek_after_input():
    """The default (fast_copy=False) path re-encodes, so -ss should go
    *after* -i for frame-accurate, edit-list-safe seeking, with
    -avoid_negative_ts to guard against the empty-output edge case seen
    on some phone-recorded files. See ffmpeg_utils.build_trim_cmd docstring.
    """
    cmd = ffmpeg_utils.build_trim_cmd("in.mp4", "out.mp4", start=5.0, end=15.0, fast_copy=False)
    assert cmd[1:3] == ["-y", "-i"]          # -i comes right after -y, before -ss
    assert "-i" in cmd and "-ss" in cmd
    assert cmd.index("-i") < cmd.index("-ss")
    assert "-avoid_negative_ts" in cmd and cmd[cmd.index("-avoid_negative_ts") + 1] == "make_zero"


def test_build_trim_cmd_fast_copy_uses_input_side_seek():
    """fast_copy=True is the quick-preview path -- -ss stays *before* -i
    for fast keyframe-snapped seeking (no re-encode happening anyway)."""
    cmd = ffmpeg_utils.build_trim_cmd("in.mp4", "out.mp4", start=5.0, end=15.0, fast_copy=True)
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"


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


def test_build_filter_graph_captions_are_composited_as_image_overlays():
    """Captions are pre-rendered PNGs (see caption_render.py) composited
    with a plain overlay=0:0 -- not ffmpeg's drawtext, which requires
    libfreetype and isn't available on every ffmpeg build (e.g. Homebrew's
    default macOS formula ships without it).
    """
    opts = EditOptions(
        fade_seconds=0,
        captions=[CaptionSpec(text="Before: totaled", position="top"),
                  CaptionSpec(text="Call us: 555-1234", position="bottom")],
    )
    graph, uses_fc, extra_inputs = build_filter_graph(opts, caption_image_paths=["cap0.png", "cap1.png"])
    assert uses_fc is True
    assert extra_inputs == ["cap0.png", "cap1.png"]
    assert "drawtext" not in graph
    assert "[1:v]" in graph and "[2:v]" in graph
    assert graph.count("overlay=0:0") == 2
    assert graph.endswith("[vout]")


def test_build_filter_graph_watermark_uses_filter_complex_and_extra_input():
    opts = EditOptions(fade_seconds=0, watermark=WatermarkSpec(path="logo.png", position="bottom_right"))
    graph, uses_fc, extra_inputs = build_filter_graph(opts)
    assert uses_fc is True
    assert extra_inputs == ["logo.png"]
    assert "[1:v]" in graph
    assert "overlay=W-w-32:H-h-32[vout]" in graph


def test_build_filter_graph_captions_and_watermark_together_order_inputs_correctly():
    opts = EditOptions(
        fade_seconds=0,
        captions=[CaptionSpec(text="hook", position="top")],
        watermark=WatermarkSpec(path="logo.png", position="bottom_right"),
    )
    graph, uses_fc, extra_inputs = build_filter_graph(opts, caption_image_paths=["cap0.png"])
    # caption image(s) first, watermark last -- matches the -i ordering build_edit_cmd uses
    assert extra_inputs == ["cap0.png", "logo.png"]
    assert "[1:v]" in graph   # caption input
    assert "[2:v]" in graph   # watermark input
    assert graph.endswith("[vout]")


def test_build_filter_graph_no_captions_or_watermark_stays_simple():
    graph, uses_fc, extra_inputs = build_filter_graph(EditOptions(fade_seconds=0))
    assert uses_fc is False
    assert extra_inputs == []
    assert "overlay" not in graph


# -------------------------------------------------------- color grading --

def test_color_filters_empty_by_default():
    assert color_filters(EditOptions()) == []


def test_color_filters_auto_enhance_uses_normalize_and_vibrance():
    parts = color_filters(EditOptions(auto_enhance=True))
    assert any(p.startswith("normalize") for p in parts)
    assert any(p.startswith("vibrance") for p in parts)


def test_color_filters_auto_enhance_normalize_uses_reduced_strength_and_linked_channels():
    """Regression test: ffmpeg's `normalize` at its full-strength default
    (independent per-channel stretch to pure black/white) crushes a frame
    dominated by one flat, low-variance color to solid black -- confirmed
    against a real solid-color clip through actual ffmpeg. Exactly the
    kind of shot this shop films constantly (a tight closeup on a
    solid-color panel). auto_enhance must use a tamed strength/independence
    instead of bare 'normalize', or this bites on real footage.
    """
    parts = color_filters(EditOptions(auto_enhance=True))
    normalize_filter = next(p for p in parts if p.startswith("normalize"))
    assert normalize_filter != "normalize", "must not use ffmpeg's unsafe full-strength default"
    assert "strength=0.5" in normalize_filter
    assert "independence=0" in normalize_filter


def test_color_filters_manual_saturation_contrast_brightness_use_eq():
    parts = color_filters(EditOptions(saturation=1.3, contrast=1.1, brightness=-0.1))
    assert len(parts) == 1
    assert parts[0] == "eq=saturation=1.3:contrast=1.1:brightness=-0.1"


def test_color_filters_warmth_uses_colortemperature():
    parts = color_filters(EditOptions(color_temperature=4500))
    assert parts == ["colortemperature=temperature=4500"]


def test_color_filters_auto_enhance_and_manual_stack_in_order():
    """Auto-enhance (analysis-driven) applies first; manual fine-tuning
    layers on top of it, not the other way around."""
    parts = color_filters(EditOptions(auto_enhance=True, saturation=1.2, color_temperature=8000))
    assert parts[0].startswith("normalize")
    assert parts[1].startswith("vibrance")
    assert parts[2].startswith("eq=saturation=1.2")
    assert parts[3] == "colortemperature=temperature=8000"


def test_build_filter_graph_includes_color_filters_in_base_chain():
    opts = EditOptions(fade_seconds=0, auto_enhance=True)
    graph, _, _ = build_filter_graph(opts)
    assert "normalize" in graph
    assert "vibrance" in graph


def test_build_edit_cmd_simple_case_has_expected_shape():
    opts = EditOptions(fade_seconds=0, max_duration=60)
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=90)
    assert cmd[0] == "ffmpeg"
    assert "-vf" in cmd
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "60.000"
    assert cmd[-1] == "out.mp4"
    assert "-map" in cmd and "0:a?" in cmd


def test_build_edit_cmd_with_captions_maps_caption_inputs_before_music():
    opts = EditOptions(
        fade_seconds=0,
        captions=[CaptionSpec(text="hook", position="top")],
        music_path="music.mp3",
    )
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30, caption_image_paths=["cap0.png"])
    # -i order must be: main video, caption png(s), then music -- build_edit_cmd's
    # music_input_idx math (1 + len(extra_inputs)) depends on this exact order.
    i_positions = [i for i, arg in enumerate(cmd) if arg == "-i"]
    inputs_in_order = [cmd[i + 1] for i in i_positions]
    assert inputs_in_order == ["in.mp4", "cap0.png", "music.mp3"]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[2:a]" in fc  # music is input index 2 (0=video, 1=caption)


def test_build_edit_cmd_with_music_builds_amix_and_maps_music_input():
    opts = EditOptions(fade_seconds=0, music_path="music.mp3", music_volume_db=-20, duck_original_audio_db=-6)
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30)
    assert "music.mp3" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "amix=inputs=2" in fc
    assert "volume=-20dB" in fc
    assert "volume=-6dB" in fc  # ducking applied to original track
    assert "[aout]" in cmd


def test_build_edit_cmd_with_music_and_loudnorm_chains_inside_filter_complex_not_af():
    """Regression test: normalize_loudness defaults to True, and ffmpeg
    rejects a simple -af filter applied to a stream that's the output of a
    complex filtergraph ("Simple and complex filtering cannot be used
    together for the same stream") -- confirmed against the real ffmpeg
    binary. Whenever music is mixed in (audio goes through amix in
    filter_complex), loudnorm must be chained onto that amix output
    instead of appended as a separate -af.
    """
    opts = EditOptions(fade_seconds=0, music_path="music.mp3")  # normalize_loudness defaults True
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "loudnorm=" in fc
    assert fc.count("amix") == 1
    assert "-af" not in cmd, "a simple -af filter can't coexist with a complex-filtergraph-sourced audio stream"


def test_build_edit_cmd_with_music_and_loudness_normalize_disabled_has_no_loudnorm_anywhere():
    opts = EditOptions(fade_seconds=0, music_path="music.mp3", normalize_loudness=False)
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "loudnorm" not in fc
    assert "-af" not in cmd


def test_build_edit_cmd_without_music_still_uses_af_for_loudnorm():
    """No music -> audio is a plain mapped input stream (not complex-filter
    output), so -af works fine and is the simpler path -- this must keep
    working exactly as before."""
    opts = EditOptions(fade_seconds=0, captions=[CaptionSpec(text="hook", position="top")])
    cmd = build_edit_cmd("in.mp4", "out.mp4", opts, clip_duration=30, caption_image_paths=["cap0.png"])
    assert "-af" in cmd
    assert cmd[cmd.index("-af") + 1] == "loudnorm=I=-14:TP=-1.5:LRA=11"
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "loudnorm" not in fc


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


def test_edit_clip_renders_caption_pngs_and_passes_them_to_ffmpeg(tmp_path):
    """edit_clip should render one PNG per caption (via caption_render) and
    thread their paths into the ffmpeg command as extra -i inputs -- this
    is what replaced drawtext.
    """
    from reel_toolkit.editor import edit_clip

    captured_cmd = {}

    def fake_run(cmd):
        captured_cmd["cmd"] = cmd
        # sanity-check every caption PNG referenced in the command actually
        # exists on disk at the moment ffmpeg would be invoked
        for i, arg in enumerate(cmd):
            if arg == "-i" and cmd[i + 1].endswith(".png"):
                assert os.path.exists(cmd[i + 1])
        return None

    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch.object(ffmpeg_utils, "run", side_effect=fake_run):
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=10.0, width=1080, height=1920, has_audio=True)
        opts = EditOptions(captions=[CaptionSpec(text="They said it was totaled...", position="top")])
        edit_clip("in.mp4", str(tmp_path / "out.mp4"), opts)

    cmd = captured_cmd["cmd"]
    assert any(arg.endswith(".png") for arg in cmd)
    assert "drawtext" not in " ".join(cmd)


# --------------------------------------------------------- caption_render --

def test_render_caption_png_produces_frame_sized_transparent_image(tmp_path):
    out_path = tmp_path / "cap.png"
    caption = CaptionSpec(text="Free estimates -- link in bio", position="bottom")
    render_caption_png(caption, width=1080, height=1920, out_path=str(out_path))

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (1080, 1920)
    assert img.mode == "RGBA"
    # fully transparent somewhere (not covering the whole frame) and
    # non-transparent somewhere (the text/box was actually drawn)
    alpha_min, alpha_max = img.getchannel("A").getextrema()
    assert alpha_min == 0
    assert alpha_max > 0


def test_render_caption_png_positions_text_top_vs_bottom(tmp_path):
    """A 'top' caption's opaque pixels should be concentrated in the upper
    half of the frame, and 'bottom' in the lower half."""
    def opaque_row_center(path):
        img = Image.open(path)
        rows_with_content = [y for y in range(img.height)
                              if any(img.getpixel((x, y))[3] > 0 for x in range(0, img.width, 20))]
        return sum(rows_with_content) / len(rows_with_content)

    top_path = tmp_path / "top.png"
    bottom_path = tmp_path / "bottom.png"
    render_caption_png(CaptionSpec(text="hook text", position="top"), 1080, 1920, str(top_path))
    render_caption_png(CaptionSpec(text="cta text", position="bottom"), 1080, 1920, str(bottom_path))

    assert opaque_row_center(top_path) < 1920 / 2
    assert opaque_row_center(bottom_path) > 1920 / 2


def test_render_caption_png_wraps_long_text(tmp_path):
    out_path = tmp_path / "long.png"
    long_caption = CaptionSpec(
        text="This is a very long caption that should definitely wrap across more than one line "
             "once it hits the frame width limit",
        position="top",
    )
    # should not raise, and should produce a taller opaque region than a
    # short one-line caption would
    render_caption_png(long_caption, width=1080, height=1920, out_path=str(out_path))
    assert out_path.exists()


def test_parse_ffmpeg_color_named_and_alpha():
    assert parse_ffmpeg_color("white") == (255, 255, 255, 255)
    assert parse_ffmpeg_color("black@0.55") == (0, 0, 0, 140)


def test_parse_ffmpeg_color_hex():
    assert parse_ffmpeg_color("#ff8800") == (255, 136, 0, 255)


def test_parse_ffmpeg_color_unknown_name_falls_back_to_white():
    assert parse_ffmpeg_color("mystery-color")[:3] == (255, 255, 255)


# --------------------------------------------------------------- stitcher --

def test_build_stitch_cmd_requires_at_least_two_clips():
    with pytest.raises(ValueError):
        stitcher.build_stitch_cmd(["a.mp4"], [10.0], "out.mp4", EditOptions())


def test_build_stitch_cmd_rejects_clip_shorter_than_transition():
    with pytest.raises(ValueError):
        stitcher.build_stitch_cmd(["a.mp4", "b.mp4"], [0.3, 10.0], "out.mp4", EditOptions(),
                                   transition_duration=0.5)


def test_build_stitch_cmd_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        stitcher.build_stitch_cmd(["a.mp4", "b.mp4"], [10.0], "out.mp4", EditOptions())


def test_build_stitch_cmd_chains_xfade_and_acrossfade_across_three_clips():
    cmd = stitcher.build_stitch_cmd(
        ["a.mp4", "b.mp4", "c.mp4"], [10.0, 8.0, 12.0], "out.mp4", EditOptions(fade_seconds=0),
        transition="wipeleft", transition_duration=0.5,
    )
    assert cmd.count("-i") == 3
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.count("xfade=transition=wipeleft:duration=0.5") == 2  # 3 clips -> 2 transitions
    assert fc.count("acrossfade=d=0.5") == 2
    # second xfade's offset accounts for the first clip minus the first transition's overlap
    assert "offset=9.500" in fc   # clip0 (10s) - 0.5s transition
    assert "offset=17.000" in fc  # + clip1 (8s) - 0.5s transition
    video_map_idx = cmd.index("-map") + 1
    assert cmd[video_map_idx].startswith("[v")
    assert cmd[-1] == "out.mp4"


def test_build_stitch_cmd_applies_grading_per_segment():
    cmd = stitcher.build_stitch_cmd(
        ["a.mp4", "b.mp4"], [10.0, 10.0], "out.mp4",
        EditOptions(fade_seconds=0, auto_enhance=True, fit_mode="crop"),
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.count("normalize") == 2  # applied to each of the 2 input segments
    assert fc.count("scale=1080:1920") == 2


def test_stitched_duration_accounts_for_transition_overlap():
    assert stitcher.stitched_duration([10.0, 10.0, 10.0], transition_duration=0.5) == 29.0


def test_polish_options_after_stitch_neutralizes_color_grading_only():
    opts = EditOptions(
        auto_enhance=True, saturation=1.5, contrast=1.2, brightness=0.3, color_temperature=4500,
        fit_mode="pad", max_duration=30,
    )
    polished = stitcher.polish_options_after_stitch(opts)
    assert polished.auto_enhance is False
    assert polished.saturation == 1.0
    assert polished.contrast == 1.0
    assert polished.brightness == 0.0
    assert polished.color_temperature is None
    # non-color settings must survive untouched
    assert polished.fit_mode == "pad"
    assert polished.max_duration == 30


def test_stitch_clips_probes_each_input_and_invokes_ffmpeg(tmp_path):
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch.object(ffmpeg_utils, "run") as mock_run:
        mock_probe.side_effect = [
            ffmpeg_utils.ProbeResult(duration=10.0, width=1080, height=1920, has_audio=True),
            ffmpeg_utils.ProbeResult(duration=8.0, width=1080, height=1920, has_audio=True),
        ]
        clip = stitcher.stitch_clips(["a.mp4", "b.mp4"], str(tmp_path / "out.mp4"), EditOptions(fade_seconds=0))
    assert mock_probe.call_count == 2
    assert mock_run.call_count == 1
    assert clip.duration == pytest.approx(10.0 + 8.0 - 0.5)


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


def test_cli_parser_wires_up_music_and_ducking_flags():
    from reel_toolkit.cli import build_parser, _build_edit_options
    parser = build_parser()
    args = parser.parse_args([
        "edit", "in.mp4", "--out", "out.mp4",
        "--music", "bed.mp3", "--music-volume-db", "-20", "--duck-original-db", "-8",
    ])
    opts = _build_edit_options(args)
    assert opts.music_path == "bed.mp3"
    assert opts.music_volume_db == -20
    assert opts.duck_original_audio_db == -8


def test_cli_parser_duck_original_db_defaults_to_zero_no_ducking():
    from reel_toolkit.cli import build_parser, _build_edit_options
    parser = build_parser()
    args = parser.parse_args(["edit", "in.mp4", "--out", "out.mp4", "--music", "bed.mp3"])
    opts = _build_edit_options(args)
    assert opts.duck_original_audio_db == 0.0


def test_cli_stitch_parser_also_has_ducking_flag():
    from reel_toolkit.cli import build_parser, _build_edit_options
    parser = build_parser()
    args = parser.parse_args([
        "stitch", "a.mp4", "b.mp4", "--out", "out.mp4",
        "--music", "bed.mp3", "--duck-original-db", "-10",
    ])
    opts = _build_edit_options(args)
    assert opts.duck_original_audio_db == -10


def test_cli_parser_requires_subcommand():
    from reel_toolkit.cli import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
