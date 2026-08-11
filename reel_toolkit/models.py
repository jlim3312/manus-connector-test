"""Plain dataclasses shared across reel_toolkit. No I/O, no ffmpeg calls --
kept import-light so tests can exercise the logic without ffmpeg installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def parse_timecode(value) -> float:
    """Accept seconds as a number, or 'MM:SS' / 'HH:MM:SS' / 'HH:MM:SS.ms'
    strings, and return seconds as a float.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise TypeError(f"timecode must be a number or string, got {type(value)!r}")
    parts = value.strip().split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    raise ValueError(f"unparseable timecode: {value!r}")


def format_timecode(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


# Instagram Reels constraints (as of 2025-2026 guidance): up to 3 minutes for
# regular uploads, but 7-90s is the sweet spot for reach/completion rate on
# short-form, punchy content like this shop will be posting.
REELS_MIN_SECONDS = 3.0
REELS_MAX_SECONDS = 90.0
REELS_RECOMMENDED_MAX = 60.0
REELS_ASPECT = (9, 16)
REELS_WIDTH = 1080
REELS_HEIGHT = 1920


@dataclass
class CutSpec:
    """One requested cut out of a source video."""

    start: float          # seconds
    end: float             # seconds
    label: str = ""        # used to name the output file

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError(
                f"cut '{self.label or '?'}' has end ({self.end}) <= start ({self.start})"
            )

    @property
    def duration(self) -> float:
        return self.end - self.start

    @classmethod
    def from_dict(cls, d: dict) -> "CutSpec":
        return cls(
            start=parse_timecode(d["start"]),
            end=parse_timecode(d["end"]),
            label=str(d.get("label", "")),
        )


@dataclass
class WatermarkSpec:
    path: str
    position: str = "bottom_right"   # top_left/top_right/bottom_left/bottom_right/center
    opacity: float = 0.85
    margin_px: int = 32
    scale_width_px: Optional[int] = 220   # None = use image's native size

    def __post_init__(self):
        valid = {"top_left", "top_right", "bottom_left", "bottom_right", "center"}
        if self.position not in valid:
            raise ValueError(f"watermark position must be one of {valid}, got {self.position!r}")
        if not (0.0 <= self.opacity <= 1.0):
            raise ValueError("watermark opacity must be between 0 and 1")


@dataclass
class CaptionSpec:
    text: str
    position: str = "top"     # "top" or "bottom"
    font_path: Optional[str] = None    # None = ffmpeg's default font
    font_size: int = 64
    font_color: str = "white"
    box_color: str = "black@0.55"
    margin_px: int = 90

    def __post_init__(self):
        if self.position not in ("top", "bottom"):
            raise ValueError("caption position must be 'top' or 'bottom'")


@dataclass
class EditOptions:
    """Everything that turns a raw cut clip into a publish-ready vertical Reel."""

    target_width: int = REELS_WIDTH
    target_height: int = REELS_HEIGHT
    fit_mode: str = "crop"          # "crop" (fill frame, crop overflow) or "pad" (blurred bars)
    max_duration: Optional[float] = REELS_MAX_SECONDS
    min_duration: Optional[float] = None
    captions: list = field(default_factory=list)      # list[CaptionSpec]
    watermark: Optional[WatermarkSpec] = None
    music_path: Optional[str] = None
    music_volume_db: float = -18.0   # music mixed in quiet, under original audio
    duck_original_audio_db: float = 0.0  # extra attenuation on original track when music is added
    normalize_loudness: bool = True
    fade_seconds: float = 0.4        # video+audio fade in/out; 0 disables
    output_format: str = "mp4"
    video_bitrate: Optional[str] = None   # e.g. "6M"; None = let CRF decide
    crf: int = 20

    def __post_init__(self):
        if self.fit_mode not in ("crop", "pad"):
            raise ValueError("fit_mode must be 'crop' or 'pad'")
        if self.target_width <= 0 or self.target_height <= 0:
            raise ValueError("target dimensions must be positive")


@dataclass
class Clip:
    """A file on disk that resulted from a split or edit step."""

    path: str
    label: str
    duration: float
    source: Optional[str] = None
