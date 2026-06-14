# Demo recording pipeline

How the README's 30-second hero and the 90-second submission video are
produced. Everything is scripted — no manual screen capture, no
editing software, no voice-over takes.

## What's here

```
scripts/demo/
├── playwright.config.ts        # 1280×720 recording config
├── tests/
│   ├── fixtures.ts             # canned /api/map, /api/chat, /api/eval-history
│   ├── 30s.spec.ts             # single test → docs/demo-30s.mp4
│   └── 90s.spec.ts             # two tests (home + dashboard) → docs/demo-90s.mp4
├── narration/
│   ├── 30s.ja.json             # cue list: { voice, rate, [{ at, text }, ...] }
│   └── 90s.ja.json
├── render.py                   # ties everything together
└── package.json                # @playwright/test as devDependency
```

## How a single render works

1. **Playwright records** the front-end at 1280×720, slowMo 80 ms, with
   API routes mocked from `fixtures.ts` so the recording is
   deterministic and works without GCP credentials. Output is one
   WebM per test under `output/raw/<test name>/video.webm`.
2. **edge-tts** (invoked via `uvx`) renders each narration cue to MP3
   using a ja-JP Neural voice.
3. **ffmpeg** delays each cue's MP3 by its `at` offset (`adelay` per
   stream), mixes them onto a silent base track, and muxes the result
   with the recorded video. The 90-second spec records two clips
   (home → dashboard) and concatenates them via the concat demuxer
   first; this sidesteps a Playwright quirk where `page.goto` to a
   same-origin URL doesn't carry through to the same video file.

The final MP4 lands at `output/<name>.mp4`.

## Prereqs

```bash
# uv (manages edge-tts and Python deps)
brew install uv         # or curl -LsSf https://astral.sh/uv/install.sh | sh

# ffmpeg (mux + concat + audio mix)
brew install ffmpeg

# Playwright + Chromium
cd scripts/demo
npm install
npx playwright install chromium
```

## Re-render

```bash
cd scripts/demo

# 30-second README hero
npm run record:30s     # writes output/raw/30s-.../video.webm
python3 render.py 30s  # → output/30s.mp4

# 90-second submission video
npm run record:90s     # writes two WebM clips, one per test
python3 render.py 90s  # concat + mux → output/90s.mp4
```

Then copy / commit the resulting MP4s into `docs/` so the README and
submission link to them.

## Editing the script

- **Visual timing** lives in the `.spec.ts` file — `page.waitForTimeout`,
  `keyboard.type({ delay: ... })`, etc. Each spec has block comments
  marking the cue alignment ("`00:18 — 00:25 : hover` → cue 2 plays").
  Tweak these when the narration changes.
- **Narration** lives in `narration/<name>.ja.json`. Edit text and `at`
  offsets together. After a change, re-run `python3 render.py <name>` —
  the recording itself doesn't need to be re-done unless visual
  timing also changed.
- **Voice / rate** are at the top of the narration JSON. `ja-JP-NanamiNeural`
  / `+10%` is the current default. Other voices via
  `uvx edge-tts --list-voices | grep ja-JP`.
- **Cue timing tip** — to measure a cue's actual TTS duration before
  committing to an `at` offset, run:

  ```bash
  uvx edge-tts --voice ja-JP-NanamiNeural --rate +10% \
    --text "...あなたのテキスト..." --write-media /tmp/check.mp3
  ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 /tmp/check.mp3
  ```

## Known limitations

- The `output: standalone` Next.js config emits a warning when the
  webServer runs `npm run build && npm run start`. Recording still
  works — the warning is informational.
- Playwright's text input on React 19 controlled inputs needs the
  production build; `next dev` interferes with synthetic input events
  fired from outside React.
- WebM keyframe granularity (~5 s) means `ffmpeg -ss N -i video.webm`
  seeks coarsely. Use `ffmpeg -i video.webm -ss N` (input first, seek
  after) for frame-accurate inspection.
