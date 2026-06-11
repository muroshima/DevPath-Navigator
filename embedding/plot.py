"""Render a static 2D cluster map PNG from BigQuery umap_coords + clusters.

Reads umap_coords (one point per employee) and clusters (one row per cluster)
and produces a matplotlib scatter plot colored by cluster_id, with archetype
purity annotated at each cluster centroid.

Usage:
    python embedding/plot.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "cluster_map.png"

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013")
DEFAULT_LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast1")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "devpath")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--title", default="DevPath Navigator — career clusters (synthetic initial batch)")
    args = ap.parse_args()

    client = bigquery.Client(project=args.project, location=args.location)
    coords_rows = list(client.query(
        f"SELECT x, y, cluster_id, archetype FROM `{client.project}.{args.dataset}.umap_coords`"
    ).result())
    cluster_rows = list(client.query(
        f"SELECT cluster_id, size, dominant_archetype, archetype_purity, centroid_x, centroid_y "
        f"FROM `{client.project}.{args.dataset}.clusters`"
    ).result())
    if not coords_rows:
        print("ERROR: no umap_coords rows. Run embedding/umap_cluster.py first.", file=sys.stderr)
        return 1

    xs = np.array([r.x for r in coords_rows])
    ys = np.array([r.y for r in coords_rows])
    cids = np.array([r.cluster_id for r in coords_rows])

    unique = sorted({int(c) for c in cids})
    # Discrete palette: noise (-1) in grey, real clusters in tab10
    palette = plt.colormaps["tab10"]
    color_map: dict[int, tuple] = {}
    real = [c for c in unique if c >= 0]
    for i, c in enumerate(real):
        color_map[c] = palette(i % palette.N)
    if -1 in unique:
        color_map[-1] = (0.7, 0.7, 0.7, 0.6)

    fig, ax = plt.subplots(figsize=(12, 9), dpi=120)
    for c in unique:
        mask = cids == c
        if c == -1:
            label = f"noise (n={int(mask.sum())})"
            ax.scatter(xs[mask], ys[mask], s=10, c=[color_map[c]], label=label, alpha=0.5)
        else:
            cluster_meta = next((r for r in cluster_rows if r.cluster_id == c), None)
            dom = cluster_meta.dominant_archetype if cluster_meta else "?"
            purity = cluster_meta.archetype_purity if cluster_meta else 0
            label = f"#{c} {dom} ({purity:.0%} purity, n={int(mask.sum())})"
            ax.scatter(xs[mask], ys[mask], s=18, c=[color_map[c]], label=label, alpha=0.85,
                       edgecolors="white", linewidths=0.3)

    for cluster_meta in cluster_rows:
        if cluster_meta.cluster_id < 0:
            continue
        ax.annotate(
            f"#{cluster_meta.cluster_id}",
            (cluster_meta.centroid_x, cluster_meta.centroid_y),
            fontsize=11, fontweight="bold", ha="center", va="center",
            color="black",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="black", alpha=0.85),
        )

    ax.set_title(args.title, fontsize=13)
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend(loc="best", fontsize=8, framealpha=0.9, title="Cluster (dominant archetype)")
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, bbox_inches="tight")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
