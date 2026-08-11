"""Tests for the reel_toolkit drag-and-drop web UI (reel_toolkit/webapp).

Same approach as test_reel_toolkit.py: the ffmpeg/ffprobe subprocess
boundary is mocked so these run without ffmpeg installed, and we drive the
actual FastAPI app through TestClient to exercise routing, form parsing,
and error handling.
"""
from __future__ import annotations

import io
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from reel_toolkit import ffmpeg_utils
from reel_toolkit.models import Clip
from reel_toolkit.webapp.main import JOBS_DIR, app, parse_manual_cuts

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_jobs_dir():
    """Each test that hits /api/process writes real files under
    reel_toolkit/webapp/jobs/<job_id>/ (only the JSONResponse is mocked
    data, not the filesystem side effects) -- sweep them up so repeated
    test runs don't accumulate throwaway job folders in the repo.
    """
    before = set(JOBS_DIR.iterdir()) if JOBS_DIR.exists() else set()
    yield
    after = set(JOBS_DIR.iterdir()) if JOBS_DIR.exists() else set()
    import shutil
    for new_dir in after - before:
        shutil.rmtree(new_dir, ignore_errors=True)


def test_index_page_serves_dropzone_ui():
    res = client.get("/")
    assert res.status_code == 200
    assert "Reel Toolkit" in res.text
    assert 'id="dropzone"' in res.text
    assert "/api/process" in res.text


# ---------------------------------------------------------- manual cuts --

def test_parse_manual_cuts_happy_path():
    cuts = parse_manual_cuts("0:00-0:45 Hook and teardown\n0:45-1:20 Paint booth\n")
    assert len(cuts) == 2
    assert cuts[0].start == 0.0 and cuts[0].end == 45.0
    assert cuts[0].label == "Hook and teardown"
    assert cuts[1].label == "Paint booth"


def test_parse_manual_cuts_ignores_blank_lines():
    cuts = parse_manual_cuts("\n0:00-0:10 a\n\n\n0:10-0:20 b\n")
    assert len(cuts) == 2


def test_parse_manual_cuts_defaults_label_when_missing():
    cuts = parse_manual_cuts("0:00-0:10")
    assert cuts[0].label == "clip"


def test_parse_manual_cuts_rejects_unparseable_line():
    with pytest.raises(Exception):
        parse_manual_cuts("this is not a cut line")


def test_parse_manual_cuts_rejects_empty_input():
    with pytest.raises(Exception):
        parse_manual_cuts("   \n  \n")


# -------------------------------------------------------------- /api/process --

def _fake_split_video(source, cuts, out_dir, fast_copy=False, filename_prefix=None):
    os.makedirs(out_dir, exist_ok=True)
    clips = []
    for i, c in enumerate(cuts, start=1):
        p = os.path.join(out_dir, f"{i:02d}-{c.label}.mp4")
        open(p, "wb").close()
        clips.append(Clip(path=p, label=c.label, duration=c.duration, source=source))
    return clips


def _fake_edit_clip(input_path, output_path, opts):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(b"fake-mp4-bytes")
    return Clip(path=output_path, label=os.path.basename(output_path), duration=opts.max_duration or 10, source=input_path)


@pytest.fixture
def mocked_ffmpeg():
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch("reel_toolkit.webapp.main.splitter.split_video", side_effect=_fake_split_video), \
         patch("reel_toolkit.webapp.main.edit_clip", side_effect=_fake_edit_clip):
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=90.0, width=1920, height=1080, has_audio=True)
        yield mock_probe


