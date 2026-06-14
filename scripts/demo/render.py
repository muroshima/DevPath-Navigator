#!/usr/bin/env python3
"""Render a final demo MP4 from a Playwright recording + a narration cue file.

Usage:
    python render.py 30s
    python render.py 90s

Pipeline:
    1. Read narration/<name>.ja.json (voice, rate, cues with `at` and `text`)
    2. For each cue, run `uvx edge-tts ... --write-media <tmp>.mp3` to render
    3. Probe each cue's duration with ffprobe
    4. Build a single combined audio track by laying each cue at its `at`
       offset against a silent base
    5. Mux the audio with the most recent Playwright video for the named
       spec (output/raw/<spec>/.../video.webm)
    6. Write output/<name>.mp4

This script intentionally avoids editing the video itself — the Playwright
spec is the source of timing truth. Re-record by running
`npm run record:<name>` from this directory; re-render audio by editing
the narration JSON and rerunning this script.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
NARRATION_DIR = ROOT / "narration"
RAW_DIR = OUTPUT_DIR / "raw"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Wrap subprocess.run to fail loud on errors."""
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=False, **kwargs)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed (exit {proc.returncode}): {' '.join(cmd)}")
    return proc


def find_videos(spec_name: str) -> list[Path]:
    """Playwright writes one video per test under a hashed directory.

    Returns videos for `spec_name` sorted in test-definition order. The
    `90s` spec has multiple tests (`90s part 1: ...`, `90s part 2: ...`)
    so the resulting list contains multiple entries that will be
    concatenated before muxing. The `30s` spec has one test and returns
    a single-element list.

    Sorting by directory name keeps the order stable across runs.
    """
    candidates: list[Path] = []
    for p in RAW_DIR.rglob("*.webm"):
        if spec_name in str(p.parent.name):
            candidates.append(p)
    if not candidates:
        raise RuntimeError(
            f"No recording found under {RAW_DIR} that matches '{spec_name}'. "
            f"Did you run `npm run record:{spec_name}` first?"
        )
    return sorted(candidates, key=lambda p: p.parent.name)


def concat_videos(videos: list[Path], out_path: Path) -> Path:
    """Concatenate multiple WebM clips into one via ffmpeg's concat demuxer.

    The concat demuxer copies streams without re-encoding when codecs
    match, which is the case for Playwright recordings (all chromium,
    same viewport, same codec). Returns `out_path`.
    """
    if len(videos) == 1:
        return videos[0]
    list_path = out_path.with_suffix(".concat-list.txt")
    list_path.write_text("\n".join(f"file '{v.resolve()}'" for v in videos))
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(out_path),
    ])
    list_path.unlink(missing_ok=True)
    return out_path


def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds via ffprobe."""
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(out.decode().strip())


def render_tts_cue(text: str, voice: str, rate: str, out_path: Path) -> None:
    """Render one narration cue to an mp3 via edge-tts (uvx managed)."""
    run([
        "uvx", "edge-tts",
        "--voice", voice,
        "--rate", rate,
        "--text", text,
        "--write-media", str(out_path),
    ])


def build_audio_track(
    cues: list[dict],
    voice: str,
    rate: str,
    total_duration: float,
    tmpdir: Path,
) -> Path:
    """Place each cue at its `at` offset onto a silent track of `total_duration`.

    Each cue input is delayed with the `adelay` filter (milliseconds),
    THEN mixed with `amix`. `-itsoffset` on the input doesn't compose
    with `amix` the way it does with `-c copy` muxing — amix reads
    every input from t=0 regardless of `-itsoffset`, so the previous
    version layered every cue on top of cue 00 at the same starting
    moment. `adelay=Nms|Nms` (per channel for stereo) is the correct
    primitive: it inserts N milliseconds of silence at the head of
    each input stream before mixing.
    """
    cue_files: list[tuple[float, Path]] = []
    for idx, cue in enumerate(cues):
        cue_path = tmpdir / f"cue_{idx:02d}.mp3"
        render_tts_cue(cue["text"], voice, rate, cue_path)
        cue_files.append((float(cue["at"]), cue_path))

    cmd = ["ffmpeg", "-y"]
    # Base track: silent stereo for the whole duration. This guarantees
    # the mixed output is exactly `total_duration` long (mixed-in cues
    # that would otherwise end earlier won't truncate the result).
    cmd += ["-f", "lavfi", "-t", f"{total_duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    for _offset, path in cue_files:
        cmd += ["-i", str(path)]

    # Build the filter graph: each cue gets `adelay` (ms per channel),
    # then everything (silent base + delayed cues) goes through `amix`.
    delay_chains: list[str] = []
    labels: list[str] = ["[0:a]"]  # silent base
    for idx, (offset, _path) in enumerate(cue_files, start=1):
        ms = int(round(offset * 1000))
        label = f"[a{idx}]"
        delay_chains.append(f"[{idx}:a]adelay={ms}|{ms},apad{label}")
        labels.append(label)
    mix = f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first[mix]"
    # apad on each cue keeps amix from cutting it off at the cue's
    # natural end; the silent base + duration=first clamps the whole
    # mix to total_duration anyway.
    filtergraph = ";".join(delay_chains + [mix])
    cmd += ["-filter_complex", filtergraph, "-map", "[mix]"]
    cmd += ["-c:a", "aac", "-b:a", "192k"]
    out_path = tmpdir / "combined.aac"
    cmd += [str(out_path)]
    run(cmd)
    return out_path


def mux(video_path: Path, audio_path: Path, out_path: Path) -> None:
    """Combine the original video stream with the new audio track."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Re-encode the video to h264 so the final file plays everywhere
    # (WebM/VP8 plays in browsers but Quicktime hates it). Audio is
    # already AAC from build_audio_track, so just copy.
    run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", choices=["30s", "90s"],
                    help="which demo to render (matches narration/<name>.ja.json)")
    args = ap.parse_args()

    if shutil.which("uvx") is None:
        print("ERROR: `uvx` not on PATH. Install uv first: https://docs.astral.sh/uv/", file=sys.stderr)
        return 1
    if shutil.which("ffmpeg") is None:
        print("ERROR: `ffmpeg` not on PATH. brew install ffmpeg", file=sys.stderr)
        return 1

    narration_path = NARRATION_DIR / f"{args.name}.ja.json"
    if not narration_path.exists():
        print(f"ERROR: narration file not found: {narration_path}", file=sys.stderr)
        return 1
    with narration_path.open() as f:
        narration = json.load(f)

    videos = find_videos(args.name)
    print(f"found {len(videos)} clip(s) for '{args.name}':")
    for v in videos:
        print(f"  {v} ({ffprobe_duration(v):.2f}s)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    final_path = OUTPUT_DIR / f"{args.name}.mp4"
    with tempfile.TemporaryDirectory() as tmpdir:
        concat_path = Path(tmpdir) / "combined.webm"
        video_path = concat_videos(videos, concat_path)
        duration = ffprobe_duration(video_path)
        print(f"combined duration: {duration:.2f}s")

        audio = build_audio_track(
            cues=narration["cues"],
            voice=narration["voice"],
            rate=narration.get("rate", "+0%"),
            total_duration=duration,
            tmpdir=Path(tmpdir),
        )
        mux(video_path, audio, final_path)

    print(f"\nwrote: {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
