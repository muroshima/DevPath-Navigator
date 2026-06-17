"""Persist evaluation metrics to BigQuery and read history for the gate.

The history table (`eval_results`) is the canonical record of every retrain
attempt: when it ran, which batches were in scope, what metrics it produced,
and whether the gate let it ship to Cloud Run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import SchemaField
from google.cloud.exceptions import NotFound

EVAL_TABLE = "eval_results"

SCHEMA = [
    SchemaField("run_id", "STRING", mode="REQUIRED"),
    SchemaField("run_at", "TIMESTAMP", mode="REQUIRED"),
    SchemaField("batches", "STRING", mode="REPEATED"),
    SchemaField("recall_at_10", "FLOAT64", mode="REQUIRED"),
    SchemaField("n_clusters", "INT64", mode="REQUIRED"),
    SchemaField("n_noise", "INT64", mode="REQUIRED"),
    SchemaField("mean_archetype_purity", "FLOAT64", mode="REQUIRED"),
    SchemaField("archetypes_covered", "STRING", mode="REPEATED"),
    SchemaField("vocab_size", "INT64", mode="REQUIRED"),
    SchemaField("held_out_n", "INT64", mode="REQUIRED"),
    SchemaField("decision", "STRING", mode="REQUIRED"),       # pass | fail | baseline
    SchemaField("decision_reasons", "STRING", mode="REPEATED"),
    SchemaField("notes", "STRING", mode="NULLABLE"),
    # Minimum Recall@10 across archetypes. NULLABLE so rows written before
    # this column existed (pre-2026-06 runs) read back as None and the
    # gate can fall back to the aggregate-only check.
    SchemaField("min_recall_per_archetype", "FLOAT64", mode="NULLABLE"),
]


@dataclass
class EvalRecord:
    run_id: str
    run_at: datetime
    batches: list[str]
    recall_at_10: float
    n_clusters: int
    n_noise: int
    mean_archetype_purity: float
    archetypes_covered: list[str]
    vocab_size: int
    held_out_n: int
    decision: str
    decision_reasons: list[str]
    notes: str | None = None
    # `None` distinguishes "this run pre-dates the metric" from "metric
    # was 0.0". The gate uses that distinction to skip the per-archetype
    # check on legacy comparisons.
    min_recall_per_archetype: float | None = None


def ensure_table(client: bigquery.Client, dataset: str) -> bigquery.Table:
    table_ref = bigquery.TableReference.from_string(
        f"{client.project}.{dataset}.{EVAL_TABLE}"
    )
    try:
        table = client.get_table(table_ref)
    except NotFound:
        table = bigquery.Table(table_ref, schema=SCHEMA)
        table.description = "DevPath Navigator retraining evaluation history."
        client.create_table(table)
        return client.get_table(table_ref)

    # In-place schema migration: any field in SCHEMA that isn't on the
    # live table gets appended. BigQuery permits adding NULLABLE or
    # REPEATED columns to an existing table without rewriting data, and
    # this lets new metric fields (e.g. min_recall_per_archetype) reach
    # production without a manual ALTER TABLE step. Existing rows keep
    # NULL for the new columns.
    live_names = {f.name for f in table.schema}
    missing = [f for f in SCHEMA if f.name not in live_names]
    if missing:
        table.schema = list(table.schema) + missing
        client.update_table(table, ["schema"])
        table = client.get_table(table_ref)
    return table


def insert_record(client: bigquery.Client, dataset: str, record: EvalRecord) -> None:
    ensure_table(client, dataset)
    table_ref = bigquery.TableReference.from_string(
        f"{client.project}.{dataset}.{EVAL_TABLE}"
    )
    row: dict[str, Any] = asdict(record)
    row["run_at"] = record.run_at.isoformat()
    # Use a load job rather than the streaming insertAll API to avoid the
    # buffer that prevents reads of just-inserted rows.
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    import io
    buf = io.BytesIO((json.dumps(row) + "\n").encode("utf-8"))
    job = client.load_table_from_file(buf, table_ref, job_config=job_config)
    job.result()


def latest_passing(client: bigquery.Client, dataset: str) -> EvalRecord | None:
    """Return the most recent record with decision = 'pass' or 'baseline'."""
    ensure_table(client, dataset)
    sql = f"""
    SELECT *
    FROM `{client.project}.{dataset}.{EVAL_TABLE}`
    WHERE decision IN ('pass', 'baseline')
    ORDER BY run_at DESC
    LIMIT 1
    """
    rows = list(client.query(sql).result())
    if not rows:
        return None
    r = rows[0]
    # `min_recall_per_archetype` may be NULL on rows written before the
    # column existed, in which case the field is just missing from the
    # row object. Fall back to None.
    min_recall = getattr(r, "min_recall_per_archetype", None)
    return EvalRecord(
        run_id=r.run_id,
        run_at=r.run_at,
        batches=list(r.batches),
        recall_at_10=float(r.recall_at_10),
        n_clusters=int(r.n_clusters),
        n_noise=int(r.n_noise),
        mean_archetype_purity=float(r.mean_archetype_purity),
        archetypes_covered=list(r.archetypes_covered),
        vocab_size=int(r.vocab_size),
        held_out_n=int(r.held_out_n),
        decision=r.decision,
        decision_reasons=list(r.decision_reasons),
        notes=r.notes,
        min_recall_per_archetype=float(min_recall) if min_recall is not None else None,
    )


def history(client: bigquery.Client, dataset: str, limit: int = 50) -> list[dict[str, Any]]:
    """Retraining evaluation history. READ-ONLY — does not migrate schema.

    Schema migration (`ensure_table`'s `update_table` call) requires
    `bigquery.tables.update`, which is `dataEditor`-level. The agent
    runtime SA only has dataset-scoped `dataViewer`, so calling
    `ensure_table` from this read path 403s. Migration is a write-path
    responsibility owned by the retrain pipeline (`insert_record` /
    Cloud Build), which has the right privileges; this function just
    reads what's there.

    If the table doesn't exist yet (retrain pipeline never ran), return
    an empty list rather than raising — the dashboard renders an empty
    state instead of a 500.

    `min_recall_per_archetype` is deliberately omitted from the SELECT:
    the column was added to `SCHEMA` in PR #29 but the live table may
    not have been migrated yet, and the upstream `EvalRunSummary`
    response model doesn't expose it either. Adding it back here would
    re-introduce the read-from-uncreated-column failure mode.
    """
    sql = f"""
    SELECT run_id, run_at, batches, recall_at_10,
           n_clusters, mean_archetype_purity, archetypes_covered, vocab_size,
           decision, decision_reasons
    FROM `{client.project}.{dataset}.{EVAL_TABLE}`
    ORDER BY run_at DESC
    LIMIT {int(limit)}
    """
    try:
        rows = list(client.query(sql).result())
    except NotFound:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "run_id": r.run_id,
            "run_at": r.run_at.isoformat() if r.run_at else None,
            "batches": list(r.batches),
            "recall_at_10": float(r.recall_at_10),
            "n_clusters": int(r.n_clusters),
            "mean_archetype_purity": float(r.mean_archetype_purity),
            "archetypes_covered": list(r.archetypes_covered),
            "vocab_size": int(r.vocab_size),
            "decision": r.decision,
            "decision_reasons": list(r.decision_reasons),
        })
    return out


def now_utc() -> datetime:
    return datetime.now(UTC)
