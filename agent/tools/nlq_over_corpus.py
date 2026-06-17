"""Tool: nlq_over_corpus — translate a natural-language question into a safe BigQuery SELECT.

Safety contract:
  * The generator is asked to emit a single SELECT statement.
  * We strictly validate: must start with SELECT, must not contain any DDL/DML
    keyword, must reference only allow-listed tables, must include a LIMIT.
  * The query is run against the BQ client that holds bigquery.dataViewer only,
    so even if validation is bypassed the worst case is a read-only query.
  * Any validation failure returns an `error` and the rejected SQL for transparency.
"""

from __future__ import annotations

import os
import re

from google import genai
from google.genai import types as genai_types

from agent.state import get_state

ALLOWED_TABLES = {"trajectories", "embeddings", "umap_coords", "clusters"}
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "merge", "grant", "revoke", "call", "execute", "exec",
    # UNION lets a crafted query glue an allowed-table SELECT onto a
    # second SELECT that exfiltrates from elsewhere, or smuggles a
    # hand-built constant set in the same result shape. The allowlist
    # plus the single-statement check already block most of that, but
    # rejecting `union` outright makes the intent explicit and removes
    # a whole class of "what if the table parser missed something"
    # reasoning. Both `union` and `union all` are covered because the
    # match is on the bare `union` word boundary.
    "union",
}
# Anywhere these substrings appear (in the comment-stripped lowercased SQL)
# is an instant reject. INFORMATION_SCHEMA and the BigQuery system tables
# would let an attacker enumerate other datasets, jobs, recent queries, IAM,
# etc. — keep them entirely out of reach.
FORBIDDEN_SUBSTRINGS = (
    "information_schema",
    "__table__",          # BigQuery query history shortcut
    "@@",                 # session vars
    "$(",                 # parameter expansion
    # External / federated / inline-ML escape hatches. These appear as
    # function-style identifiers (e.g. `FROM EXTERNAL_QUERY(...)`) which
    # the table-reference allowlist below can't see — the FROM/JOIN
    # identifier pattern breaks at `(`, so the function call is silently
    # treated as "no tables referenced". Block by substring so they
    # never reach BigQuery regardless of where in the statement they sit.
    "external_query",
    "ml.generate_text",
    "ml.predict",
    "ml.transcribe",
    "ml.translate",
    "object_table",       # BQ object tables read from GCS
    "session_user",       # BQ built-in returns the caller's email
    "region-",            # `region-<id>.INFORMATION_SCHEMA.*` regional shortcut
)
MAX_DEFAULT_LIMIT = 50
# Hard ceiling on the LIMIT literal the validator will allow. The model's
# instruction tells it to use LIMIT 50, but a prompt-injected variant
# emitting `LIMIT 1000000` would still pass the previous "is LIMIT present?"
# check. With MAX_BYTES_BILLED=100MB the corpus fits, so volume-based
# exfiltration is bounded only by the row count — cap it here.
MAX_HARD_LIMIT = 200
MAX_SQL_LENGTH = 2000  # characters
MAX_QUESTION_LENGTH = 1000  # characters of NL input the agent can hand off

# Hard cap on bytes a single NL→SQL query is allowed to scan. The current
# corpus is well under 10 MB across all tables; 100 MB is generous for the
# demo and still bounds the worst case if a future query gets past the
# regex validator and tries to scan something pathological.
MAX_BYTES_BILLED = 100 * 1024 * 1024  # 100 MB

_SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_HASH_COMMENT_RE = re.compile(r"#[^\n]*")  # BigQuery accepts # as a line comment


def _extract_sql(generated: str) -> str:
    """Strip Markdown fences and surrounding text from the generated SQL."""
    m = _SQL_FENCE_RE.search(generated)
    raw = m.group(1) if m else generated
    return raw.strip().rstrip(";").strip()


def _strip_comments(sql: str) -> str:
    """Remove SQL block / line / hash comments before validation.

    Without this, a model could emit `SELECT * FROM t /* DROP TABLE */ ...`
    or `-- DROP TABLE foo` and the keyword-banlist would catch the comment
    text rather than the executable SQL the engine actually sees. Stripping
    comments first means our validation runs against the same logical text
    that BigQuery would execute.
    """
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    sql = _HASH_COMMENT_RE.sub(" ", sql)
    return sql


