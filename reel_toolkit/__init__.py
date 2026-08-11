"""reel_toolkit -- cut, edit, and plan Instagram Reels from raw shop footage.

Built for an auto body shop's social media workflow:

1. `splitter`  -- cut a long raw clip (a phone recording of a repair, a
   walkaround, a customer interview) into Reels-length pieces, either from
   an explicit timestamp list or auto-detected scene changes.
2. `editor`    -- take a cut clip and make it Reels-ready: vertical 9:16
   frame, burned-in captions, logo watermark, loudness normalization,
   optional background music bed, fade in/out.
3. `pipeline`  -- run split + edit end-to-end from a single JSON project
   config, so a whole batch of raw footage turns into a folder of
   publish-ready .mp4 files plus a manifest.
4. `content/`  -- not code: the actual filming playbook, shot lists, and
   ready-to-read scripts for the shop's video team.

Everything here shells out to `ffmpeg`/`ffprobe` (must be installed and on
PATH) rather than pulling in a heavy Python video-editing dependency, so it
stays fast and easy to run on a laptop or a small server.
"""

__version__ = "0.1.0"
