"""Compute UMAP 2D projection + HDBSCAN clusters and write to BigQuery.

Pipeline:
  1. Load trajectories from BigQuery
  2. Embed each employee with embed_trajectory() (Word2Vec must be trained first)
  3. UMAP → 2D coordinates
  4. HDBSCAN → cluster labels (cluster_id = -1 means noise)
  5. Write three tables:
     - embeddings: employee_id, vector, batch_id
     - umap_coords: employee_id, x, y, cluster_id, archetype, batch_id
     - clusters: cluster_id, size, dominant_archetype, archetype_purity,
                 centroid_x, centroid_y

Usage:
    python embedding/umap_cluster.py --batches initial
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections import Counter
from pathlib import Path

import hdbscan
import numpy as np
import umap
from google.cloud import bigquery
from google.cloud.bigquery import SchemaField
from google.cloud.exceptions import NotFound

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gensim.models import KeyedVectors

from embedding.tokens import group_trajectory_by_employee
from embedding.trajectory import embed_trajectory

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013")
DEFAULT_LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast1")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "devpath")

DEFAULT_MODEL_PATH = REPO_ROOT / "data" / "embeddings" / "w2v.kv"

UMAP_PARAMS = dict(n_components=2, n_neighbors=15, min_dist=0.1, metric="cosine", random_state=42)
HDBSCAN_PARAMS = dict(min_cluster_size=25, min_samples=5)

EMBEDDINGS_SCHEMA = [
    SchemaField("employee_id", "STRING", mode="REQUIRED"),
    SchemaField("vector", "FLOAT64", mode="REPEATED"),
    SchemaField("batch_id", "STRING", mode="REQUIRED"),
]
UMAP_COORDS_SCHEMA = [
    SchemaField("employee_id", "STRING", mode="REQUIRED"),
    SchemaField("x", "FLOAT64", mode="REQUIRED"),
    SchemaField("y", "FLOAT64", mode="REQUIRED"),
    SchemaField("cluster_id", "INT64", mode="REQUIRED"),
    SchemaField("archetype", "STRING", mode="NULLABLE"),
    SchemaField("batch_id", "STRING", mode="REQUIRED"),
]
CLUSTERS_SCHEMA = [
    SchemaField("cluster_id", "INT64", mode="REQUIRED"),
    SchemaField("size", "INT64", mode="REQUIRED"),
    SchemaField("dominant_archetype", "STRING", mode="NULLABLE"),
    SchemaField("archetype_purity", "FLOAT64", mode="NULLABLE"),
    SchemaField("centroid_x", "FLOAT64", mode="REQUIRED"),
    SchemaField("centroid_y", "FLOAT64", mode="REQUIRED"),
]


def load_trajectories(client: bigquery.Client, dataset: str, batches: list[str]) -> list[dict]:
    sql = f"""
    SELECT employee_id, step, roles, tech_stack, seniority, archetype, batch_id
    FROM `{client.project}.{dataset}.trajectories`
    WHERE batch_id IN UNNEST(@batches)
    ORDER BY employee_id, step
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("batches", "STRING", batches)]
        ),
    )
    return [dict(row) for row in job.result()]