def _validate_table_refs(sql_lower: str, project: str, dataset: str) -> str | None:
    """Validate every FROM/JOIN reference against the full
    `project.dataset.table` triple, not just the final segment.

    The previous version kept only the last dotted segment and matched it
    against ALLOWED_TABLES. That let a crafted `FROM
    \\`evil-proj.evil_ds.trajectories\\`` slip past — the suffix matched
    the allowlist but the dataset/project did not, so any other project
    where the agent service account had reader (or any future
    other-dataset reader grant) became reachable. We now require the
    fully-qualified triple to match exactly.

    Two-segment refs (`dataset.table`, with no project) are also rejected
    — the production prompt instructs the model to emit fully-qualified
    refs and the BQ client has no default dataset configured.

    Single-identifier refs (no dots) are CTE aliases / hallucinations;
    BigQuery refuses them at execution time, so we skip them here to
    keep `WITH cte AS (...) SELECT * FROM cte` working.
    """
    proj_l = project.lower()
    ds_l = dataset.lower()
    allowed_triples = {f"{proj_l}.{ds_l}.{t}" for t in ALLOWED_TABLES}
    pattern = r"(?:from|join)\s+(?:`([^`]+)`|([a-zA-Z0-9_.\-]+))"
    for m in re.finditer(pattern, sql_lower):
        ref = (m.group(1) or m.group(2) or "").replace("`", "").strip().lower()
        if not ref:
            continue
        parts = ref.split(".")
        if len(parts) == 1:
            continue  # CTE alias / unqualified — BQ rejects at execution
        if len(parts) != 3:
            return (
                f"Table refs must be fully qualified `project.dataset.table`, "
                f"got: {ref}"
            )
        if ref not in allowed_triples:
            return (
                f"Disallowed tables: [{ref!r}]; "
                f"allowed: {sorted(allowed_triples)}"
            )
    return None


def _validate_limit(sql_lower_no_strings: str) -> str | None:
    """Require a LIMIT clause whose numeric literal is within MAX_HARD_LIMIT.

    Previously only the *presence* of `LIMIT` was checked. A model coerced
    into emitting `LIMIT 1000000` would happily return the entire
    `trajectories` table — the corpus fits under `maximum_bytes_billed`, so
    bytes-based caps don't bound row count.
    """
    m = re.search(r"\blimit\s+(\d+)\b", sql_lower_no_strings)
    if not m:
        return "SQL must include LIMIT"
    n = int(m.group(1))
    if n > MAX_HARD_LIMIT:
        return f"LIMIT {n} exceeds hard cap of {MAX_HARD_LIMIT}"
    return None


def _validate_sql(
    sql: str,
    *,
    project: str | None = None,
    dataset: str | None = None,
) -> str | None:
    """Return None if safe, otherwise an error string.

    `project`/`dataset` default to the running agent's BigQuery target
    (`get_state()`); they are kwargs purely for testability — unit tests
    pass explicit fixture values so they don't depend on a configured
    runtime state.
    """
    if len(sql) > MAX_SQL_LENGTH:
        return f"SQL exceeds {MAX_SQL_LENGTH}-character cap ({len(sql)} chars)"
    # Strip comments BEFORE every check so a model can't hide forbidden
    # tokens inside /* ... */ or -- ... .
    stripped = _strip_comments(sql)
    low = stripped.lower()
    if not (low.lstrip().startswith("select") or low.lstrip().startswith("with")):
        return "SQL must start with SELECT or WITH"
    if ";" in stripped.strip(";"):
        return "SQL must be a single statement"
    for needle in FORBIDDEN_SUBSTRINGS:
        if needle in low:
            return f"Forbidden substring: {needle}"
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", low):
            return f"Forbidden keyword: {kw}"

    if project is None or dataset is None:
        state = get_state()
        if project is None:
            project = state.project
        if dataset is None:
            dataset = state.dataset
    err = _validate_table_refs(low, project, dataset)
    if err:
        return err

    # `limit` must appear as its own SQL keyword, not inside a string literal
    # or a column name like `time_limit`. Quick proxy: search the
    # string-literal-stripped form.
    no_strings = re.sub(r"'[^']*'", "''", low)
    return _validate_limit(no_strings)


