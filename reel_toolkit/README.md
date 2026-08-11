# reel_toolkit

Cut raw shop footage into Instagram Reels, edit them (vertical crop,
captions, logo watermark, background music, loudness normalization), and
follow a ready-made filming/scripting playbook — built for an auto body
shop's social media, but generic enough for any small business.

## What's here

```
reel_toolkit/
  models.py       Plain dataclasses: CutSpec, EditOptions, CaptionSpec, WatermarkSpec, Clip
  ffmpeg_utils.py  subprocess wrapper around ffmpeg/ffprobe (the only I/O boundary)
  splitter.py      Cut a source video into clips: explicit timestamps, equal-length
                   auto segments, or scene-change auto-detection
  editor.py        Vertical crop/pad, captions, watermark, music mix, loudness
                   normalization, fade in/out, duration clamp -- builds the ffmpeg
                   filter graph and command
  pipeline.py       Batch runner: one JSON config -> split + edit every clip -> manifest.json
  cli.py            `python -m reel_toolkit.cli ...`
  content/
    filming_playbook.md   Content pillars, 7 ready-to-shoot scripts (hook / shot
                           list / captions / audio / CTA), filming technical
                           basics, posting cadence, hashtags, 4-week calendar
  examples/
    project_config.json   Example batch config
```

Content pillars and shot-by-shot scripts written for the shop's actual
subject matter (collision repair, paintless dent removal, paint booth,
customer reveals) live in **[`content/filming_playbook.md`](content/filming_playbook.md)** --
read that first if you're the one filming/posting, not writing code.

## Requirements

- Python 3.9+
- **`ffmpeg` and `ffprobe` installed and on PATH** (this toolkit shells out
  to them rather than bundling a video engine):
  ```bash
  brew install ffmpeg          # macOS
  sudo apt-get install ffmpeg  # Ubuntu/Debian
  winget install Gyan.FFmpeg   # Windows
  ```
- No extra Python packages required (stdlib only). The repo's
  `requirements.txt` covers the unrelated `suspension_predictor` app, not
  needed for this toolkit.

## Quickstart

```bash
# 1. See what you've got
python -m reel_toolkit.cli probe raw/job123.mp4

# 2. (optional) auto-suggest cut points, then hand-edit the JSON it writes
python -m reel_toolkit.cli suggest-cuts raw/job123.mp4 --out cuts.json

# 3. Cut the raw video into clips
python -m reel_toolkit.cli split raw/job123.mp4 cuts.json --out-dir clips/

# 4. Make one clip a finished, publish-ready Reel
python -m reel_toolkit.cli edit clips/01-before-teardown.mp4 \
  --out final/01-reel.mp4 \
  --caption-top "They said it was totaled..." \
  --caption-bottom "Free estimates -- link in bio" \
  --watermark assets/logo.png \
  --music assets/music/upbeat_bed.mp3 \
  --max-duration 45

# --- or do the whole job in one shot from a config file ---
python -m reel_toolkit.cli batch reel_toolkit/examples/project_config.json
```

`batch` mode reads a JSON config describing the source video, the cuts (or
an auto-segment length), global edit settings, and per-clip caption/edit
overrides keyed by cut label. See `examples/project_config.json` for the
full shape. It writes finished clips to `<output_dir>/final/` and a
`manifest.json` summarizing what was produced.

## Design notes

- **No cut is destructive.** `split` always writes new files; your raw
  footage is never modified in place.
- **`--fast` on `split`** stream-copies instead of re-encoding, so you can
  preview candidate cuts in seconds. Leave it off for the final pass —
  stream copy snaps to the nearest keyframe, so cut points can be off by a
  fraction of a second.
- **Scene auto-detection is a starting point, not an answer.** Shop
  footage has a lot of camera motion, sparks, and reflective paint, all of
  which cause false positives. Always review `suggest-cuts` output before
  splitting from it.
- **Vertical crop vs. pad:** `--fit-mode crop` (default) fills the 9:16
  frame and crops overflow — looks intentional, is what most Reels do.
  `--fit-mode pad` fits the whole source frame in with a blurred background
  fill — use it when you can't afford to crop anything out (e.g. a wide
  two-person interview).
- **Captions here are burned-in on-screen text** (hook/CTA overlays), not
  spoken-word auto-captions/subtitles. Add Instagram's built-in auto-caption
  sticker after upload if you also want word-by-word spoken captions.

## Testing

```bash
pytest tests/test_reel_toolkit.py -q
```

All tests run without ffmpeg installed — the ffmpeg/ffprobe subprocess
calls are mocked at the `ffmpeg_utils` boundary, and the filter-graph and
command-building logic is tested as pure string output.
