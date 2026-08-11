# Auto Body Shop Reels Playbook

A practical, no-fluff guide for the shop's phone-in-hand video plan: what to
film, how to film it, and how to turn it into posted Reels using the
`reel_toolkit` CLI in this repo.

---

## 1. Why this works for a body shop specifically

Instagram's Reels algorithm rewards **watch-through and rewatches**, not
follower count. A collision repair shop has a structural advantage almost
no other local business has: **built-in before/after transformation and a
process people have never seen up close.** Dent removal, frame pulls, paint
booths, color-matching, and "how'd they even fix that" moments are
naturally satisfying to watch — lean into that instead of generic "we're
open" content.

Two audiences to keep in mind for every video:
- **Bystanders** (the algorithm's cold-traffic reach) — they don't know the
  shop, won't read a caption, and decide in the first 1-2 seconds whether
  to keep watching. This is who the *hook* is for.
- **Future customers** — someone who just got hit, is scared about cost, or
  is choosing a shop off Google/Instagram. This is who the *trust signals*
  (clean shop, real techs, real reviews, clear process) are for.

---

## 2. Content pillars (rotate through these — don't post one type on repeat)

| Pillar | Purpose | Example |
|---|---|---|
| **Transformation** | The core hook — before/after, damage to repair | Bumper repair timelapse, paintless dent removal |
| **Process/education** | Builds trust, answers questions people are afraid to ask | "What actually happens after you drop off your car?" "Insurance total vs. repair — how we decide" |
| **Behind the scenes** | Humanizes the shop, shows real people | Tech mixing paint to match color, morning shop walkthrough |
| **Customer moments** | Social proof | Customer reaction picking up their car, quick testimonial |
| **Quick tips** | Shareable, positions the shop as the expert | "3 things to do at the scene of an accident before calling anyone" |
| **Team/culture** | Recruiting + relatability | Tech intros, "day in the life", shop dog, holiday shoutouts |

Rough posting mix: **40% transformation, 25% process/education, 15% behind
the scenes, 10% customer moments, 10% tips/culture.**

---

## 3. Filming technical basics (read this once, then it's muscle memory)

**Camera**
- Shoot **vertical (9:16)**, phone held normally (not sideways). `reel_toolkit`
  will crop/reframe horizontal footage, but native vertical always looks
  sharper and needs less cropping.
- Shoot in **4K if the phone supports it**, even though the final export is
  1080x1920 — it gives room to crop/reframe in editing without losing quality.
- Clean the lens. Shop dust and fingerprints ruin more shop footage than
  anything else.
- Use a cheap phone tripod or a mini gorilla-pod clamp for any shot longer
  than ~15 seconds (timelapses, interviews) — handheld shake reads as
  unprofessional and also confuses the auto scene-detection in this toolkit.

**Lighting**
- Natural light near a bay door beats shop fluorescents — if possible,
  film transformation shots near an open bay in daylight.
- Avoid mixed lighting in one shot (half fluorescent, half daylight) —
  causes color banding that's hard to fix in post.
- For paint booth shots, the booth lighting is usually already good — don't
  add another light source.

**Audio**
- Get **natural shop sound** (sanders, spray guns, air tools) — it's part
  of the appeal, don't talk over it constantly.
- For interviews/testimonials, get within 2-3 feet of the person, or use a
  cheap clip-on lav mic ($20-30) if doing these regularly — phone mic audio
  from more than a few feet away sounds noticeably worse on a loud shop floor.
- Always grab **10-15 seconds of "room tone"** (ambient shop sound with
  nobody talking) per location — useful as a music-bed alternative or to
  smooth audio cuts.

**Framing**
- Leave headroom for a top caption and don't let the subject's face sit in
  the bottom third — that's where a bottom caption/CTA will land.
- For before/after: **shoot both from the identical camera position and
  angle.** Tape a mark on the floor if needed. Mismatched angles make the
  transformation less convincing, not more.
- Get close on hands/tools during process shots — wide shots of a whole bay
  read as boring; a close-up of a sander on a dent reads as satisfying.

**Shot variety (b-roll checklist — grab these on every job, even if the
final reel doesn't end up using all of them):**
- [ ] Wide establishing shot of the vehicle as it arrives
- [ ] Close-up of the specific damage
- [ ] Hands-on-tool close-ups (sanding, pulling, spraying)
- [ ] A slow pan or push-in on the vehicle mid-repair
- [ ] Paint mixing / color-match swatch
- [ ] Booth shot (paint gun in motion if safe/allowed through the window)
- [ ] Final reveal — same angle as the "before" shot
- [ ] A 3-5 second static "hero" shot of the finished vehicle, good light

---

## 4. Ready-to-shoot Reel scripts

Each script gives: the **hook** (first 1-2 sec on screen), the **shot
list** in order, suggested **on-screen captions** (feed straight into
`reel_toolkit edit --caption-top/--caption-bottom`), an **audio** note, and
a **CTA**. Target length is noted per script — keep it tight, most should
land at 15-35 seconds.

### Script 1 — "Total Loss? Watch This" (Transformation, ~25s)
- **Hook (0-2s):** Static close-up of the worst-looking damage, caption:
  `"They said it was totaled..."`
- **Shots:** damage close-up (3s) → wide of full vehicle damage (3s) →
  quick-cut teardown montage (4s) → 2-3 mid-repair moments, fast cuts
  (6s) → paint booth (3s) → reveal, same angle as opening shot (4s) →
  hero shot (2s)
- **Captions:** top: `"They said it was totaled..."` → bottom on reveal:
  `"We said not so fast."`
- **Audio:** upbeat trending audio, cut on the beat at the reveal
- **CTA (last frame, 2s hold):** `"Free estimates — link in bio"`

### Script 2 — "Paintless Dent Removal in Real Time" (Process, ~20s)
- **Hook:** close-up of the dent, hand pointing at it, caption:
  `"No paint. No bondo. Watch."`
- **Shots:** dent close-up (2s) → tech positioning tool behind panel (3s) →
  slow-motion or real-time dent pulling out (8-10s, this IS the content,
  don't rush it) → hand running flat across panel to show it's smooth (3s)
- **Captions:** top only, minimal text — let the visual do the work
- **Audio:** natural shop sound preferred over music here — the satisfying
  "pop" of the dent releasing is the hook
- **CTA:** `"Hail damage? Ask us about PDR — comment DENT for info"`

### Script 3 — "What Happens After You Drop Off Your Car" (Education, ~35s)
- **Hook:** tech walking toward camera in shop, caption:
  `"Here's what actually happens to your car"`
- **Shots:** intake/photo documentation (4s) → teardown/estimate writing
  (4s) → insurance call or paperwork moment (3s) → parts arriving (3s) →
  repair montage (8s) → paint (4s) → quality check/test drive (4s) →
  keys handed back to customer (3s)
- **Captions:** sequential bottom captions as chapters: `"1. Inspect"` →
  `"2. Estimate & insurance"` → `"3. Repair"` → `"4. Paint & finish"` →
  `"5. Quality check"`
- **Audio:** calm, informative trending audio (lower energy than
  transformation reels)
- **CTA:** `"Questions about your claim? DM us"`

### Script 4 — "Color Match Test" (Process/Satisfying, ~15s)
- **Hook:** close-up of paint swatch fan against the car, caption:
  `"Can you tell where the new paint is?"`
- **Shots:** swatch-to-panel comparison (3s) → mixing/tinting close-up
  (4s) → test spray card next to panel (3s) → final panel, seamless blend
  (5s)
- **Captions:** top: the hook line; bottom near end: `"Guess in the
  comments 👇"` (engagement bait that's honest, not misleading)
- **Audio:** trending audio, short and punchy
- **CTA:** `"Tag someone who'd never notice"`

### Script 5 — Customer Reveal Reaction (Social proof, ~15-20s)
- **Hook:** customer walking up to their car, filmed from the side/front
  (get consent before posting — see Section 6)
- **Shots:** customer approaching (3s) → reaction (natural, unscripted,
  3-6s) → customer running hand over the repaired panel (3s) → short
  on-camera quote if they're willing (5-8s)
- **Captions:** subtitle their quote if audio is usable; otherwise caption
  the moment: `"Come get your baby back 🚗✨"`
- **Audio:** their real reaction audio if decent; otherwise light music
  under it
- **CTA:** `"Ready when you are — link in bio for a free estimate"`

### Script 6 — Tech Intro (Team/culture, ~15s)
- **Hook:** tech looking at camera in the bay, caption: `"Meet [Name],
  our [role]"`
- **Shots:** tech at work, close-up on hands (4s) → quick to-camera intro:
  name, role, how long at the shop, one fun fact (8s) → back to work shot
  (3s)
- **Captions:** name/role as a lower-third style bottom caption
- **Audio:** natural talking audio, no music needed
- **CTA:** `"We're hiring — DM us"` (use only on relevant posts)

### Script 7 — "3 Things to Do After an Accident" (Tips, ~30s)
- **Hook:** to-camera or voiceover over b-roll, caption:
  `"Save this before you need it"`
- **Shots:** can be b-roll of the shop/vehicles while a voiceover or
  on-screen text delivers the 3 tips (safety first, photos, call the shop
  before the tow truck picks a shop for you)
- **Captions:** one tip per 8-10 seconds, bottom caption, numbered
- **Audio:** calm trending audio under a voiceover, or fully text-driven
- **CTA:** `"Save this post — you'll want it later"`

---

## 5. Turning footage into posted Reels with `reel_toolkit`

1. **Film using the shot lists above.** One raw video file per job/scene is
   fine — the toolkit cuts it up.
2. **Check the raw footage:**
   ```bash
   python -m reel_toolkit.cli probe raw/job123.mp4
   ```
3. **Get candidate cut points** (optional — skip if you already know your
   timestamps from the script):
   ```bash
   python -m reel_toolkit.cli suggest-cuts raw/job123.mp4 --out cuts.json
   ```
   Open `cuts.json` and adjust start/end/label by hand — auto-detection is
   a starting point, not gospel.
4. **Split into raw clips:**
   ```bash
   python -m reel_toolkit.cli split raw/job123.mp4 cuts.json --out-dir clips/
   ```
5. **Edit one clip into a finished Reel** (vertical crop, captions, logo,
   music, loudness-normalized, faded, capped at 60s):
   ```bash
   python -m reel_toolkit.cli edit clips/01-before-teardown.mp4 \
     --out final/01-reel.mp4 \
     --caption-top "They said it was totaled..." \
     --caption-bottom "Free estimates -- link in bio" \
     --watermark assets/logo.png --watermark-position bottom_right \
     --music assets/music/upbeat_bed.mp3 \
     --max-duration 45
   ```
6. **Or run the whole job (split + edit for every clip) from one config
   file** — see `reel_toolkit/examples/project_config.json` for the format:
   ```bash
   python -m reel_toolkit.cli batch reel_toolkit/examples/project_config.json
   ```
   This writes finished .mp4s to `<output_dir>/final/` and a
   `manifest.json` listing every clip produced.

**Requires `ffmpeg`/`ffprobe` installed and on PATH** (`brew install
ffmpeg` / `sudo apt-get install ffmpeg`) — the toolkit shells out to them
rather than bundling a video engine.

---

## 6. Posting cadence, captions, hashtags, consent

- **Cadence:** 4-6 Reels/week is a realistic, sustainable target for a
  small shop — consistency beats volume. Batch-film on your busiest repair
  days so you're not scrambling to find content.
- **Caption (the Instagram post caption, not on-screen text):** first line
  is the hook again (it shows before "more..."), then 1-2 sentences of
  context, then a CTA, then hashtags.
- **Hashtags:** mix a few broad ones with local/niche ones each time, e.g.
  `#autobodyrepair #collisionrepair #paintlessdentremoval #[yourcity]cars
  #[yourcitycarcommunity] #bumpertobumper`. Don't reuse the exact same
  block on every post — vary it.
- **Consent:** always get a quick verbal OK ("mind if we post this?") before
  filming a customer's face, license plate, or insurance details on camera.
  Blur or crop plates by default unless the customer is fine with it
  showing. This matters both for privacy and because it looks more
  professional.
- **Insurance/pricing claims:** don't state specific dollar estimates or
  claim outcomes in captions without checking with the shop owner/manager
  first — treat pricing talk as case-by-case, not for public posts.

---

## 7. 4-week starter content calendar

| Week | Mon | Wed | Fri |
|---|---|---|---|
| 1 | Transformation (Script 1) | Process (Script 3, part 1) | Tech intro (Script 6) |
| 2 | Transformation (new job) | Quick tip (Script 7) | Customer reveal (Script 5) |
| 3 | PDR satisfying clip (Script 2) | Process (Script 3, part 2 or new job) | Color match (Script 4) |
| 4 | Transformation (new job) | Tip or education | Team/culture (shop moment, holiday, milestone) |

Repeat the cycle, swapping in whatever real jobs come through the shop that
week — the scripts are templates, not a rigid schedule.