def test_process_whole_video_mode(mocked_ffmpeg):
    res = client.post(
        "/api/process",
        data={"cut_mode": "whole", "caption_top": "Hello", "max_duration": "60"},
        files={"video": ("job.mp4", io.BytesIO(b"fake video bytes"), "video/mp4")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["clips"]) == 1
    assert body["clips"][0]["label"] == "full"
    assert body["clips"][0]["url"].startswith(f"/jobs/{body['job_id']}/final/")

    # the returned URL should actually be servable via the StaticFiles mount
    download = client.get(body["clips"][0]["url"])
    assert download.status_code == 200
    assert download.content == b"fake-mp4-bytes"


def test_process_whole_video_mode_skips_the_trim_step():
    """Regression test: 'whole video' mode used to round-trip the upload
    through splitter.split_video (an unnecessary trim/re-encode) before
    editing, which could produce a zero-stream intermediate file on some
    real-world phone recordings. It should now feed the upload straight
    into edit_clip instead.
    """
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch("reel_toolkit.webapp.main.splitter.split_video") as mock_split, \
         patch("reel_toolkit.webapp.main.edit_clip", side_effect=_fake_edit_clip) as mock_edit:
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=12.0, width=1080, height=1920, has_audio=True)
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},
            files={"video": ("job.mp4", io.BytesIO(b"fake video bytes"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    mock_split.assert_not_called()
    assert mock_edit.call_count == 1
    input_path_arg = mock_edit.call_args[0][0]
    assert input_path_arg.endswith("raw/job.mp4")


def test_process_auto_segment_mode_produces_multiple_clips(mocked_ffmpeg):
    res = client.post(
        "/api/process",
        data={"cut_mode": "auto", "segment_seconds": "30"},
        files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert res.status_code == 200
    clips = res.json()["clips"]
    assert len(clips) == 3  # 90s / 30s segments


def test_process_manual_mode_uses_provided_cuts(mocked_ffmpeg):
    res = client.post(
        "/api/process",
        data={"cut_mode": "manual", "manual_cuts": "0:00-0:20 Intro\n0:20-0:50 Repair"},
        files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert res.status_code == 200
    labels = [c["label"] for c in res.json()["clips"]]
    assert labels == ["Intro", "Repair"]


def test_process_manual_mode_rejects_bad_cut_list(mocked_ffmpeg):
    res = client.post(
        "/api/process",
        data={"cut_mode": "manual", "manual_cuts": "not a valid line"},
        files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert res.status_code == 400


def test_process_auto_enhance_defaults_to_true_and_is_passed_through(mocked_ffmpeg):
    """The web UI's 'Auto-enhance colors' checkbox is checked by default --
    confirm the resulting EditOptions actually carries that through to
    edit_clip when the form field is omitted (as a real un-submitted
    checkbox would be) as well as when explicitly sent.
    """
    captured = {}

    def capturing_edit_clip(input_path, output_path, opts):
        captured["opts"] = opts
        return _fake_edit_clip(input_path, output_path, opts)

    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch("reel_toolkit.webapp.main.edit_clip", side_effect=capturing_edit_clip):
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=10.0, width=1080, height=1920, has_audio=True)
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},  # auto_enhance omitted -> Form(True) default applies
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    assert captured["opts"].auto_enhance is True


def test_process_manual_color_values_are_passed_through(mocked_ffmpeg):
    captured = {}

    def capturing_edit_clip(input_path, output_path, opts):
        captured["opts"] = opts
        return _fake_edit_clip(input_path, output_path, opts)

    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch("reel_toolkit.webapp.main.edit_clip", side_effect=capturing_edit_clip):
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=10.0, width=1080, height=1920, has_audio=True)
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole", "auto_enhance": "false", "saturation": "1.4",
                  "contrast": "1.1", "brightness": "-0.1", "color_temperature": "4500"},
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    opts = captured["opts"]
    assert opts.auto_enhance is False
    assert opts.saturation == 1.4
    assert opts.contrast == 1.1
    assert opts.brightness == -0.1
    assert opts.color_temperature == 4500


def test_process_duck_original_audio_db_is_passed_through(mocked_ffmpeg):
    captured = {}

    def capturing_edit_clip(input_path, output_path, opts):
        captured["opts"] = opts
        return _fake_edit_clip(input_path, output_path, opts)

    with patch("reel_toolkit.webapp.main.edit_clip", side_effect=capturing_edit_clip):
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole", "duck_original_audio_db": "-8"},
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    assert captured["opts"].duck_original_audio_db == -8


def test_process_duck_original_audio_db_defaults_to_zero(mocked_ffmpeg):
    captured = {}

    def capturing_edit_clip(input_path, output_path, opts):
        captured["opts"] = opts
        return _fake_edit_clip(input_path, output_path, opts)

    with patch("reel_toolkit.webapp.main.edit_clip", side_effect=capturing_edit_clip):
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    assert captured["opts"].duck_original_audio_db == 0.0


def test_process_combine_with_transitions_calls_stitcher():
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe, \
         patch("reel_toolkit.webapp.main.splitter.split_video", side_effect=_fake_split_video), \
         patch("reel_toolkit.webapp.main.stitcher.stitch_and_polish") as mock_stitch:
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=60.0, width=1080, height=1920, has_audio=True)

        def fake_stitch(clip_paths, stitched_path, final_path, opts, transition, transition_duration):
            with open(final_path, "wb") as f:
                f.write(b"stitched-bytes")
            return Clip(path=final_path, label="stitched", duration=55.0)

        mock_stitch.side_effect = fake_stitch
        res = client.post(
            "/api/process",
            data={"cut_mode": "auto", "segment_seconds": "30", "combine_with_transitions": "true",
                  "transition": "wipeleft", "transition_duration": "0.5"},
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert mock_stitch.call_count == 1
    args = mock_stitch.call_args.args
    assert len(args[0]) == 2  # 2 clip paths from a 60s video / 30s segments
    assert len(body["clips"]) == 1  # one combined result, not one per cut
    assert "combined" in body["clips"][0]["label"]


def test_process_combine_with_transitions_ignored_for_single_clip(mocked_ffmpeg):
    """'whole' mode only ever produces one clip -- combine_with_transitions
    should be a no-op (falls back to the normal single-clip edit path)
    rather than erroring on 'stitching needs at least 2 clips'."""
    with patch("reel_toolkit.webapp.main.stitcher.stitch_and_polish") as mock_stitch:
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole", "combine_with_transitions": "true"},
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 200, res.text
    mock_stitch.assert_not_called()
    assert len(res.json()["clips"]) == 1


def test_process_rejects_unknown_transition(mocked_ffmpeg):
    res = client.post(
        "/api/process",
        data={"cut_mode": "auto", "combine_with_transitions": "true", "transition": "made-up-transition"},
        files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert res.status_code == 400
    assert "made-up-transition" in res.json()["detail"]


def test_process_rejects_bad_fit_mode(mocked_ffmpeg):
    res = client.post(
        "/api/process",
        data={"cut_mode": "whole", "fit_mode": "stretch"},
        files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert res.status_code == 400


def test_process_returns_500_when_ffmpeg_missing():
    with patch.object(ffmpeg_utils, "require_ffmpeg", side_effect=ffmpeg_utils.FfmpegNotFoundError("ffmpeg missing")):
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},
            files={"video": ("job.mp4", io.BytesIO(b"x"), "video/mp4")},
        )
    assert res.status_code == 500
    assert "ffmpeg" in res.json()["detail"].lower()


def test_process_rejects_upload_with_no_video_stream():
    """A photo dropped in by mistake (e.g. a .jpeg) probes with width/height
    0 -- reject it with a clear message instead of letting it reach ffmpeg's
    encoder and blow up with a cryptic libx264 error.
    """
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe:
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=0.04, width=0, height=0, has_audio=False)
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},
            files={"video": ("photo.jpeg", io.BytesIO(b"x"), "image/jpeg")},
        )
    assert res.status_code == 400
    assert "video track" in res.json()["detail"].lower()


