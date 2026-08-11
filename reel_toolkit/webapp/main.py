"""FastAPI backend for the drag-and-drop reel_toolkit web UI.

One page (static/index.html) posts a video + a small form to /api/process;
this module saves the upload, runs the same splitter/editor code the CLI
uses, and returns URLs to the finished clip(s), served straight out of
this job's folder under /jobs/.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from reel_toolkit import ffmpeg_utils, splitter, stitcher
from reel_toolkit.editor import edit_clip
from reel_toolkit.models import CaptionSpec, Clip, CutSpec, EditOptions, WatermarkSpec

APP_DIR = Path(__file__).resolve().parent
JOBS_DIR = APP_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Reel Toolkit")
app.mount("/jobs", StaticFiles(directory=str(JOBS_DIR)), name="jobs")

_INDEX_HTML = (STATIC_DIR / "index.html").read_text()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


def _safe_filename(name: Optional[str]) -> str:
    name = os.path.basename(name or "upload")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    return name or "upload"


def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_filename(upload.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


def parse_manual_cuts(text: str) -> List[CutSpec]:
    """Parse the manual cut-list textarea, one cut per line:

        0:00-0:45 Hook and teardown
        0:45-1:20 Paint booth

    Raises HTTPException(400) with the offending line if a line doesn't
    parse, so the form can show the user exactly what to fix.
    """
    cuts: List[CutSpec] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r"^([\d:.]+)\s*-\s*([\d:.]+)\s*(.*)$", line)
        if not m:
            raise HTTPException(400, f"Couldn't parse cut line: {line!r} -- expected 'start-end label'")
        start, end, label = m.groups()
        try:
            cuts.append(CutSpec.from_dict({"start": start, "end": end, "label": label.strip() or "clip"}))
        except ValueError as e:
            raise HTTPException(400, f"Bad cut line {line!r}: {e}")
    if not cuts:
        raise HTTPException(400, "Manual cut list is empty -- add at least one 'start-end label' line.")
    return cuts


@app.post("/api/process")
async def process(
    video: UploadFile = File(...),
    cut_mode: str = Form("whole"),            # "whole" | "auto" | "manual"
    segment_seconds: float = Form(45.0),
    manual_cuts: str = Form(""),
    caption_top: str = Form(""),
    caption_bottom: str = Form(""),
    fit_mode: str = Form("crop"),
    max_duration: float = Form(60.0),
    watermark_position: str = Form("bottom_right"),
    music_volume_db: float = Form(-18.0),
    duck_original_audio_db: float = Form(0.0),  # lower original audio while music plays under it; 0 = full volume
    auto_enhance: bool = Form(True),          # analyze footage and auto-correct color -- no numbers needed by default
    saturation: float = Form(1.0),
    contrast: float = Form(1.0),
    brightness: float = Form(0.0),
    color_temperature: Optional[int] = Form(None),
    combine_with_transitions: bool = Form(False),
    transition: str = Form(stitcher.DEFAULT_TRANSITION),
    transition_duration: float = Form(0.5),
    watermark: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
) -> JSONResponse:
    try:
        ffmpeg_utils.require_ffmpeg()
    except ffmpeg_utils.FfmpegNotFoundError as e:
        raise HTTPException(500, str(e))

    if fit_mode not in ("crop", "pad"):
        raise HTTPException(400, "fit_mode must be 'crop' or 'pad'")
    if cut_mode not in ("whole", "auto", "manual"):
        raise HTTPException(400, "cut_mode must be 'whole', 'auto', or 'manual'")
    if combine_with_transitions and transition not in stitcher.COMMON_TRANSITIONS:
        raise HTTPException(
            400,
            f"Unknown transition '{transition}' -- choose one of: {', '.join(stitcher.COMMON_TRANSITIONS)}",
        )

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    raw_dir = job_dir / "raw"
    cuts_dir = job_dir / "cuts"
    final_dir = job_dir / "final"

    video_path = _save_upload(video, raw_dir)
    watermark_path = _save_upload(watermark, job_dir) if (watermark and watermark.filename) else None
    music_path = _save_upload(music, job_dir) if (music and music.filename) else None

    try:
        probe = ffmpeg_utils.probe(str(video_path))
    except ffmpeg_utils.FfmpegError:
        raise HTTPException(
            400,
            f"Couldn't read '{video.filename}' as a video -- the file looks incomplete or corrupted, not just "
            "the wrong type. This is common when dragging a video straight out of the Photos app if the "
            "original is stored in iCloud and hasn't fully downloaded to this Mac yet. Try: open the video in "
            "Photos or QuickTime Player first and confirm it actually plays, then in Photos use "
            "File > Export > Export Unmodified Original to save a real copy to your Desktop, and drop that "
            "exported file in instead.",
        )

    try:
        if probe.width == 0 or probe.height == 0:
            raise HTTPException(
                400,
                f"'{video.filename}' doesn't have a video track ffmpeg can read -- "
                "make sure you're dropping a video file (.mp4, .mov, etc.), not a photo or other file type.",
            )
        if probe.duration < 0.5:
            raise HTTPException(
                400,
                f"'{video.filename}' is only {probe.duration:.2f}s long, which usually means it's actually a "
                "photo (not a video) or the file didn't upload correctly. Please drop an actual video file.",
            )

        if cut_mode == "whole":
            # No cutting needed -- feed the upload straight into the edit
            # pass instead of round-tripping it through an unnecessary
            # trim/re-encode first (which also sidesteps a real-world
            # ffmpeg edge case where certain phone-recorded files come out
            # of a 0-to-full-duration trim with zero usable streams).
            raw_clips = [Clip(path=str(video_path), label="full", duration=probe.duration, source=str(video_path))]
        else:
            if cut_mode == "auto":
                cuts = splitter.auto_segments(probe.duration, segment_length=segment_seconds)
            else:
                cuts = parse_manual_cuts(manual_cuts)
            raw_clips = splitter.split_video(str(video_path), cuts, str(cuts_dir))

        captions = []
        if caption_top.strip():
            captions.append(CaptionSpec(text=caption_top.strip(), position="top"))
        if caption_bottom.strip():
            captions.append(CaptionSpec(text=caption_bottom.strip(), position="bottom"))
        watermark_spec = (
            WatermarkSpec(path=str(watermark_path), position=watermark_position) if watermark_path else None
        )

        final_dir.mkdir(parents=True, exist_ok=True)
        opts_kwargs = dict(
            fit_mode=fit_mode,
            max_duration=max_duration or None,
            captions=captions,
            watermark=watermark_spec,
            music_path=str(music_path) if music_path else None,
            music_volume_db=music_volume_db,
            duck_original_audio_db=duck_original_audio_db,
            auto_enhance=auto_enhance,
            saturation=saturation,
            contrast=contrast,
            brightness=brightness,
            color_temperature=color_temperature,
        )

        results = []
        if combine_with_transitions and len(raw_clips) >= 2:
            opts = EditOptions(**opts_kwargs)
            stitched_path = job_dir / "stitched.mp4"
            out_path = final_dir / "combined-reel.mp4"
            final_clip = stitcher.stitch_and_polish(
                [c.path for c in raw_clips], str(stitched_path), str(out_path), opts,
                transition=transition, transition_duration=transition_duration,
            )
            results.append({
                "label": f"combined ({len(raw_clips)} clips, {transition} transition)",
                "duration": round(final_clip.duration, 1),
                "url": f"/jobs/{job_id}/final/combined-reel.mp4",
            })
        else:
            for clip in raw_clips:
                opts = EditOptions(**opts_kwargs)
                out_name = Path(clip.path).stem + "-reel.mp4"
                out_path = final_dir / out_name
                final_clip = edit_clip(clip.path, str(out_path), opts)
                results.append({
                    "label": clip.label,
                    "duration": round(final_clip.duration, 1),
                    "url": f"/jobs/{job_id}/final/{out_name}",
                })
    except ffmpeg_utils.FfmpegError as e:
        raise HTTPException(500, f"ffmpeg failed: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    return JSONResponse({"job_id": job_id, "clips": results})
