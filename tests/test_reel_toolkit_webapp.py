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