def test_process_rejects_upload_that_is_too_short():
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe") as mock_probe:
        mock_probe.return_value = ffmpeg_utils.ProbeResult(duration=0.04, width=323, height=576, has_audio=False)
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},
            files={"video": ("photo.jpeg", io.BytesIO(b"x"), "image/jpeg")},
        )
    assert res.status_code == 400
    assert "0.04s" in res.json()["detail"]


def test_process_gives_friendly_message_when_file_is_unreadable():
    """A truncated/incomplete upload (e.g. an iCloud placeholder that
    hasn't fully downloaded) makes ffprobe itself fail with something like
    'moov atom not found' -- that should surface as a plain-English 400,
    not the raw ffmpeg stderr dump.
    """
    with patch.object(ffmpeg_utils, "require_ffmpeg"), \
         patch.object(ffmpeg_utils, "probe", side_effect=ffmpeg_utils.FfmpegError("moov atom not found")):
        res = client.post(
            "/api/process",
            data={"cut_mode": "whole"},
            files={"video": ("clip.mov", io.BytesIO(b"x"), "video/quicktime")},
        )
    assert res.status_code == 400
    detail = res.json()["detail"].lower()
    assert "incomplete or corrupted" in detail
    assert "icloud" in detail


def test_uploaded_filenames_are_sanitized(mocked_ffmpeg, tmp_path):
    res = client.post(
        "/api/process",
        data={"cut_mode": "whole"},
        files={"video": ("../../evil name!!.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    from reel_toolkit.webapp.main import JOBS_DIR
    raw_dir = JOBS_DIR / job_id / "raw"
    saved = list(raw_dir.iterdir())
    assert len(saved) == 1
    assert ".." not in saved[0].name
    assert "/" not in saved[0].name
