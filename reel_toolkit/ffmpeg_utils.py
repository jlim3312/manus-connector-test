"""Thin wrapper around the ffmpeg/ffprobe binaries.

Every function here is a subprocess boundary -- kept in one file so the rest
of the package (splitter.py, editor.py) can be unit-tested by mocking
`run_ffmpeg`/`run_ffprobe` instead of needing ffmpeg actually installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional


class FfmpegNotFoundError(RuntimeError):
    pass


class FfmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise FfmpegNotFoundError(
            "ffmpeg was not found on PATH. Install it first:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt-get install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg\n"
        )
    if shutil.which("ffprobe") is None:
        raise FfmpegNotFoundError("ffprobe was not found on PATH (it ships with ffmpeg).")


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run a subprocess command, raising FfmpegError with stderr on failure."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise FfmpegError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n--- stderr ---\n{proc.stderr[-4000:]}"
        )
    return proc


@dataclass
class ProbeResult:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe(path: str) -> ProbeResult:
    """Return duration/width/height/has_audio for a media file via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=width,height,codec_type",
        "-of", "json",
        path,
    ]
    proc = run(cmd)
    data = json.loads(proc.stdout)
    duration = float(data.get("format", {}).get("duration", 0.0))
    width = height = 0
    has_audio = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and not width:
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
        if stream.get("codec_type") == "audio":
            has_audio = True
    return ProbeResult(duration=duration, width=width, height=height, has_audio=has_audio)


def detect_scene_changes(path: str, threshold: float = 0.4) -> List[float]:
    """Return a list of timestamps (seconds) where ffmpeg's scene-detection
    filter thinks the shot changed. Useful as a *starting point* for
    `suggest-cuts` -- always eyeball the results, auto-detection is not
    perfect on handheld shop footage with a lot of camera motion.
    """
    cmd = [
        "ffmpeg", "-i", path,
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # ffmpeg writes showinfo to stderr regardless of return code conventions here;
    # a nonzero return with no showinfo lines means a real failure.
    timestamps = []
    for line in proc.stderr.splitlines():
        if "pts_time:" in line:
            for token in line.split():
                if token.startswith("pts_time:"):
                    try:
                        timestamps.append(float(token.split(":", 1)[1]))
                    except ValueError:
                        pass
    if not timestamps and proc.returncode != 0:
        raise FfmpegError(
            f"scene detection failed: {' '.join(cmd)}\n--- stderr ---\n{proc.stderr[-4000:]}"
        )
    return timestamps


def build_trim_cmd(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    fast_copy: bool = False,
    extra_video_filters: Optional[str] = None,
    extra_output_args: Optional[List[str]] = None,
) -> List[str]:
    """Build an ffmpeg command that trims [start, end) out of input_path.

    fast_copy=True uses stream copy (near-instant, but the cut may land up
    to one keyframe early/late). fast_copy=False re-encodes for a frame
    accurate cut, which is what you want once you're happy with the cut
    points and are ready to publish.
    """
    duration = end - start
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", input_path, "-t", f"{duration:.3f}"]
    if fast_copy and not extra_video_filters:
        cmd += ["-c", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]
        if extra_video_filters:
            cmd += ["-vf", extra_video_filters]
    if extra_output_args:
        cmd += extra_output_args
    cmd.append(output_path)
    return cmd


def trim(input_path: str, output_path: str, start: float, end: float, fast_copy: bool = False) -> None:
    require_ffmpeg()
    cmd = build_trim_cmd(input_path, output_path, start, end, fast_copy=fast_copy)
    run(cmd)