def _build_nl2sql_prompt(question: str) -> str:
    state = get_state()
    return f"""You translate a single natural-language question about a synthetic engineer-career corpus into a single safe BigQuery SQL SELECT (or WITH) statement.

Hard rules:
- Output ONLY the SQL inside a ```sql code block. No prose before or after.
- Use ONLY these tables (fully-qualified):
  * `{state.project}.{state.dataset}.trajectories` — columns: employee_id STRING, step INT64, roles ARRAY<STRUCT<role STRING, years FLOAT64>>, tech_stack ARRAY<STRING>, seniority STRING, archetype STRING, batch_id STRING
    Use UNNEST(roles) AS r when filtering on a specific role. For example: WHERE EXISTS (SELECT 1 FROM UNNEST(roles) AS r WHERE r.role = 'genai_engineer').
  * `{state.project}.{state.dataset}.embeddings` — employee_id STRING, vector ARRAY<FLOAT64>, batch_id STRING
  * `{state.project}.{state.dataset}.umap_coords` — employee_id STRING, x FLOAT64, y FLOAT64, cluster_id INT64, archetype STRING, batch_id STRING
  * `{state.project}.{state.dataset}.clusters` — cluster_id INT64, size INT64, dominant_archetype STRING, archetype_purity FLOAT64, centroid_x FLOAT64, centroid_y FLOAT64
- Always include LIMIT {MAX_DEFAULT_LIMIT}.
- Use UNNEST(tech_stack) when filtering by individual tech tokens.
- Single SELECT or WITH only — no DDL, no DML, no procedures, no semicolons inside the body.
- Do not invent columns or tables.

Question: {question.strip()}"""


def nlq_over_corpus(question: str) -> dict:
    """Run a natural-language question against the synthetic corpus via NL→SQL.

    Use this tool when the user asks aggregate or filter-shaped questions that
    cannot be answered by the per-user vector-search tools, e.g. "what's the
    most common tech in cluster #2?", "how many engineers moved from frontend
    to data engineer?", "list clusters with archetype purity below 95%".

    The corpus is synthetic demonstration data only.

    Args:
        question: a single natural-language question.

    Returns:
        On success: {"sql": <the generated SQL>, "rows": [<row>...], "row_count": N}.
        On rejection: {"sql": <generated>, "error": <why>}.
    """
    # Cap the input before paying for a Gemini call. The agent's instruction
    # tells it to send "neutral analytic questions" — anything longer than
    # MAX_QUESTION_LENGTH is almost certainly an attempt to smuggle a much
    # larger prompt or to drain quota.
    if not isinstance(question, str):
        return {"error": "question must be a string", "sql": None}
    if len(question) > MAX_QUESTION_LENGTH:
        return {
            "error": f"question exceeds {MAX_QUESTION_LENGTH}-character cap "
                     f"({len(question)} chars)",
            "sql": None,
        }

    state = get_state()

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", state.project)
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    from agent.agent import build_retry_options
    retry = build_retry_options()
    http_options = (
        genai_types.HttpOptions(retry_options=retry) if retry is not None else None
    )
    client = genai.Client(
        vertexai=True, project=project, location=location, http_options=http_options
    )

    prompt = _build_nl2sql_prompt(question)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0.1),
    )
    if not resp.text:
        return {"error": "NL→SQL model returned no text", "sql": None}

    sql = _extract_sql(resp.text)
    err = _validate_sql(sql)
    if err:
        return {"sql": sql, "error": err}

    try:
        # Cap the bytes BigQuery is allowed to bill for this query. If the
        # query would scan more than MAX_BYTES_BILLED, BigQuery refuses
        # before any data is read — important because this SQL came from
        # an LLM and the regex validator is best-effort.
        from google.cloud import bigquery
        job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
        job = state.bq_client.query(sql, job_config=job_config)
        rows = [dict(r) for r in job.result()]
    except Exception as exc:
        return {"sql": sql, "error": f"BigQuery error: {exc}"}

    # Normalize row values for JSON serialization (lists, etc.)
    normalized: list[dict] = []
    for r in rows:
        out: dict = {}
        for k, v in r.items():
            if isinstance(v, (list, tuple)):
                out[k] = list(v)
            else:
                out[k] = v
        normalized.append(out)

    return {"sql": sql, "rows": normalized, "row_count": len(normalized)}
