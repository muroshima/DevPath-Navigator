"""Generate a hero/banner illustration for the README via Vertex AI image gen.

Uses Gemini 3.1 Flash Image (the "Nano Banana 2" successor to gemini-2.5-flash-image).
Saves to docs/hero.png. Idempotent — re-running just overwrites.

Usage:
    uv run python scripts/generate-hero-image.py
    uv run python scripts/generate-hero-image.py --model gemini-3-pro-image
    uv run python scripts/generate-hero-image.py --model imagen-4.0-ultra-generate-001
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types as genai_types

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "hero.png"
DEFAULT_MODEL = "gemini-3.1-flash-image"


HERO_PROMPT = """A wide, cinematic, dark-mode hero illustration for a hackathon project
named "DevPath Navigator" — a career navigator that vectorizes engineer career
trajectories.

Composition:
- A futuristic, minimalist 2D map / starfield as the background
- Tens of small luminous dots arranged in soft, distinct cluster shapes,
  each cluster in a different cool color (teal, emerald, blue, violet, amber)
- A single highlighted "you are here" point glowing brighter, near the
  center-left, with thin elegant arrows curving outward toward 2-3 other
  clusters (recommended next career steps)
- The arrows are dashed glowing lines, like flight paths on a map
- Subtle constellation lines connecting dots inside the same cluster
- Very subtle grid pattern in the background, like a coordinate system

Style:
- Deep navy / slate background (#0b1020 base)
- Glowing accent colors, soft bloom, neon aesthetic but restrained
- High contrast, modern, technical, dignified
- No text or labels in the image at all
- Aspect ratio 16:9, wide banner
- Clean composition with negative space — the kind of cover image used by
  serious technical projects (think: Stripe, Vercel, Linear marketing pages)
- Photorealistic / 3D render quality, NOT cartoony or flat-illustration
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Model id (default {DEFAULT_MODEL}).")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Output path (default {DEFAULT_OUTPUT}).")
    ap.add_argument("--project", default=os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013"))
    ap.add_argument("--location", default=os.environ.get("VERTEX_LOCATION", "us-central1"))
    args = ap.parse_args()

    client = genai.Client(vertexai=True, project=args.project, location=args.location)
    print(f"[hero] generating with model={args.model}…", flush=True)

    # Gemini *_image_* models take a normal generate_content call with the
    # IMAGE modality enabled. Imagen models use the separate generate_images
    # method. Try whichever shape fits the model.
    if "imagen" in args.model.lower():
        resp = client.models.generate_images(
            model=args.model,
            prompt=HERO_PROMPT,
            config=genai_types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
            ),
        )
        if not resp.generated_images:
            print("[hero] no images returned", file=sys.stderr)
            return 1
        img_bytes = resp.generated_images[0].image.image_bytes
    else:
        resp = client.models.generate_content(
            model=args.model,
            contents=HERO_PROMPT,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        img_bytes = None
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                blob = getattr(part, "inline_data", None)
                if blob and blob.data:
                    img_bytes = blob.data
                    break
            if img_bytes:
                break
        if img_bytes is None:
            print("[hero] generate_content returned no image bytes", file=sys.stderr)
            print("[hero] candidates:", resp.candidates, file=sys.stderr)
            return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(img_bytes)
    print(f"[hero] wrote {args.output} ({len(img_bytes):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