def overwrite_table(
    client: bigquery.Client,
    dataset: str,
    table: str,
    schema: list[SchemaField],
    rows: list[dict],
) -> None:
    table_ref = bigquery.TableReference.from_string(f"{client.project}.{dataset}.{table}")
    with contextlib.suppress(NotFound):
        client.delete_table(table_ref)
    client.create_table(bigquery.Table(table_ref, schema=schema))
    if not rows:
        return
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    import io
    import json
    buf = io.BytesIO()
    for row in rows:
        buf.write((json.dumps(row) + "\n").encode("utf-8"))
    buf.seek(0)
    job = client.load_table_from_file(buf, table_ref, job_config=job_config)
    job.result()
    print(f"  wrote {len(rows):>5d} rows -> {table_ref}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batches", nargs="+", default=["initial"])
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    args = ap.parse_args()

    if not args.model.exists():
        print(f"ERROR: w2v model not found: {args.model}", file=sys.stderr)
        print("Hint: run `python embedding/train_w2v.py` first.", file=sys.stderr)
        return 1

    vectors = KeyedVectors.load(str(args.model))
    client = bigquery.Client(project=args.project, location=args.location)

    rows = load_trajectories(client, args.dataset, args.batches)
    grouped = group_trajectory_by_employee(rows)
    archetype_by_emp = {emp: steps[0]["archetype"] for emp, steps in grouped.items()}
    batch_by_emp = {emp: steps[0]["batch_id"] for emp, steps in grouped.items()}

    employee_ids: list[str] = []
    matrix: list[np.ndarray] = []
    for emp, steps in grouped.items():
        vec = embed_trajectory(steps, vectors)
        if vec is None:
            continue
        employee_ids.append(emp)
        matrix.append(vec)
    if not matrix:
        print("ERROR: no employees could be embedded", file=sys.stderr)
        return 1
    matrix_np = np.stack(matrix)
    print(f"Embedded {matrix_np.shape[0]} employees into dim={matrix_np.shape[1]}")

    print("Running UMAP...")
    reducer = umap.UMAP(**UMAP_PARAMS)
    coords = reducer.fit_transform(matrix_np)

    print("Running HDBSCAN...")
    clusterer = hdbscan.HDBSCAN(**HDBSCAN_PARAMS, prediction_data=False)
    labels = clusterer.fit_predict(coords)
    n_clusters = len({lbl for lbl in labels if lbl >= 0})
    n_noise = int((labels < 0).sum())
    print(f"  HDBSCAN: {n_clusters} clusters, {n_noise} noise points "
          f"({100 * n_noise / len(labels):.1f}%)")

    # Build cluster summaries
    cluster_rows: list[dict] = []
    for cid in sorted(set(labels)):
        mask = labels == cid
        members = [employee_ids[i] for i, m in enumerate(mask) if m]
        arch_counts = Counter(archetype_by_emp[emp] for emp in members)
        dominant, dominant_count = arch_counts.most_common(1)[0] if arch_counts else (None, 0)
        purity = dominant_count / len(members) if members else 0.0
        cluster_rows.append({
            "cluster_id": int(cid),
            "size": int(mask.sum()),
            "dominant_archetype": dominant,
            "archetype_purity": float(purity),
            "centroid_x": float(coords[mask, 0].mean()),
            "centroid_y": float(coords[mask, 1].mean()),
        })

    embeddings_rows = [
        {"employee_id": emp, "vector": matrix_np[i].tolist(), "batch_id": batch_by_emp[emp]}
        for i, emp in enumerate(employee_ids)
    ]
    umap_rows = [
        {
            "employee_id": emp,
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "cluster_id": int(labels[i]),
            "archetype": archetype_by_emp.get(emp),
            "batch_id": batch_by_emp[emp],
        }
        for i, emp in enumerate(employee_ids)
    ]

    print("Writing to BigQuery...")
    overwrite_table(client, args.dataset, "embeddings", EMBEDDINGS_SCHEMA, embeddings_rows)
    overwrite_table(client, args.dataset, "umap_coords", UMAP_COORDS_SCHEMA, umap_rows)
    overwrite_table(client, args.dataset, "clusters", CLUSTERS_SCHEMA, cluster_rows)

    print("\nCluster summary:")
    print(f"  {'cluster':>7s} {'size':>6s} {'dominant_archetype':<22s} {'purity':>7s}")
    for row in sorted(cluster_rows, key=lambda r: (r["cluster_id"] == -1, -r["size"])):
        print(f"  {row['cluster_id']:>7d} {row['size']:>6d} "
              f"{(row['dominant_archetype'] or '—'):<22s} "
              f"{row['archetype_purity']:>7.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
