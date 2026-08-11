# reel_toolkit

Cut raw shop footage into Instagram Reels, edit them (vertical crop,
captions, logo watermark, background music, loudness normalization), and
follow a ready-made filming/scripting playbook — built for an auto body
shop's social media, but generic enough for any small business.

## What's here

```
reel_toolkit/
  models.py       Plain dataclasses: CutSpec, EditOptions, CaptionSpec, WatermarkSpec, Clip
  ffmpeg_utils.py  subprocess wrapper around ffmpeg/ffprobe (the only ffmpeg I/O boundary)
  caption_render.py  Renders caption text to a transparent PNG with Pillow (see
                   "Why Pillow for captions?" below)
  splitter.py      Cut a source video into clips: explicit timestamps, equal-length
                   auto segments, or scene-change auto-detection
  editor.py        Vertical crop/pad, color grading, caption/watermark overlay, music
                   mix, loudness normalization, fade in/out, duration clamp -- builds
                   the ffmpeg filter graph and command
  stitcher.py       Combine multiple clips into one Reel with a transition (crossfade,
                   wipe, etc.) at each cut, instead of separate clip files
  pipeline.py       Batch runner: one JSON config -> split + edit every clip -> manifest.json
  cli.py            `python -m reel_toolkit.cli ...`
  webapp/
    main.py         FastAPI backend for a local drag-and-drop web UI
    static/index.html  The drag-and-drop page itself (upload, form, results)
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

## Drag-and-drop web UI (no command line needed after setup)

For anyone on the team who'd rather not touch a terminal, there's a local
web app: drop in a video, fill in a short form (captions, logo, music,
how to cut it, color, optional transitions), click **Process video**,
then preview and download the finished Reels right in the browser.
"Auto-enhance colors" is on by default -- the tool figures out color
correction from the footage itself, no sliders required unless you want
to fine-tune manually.

```bash
pip install -r requirements.txt          # fastapi/uvicorn, from repo root
uvicorn reel_toolkit.webapp.main:app --reload --port 8000
```

Then open **http://127.0.0.1:8000** in a browser. One person needs to run
that one command (leave the terminal window open while it's in use) --
after that, everyone on that machine/network can use the web page.

Notes:
- This is a **local** tool, not something to expose on the open internet
  as-is -- there's no login and no upload size limit.
- Output for each run lands in `reel_toolkit/webapp/jobs/<job_id>/final/`
  (gitignored) as well as being downloadable from the page.
- Same engine as the CLI underneath -- anything the web UI can't do
  (scene-detection auto cut suggestions, batch project configs) is still
  available via `reel_toolkit.cli`.

## Requirements

- Python 3.9+
- **`ffmpeg` and `ffprobe` installed and on PATH** (this toolkit shells out
  to them rather than bundling a video engine):
  ```bash
  brew install ffmpeg          # macOS
  sudo apt-get install ffmpeg  # Ubuntu/Debian
  winget install Gyan.FFmpeg   # Windows
  ```
- **Python packages:** `pip install -r requirements.txt` from the repo
  root (this covers the unrelated `suspension_predictor` app too, but also
  includes everything reel_toolkit needs -- fastapi/uvicorn for the web UI
  and Pillow for caption rendering).

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

# --- or combine several cuts into ONE Reel with a transition at each cut ---
python -m reel_toolkit.cli stitch clips/01-before.mp4 clips/02-process.mp4 clips/03-after.mp4 \
  --out final/combined-reel.mp4 --transition fade --transition-duration 0.5 \
  --auto-enhance --caption-top "Before -> Process -> After"

# --- or do the whole job in one shot from a config file ---
python -m reel_toolkit.cli batch reel_toolkit/examples/project_config.json
```

## Color grading

`--auto-enhance` analyzes each frame's actual histogram and corrects
levels/color automatically (no numbers to figure out) -- it's the
recommended default and is what the web UI's "Auto-enhance colors"
checkbox uses. For direct manual control instead (or on top of it),
`edit` and `stitch` both also take `--saturation`, `--contrast`,
`--brightness`, and `--warmth KELVIN` (e.g. `--warmth 4500` for warmer,
`--warmth 8500` for cooler).

## Transitions

`stitch` combines 2+ clips into one continuous video instead of leaving
them as separate files -- e.g. a single before → process → after Reel
with a crossfade at each cut. Pick `--transition` from `fade`,
`fadeblack`, `fadewhite`, `dissolve`, `wipeleft`/`wiperight`/`wipeup`/`wipedown`,
`slideleft`/`slideright`/`slideup`/`slidedown`, `circleopen`/`circleclose`,
`smoothleft`/`smoothright` (or any other valid ffmpeg `xfade` transition
name), and `--transition-duration` for how long each crossfade lasts.
Every clip must be longer than the transition duration. Color
grading/crop happens per-segment during stitching; captions/watermark/
music/loudness/fade apply once, to the whole combined result.

## Music vs. original audio

`--music path/to/track.mp3` mixes a background track in under the clip's
original audio (both `edit` and `stitch`, and the web UI). By default the
original audio stays at full volume alongside it -- if you want the
original sound (shop noise, talking) turned down while the music plays,
add `--duck-original-db -6` (or more negative for quieter); `0`, the
default, leaves it untouched. `--music-volume-db` controls the music
track's own volume the same way.
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
- **Why Pillow for captions, not ffmpeg's drawtext?** drawtext requires
  ffmpeg to have been compiled with libfreetype, which isn't guaranteed --
  notably, Homebrew's default `ffmpeg` formula on macOS currently ships
  *without* it, so `brew install ffmpeg` alone gives you a binary where
  drawtext doesn't exist. Rendering caption text to a PNG with Pillow
  first and compositing it with ffmpeg's `overlay` filter (present in
  every ffmpeg build) sidesteps that entirely -- captions work no matter
  how ffmpeg on that machine was built.
- **`--auto-enhance` deliberately doesn't use ffmpeg's `normalize` filter
  at its default settings.** Full-strength `normalize` stretches each
  frame's actual min/max to pure black/white, which crushes a frame
  dominated by one flat, low-variance color -- e.g. a tight closeup on a
  solid-color panel, exactly the kind of shot a body shop films
  constantly -- to solid black. Confirmed against a real solid-color test
  clip before shipping; `auto_enhance` uses reduced strength with linked
  channels instead (see `editor.color_filters`).

## Testing

```bash
pytest tests/test_reel_toolkit.py -q
```

All tests run without ffmpeg installed — the ffmpeg/ffprobe subprocess
calls are mocked at the `ffmpeg_utils` boundary, and the filter-graph and
command-building logic is tested as pure string output.
