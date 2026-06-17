"""Tests for the NL→SQL safety validator."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.tools.nlq_over_corpus import (
    MAX_HARD_LIMIT,
    MAX_SQL_LENGTH,
    _mask_project_dataset,
    _strip_comments,
    _validate_sql,
)

# Tests pass an explicit (project, dataset) so they don't depend on
# `agent.state.get_state()` being initialized at import time.
_TEST_PROJECT = "proj"
_TEST_DATASET = "devpath"


def _ok(sql: str, *, project: str = _TEST_PROJECT, dataset: str = _TEST_DATASET) -> None:
    err = _validate_sql(sql, project=project, dataset=dataset)
    assert err is None, f"expected pass, got: {err}"


def _reject(
    sql: str,
    hint: str,
    *,
    project: str = _TEST_PROJECT,
    dataset: str = _TEST_DATASET,
) -> None:
    err = _validate_sql(sql, project=project, dataset=dataset)
    assert err is not None, "expected rejection, got pass"
    assert hint.lower() in err.lower(), f"expected '{hint}' in '{err}'"


def test_basic_select_passes():
    _ok("SELECT * FROM `proj.devpath.clusters` LIMIT 50")


def test_with_cte_passes():
    _ok(
        """
        WITH x AS (SELECT 1 AS a) SELECT * FROM `proj.devpath.clusters` LIMIT 50
        """
    )


def test_must_have_limit():
    _reject("SELECT * FROM `proj.devpath.clusters`", "LIMIT")


def test_must_start_with_select_or_with():
    _reject("ANALYZE TABLE x LIMIT 1", "SELECT or WITH")


def test_rejects_disallowed_table():
    _reject(
        "SELECT * FROM `proj.devpath.eval_results` LIMIT 10",
        "disallowed tables",
    )


def test_rejects_information_schema():
    _reject(
        "SELECT * FROM `region-us.INFORMATION_SCHEMA.JOBS` LIMIT 5",
        "information_schema",
    )


def test_rejects_forbidden_keyword():
    _reject("SELECT * FROM `proj.devpath.clusters` UNION SELECT 1 LIMIT 5; DROP TABLE x LIMIT 5", "single statement")


def test_rejects_union_in_single_statement():
    """A single-statement UNION is now explicitly rejected — not via the
    multi-statement check or via the allowlist, but as a forbidden keyword
    in its own right. This closes the case where a crafted query glues a
    SELECT on an allowed table onto a second SELECT that smuggles in
    constants or reaches for something outside the allowlist."""
    _reject(
        "SELECT cluster_id FROM `proj.devpath.clusters` UNION ALL "
        "SELECT 999 FROM `proj.devpath.clusters` LIMIT 5",
        "union",
    )
    _reject(
        "SELECT cluster_id FROM `proj.devpath.clusters` UNION "
        "SELECT 1 LIMIT 5",
        "union",
    )


def test_block_comment_keywords_are_stripped():
    """Forbidden keywords inside /* */ are noise; the executable SQL is safe."""
    _ok("SELECT * FROM `proj.devpath.clusters` /* DROP TABLE x */ LIMIT 5")


def test_line_comment_keywords_are_stripped():
    _ok("SELECT 1 AS x FROM `proj.devpath.clusters` -- DELETE FROM something\nLIMIT 5")


def test_hash_comment_keywords_are_stripped():
    _ok("SELECT 1 AS x FROM `proj.devpath.clusters` # TRUNCATE later\nLIMIT 5")


def test_keyword_outside_comment_still_caught():
    """The comment-stripping path must NOT eat live DDL — only commented-out tokens."""
    _reject(
        "SELECT * FROM `proj.devpath.clusters` LIMIT 5\nDROP TABLE x LIMIT 5",
        "drop",
    )


def test_disallowed_table_in_comment_is_ok():
    """References to disallowed tables inside comments are not executable."""
    _ok(
        """
        SELECT *
        FROM `proj.devpath.clusters` /* JOIN `proj.devpath.eval_results` x ON 1=1 */
        LIMIT 5
        """
    )


def test_disallowed_table_via_live_join_is_rejected():
    _reject(
        """
        SELECT *
        FROM `proj.devpath.clusters`
        JOIN `proj.devpath.eval_results` ON 1=1
        LIMIT 5
        """,
        "disallowed",
    )


def test_oversize_query_rejected():
    big = "SELECT * FROM `proj.devpath.clusters` WHERE x = '" + "a" * (MAX_SQL_LENGTH + 100) + "' LIMIT 5"
    _reject(big, "exceeds")


def test_strip_comments_helper():
    assert _strip_comments("SELECT /* comment */ 1") .strip().split() == ["SELECT", "1"]
    assert "DROP" not in _strip_comments("SELECT 1 -- DROP\n").upper()


def test_limit_inside_string_literal_does_not_count():
    _reject(
        "SELECT 'limit' FROM `proj.devpath.clusters`",
        "LIMIT",
    )


def test_table_extractor_ignores_cte_alias():
    """CTE aliases (the name after WITH … AS) should not be treated as tables."""
    _ok(
        """
        WITH ranked AS (SELECT * FROM `proj.devpath.clusters` LIMIT 5)
        SELECT * FROM ranked LIMIT 5
        """
    )


# -- Security regression tests (S1-S3, issue #53) ------------------------------


def test_cross_project_from_rejected_even_when_suffix_matches():
    """S1: a fully-qualified ref whose last segment is in ALLOWED_TABLES but
    whose project/dataset don't match the agent's BQ target must be rejected.
    The previous _extract_tables only kept the suffix, so this passed."""
    _reject(
        "SELECT * FROM `evil-proj.evil_ds.trajectories` LIMIT 5",
        "disallowed tables",
    )


def test_cross_dataset_in_same_project_rejected():
    """S1: same project, different dataset, allowed suffix — still rejected."""
    _reject(
        "SELECT * FROM `proj.shadow_ds.clusters` LIMIT 5",
        "disallowed tables",
    )


def test_two_segment_dataset_table_ref_rejected():
    """S1: `dataset.table` (no project) used to pass via the suffix-only
    check. Production prompt mandates fully-qualified refs."""
    _reject(
        "SELECT * FROM devpath.trajectories LIMIT 5",
        "fully qualified",
    )


def test_external_query_function_rejected():
    """S2: EXTERNAL_QUERY is a function call, not an identifier; the
    FROM/JOIN regex breaks at `(` and the extractor sees no tables.
    Block by substring instead."""
    _reject(
        "SELECT * FROM EXTERNAL_QUERY('conn_id', 'SELECT 1 AS x') LIMIT 5",
        "external_query",
    )


def test_ml_generate_text_rejected():
    """S2: inline Gemini-from-BQ would let an attacker burn Gemini quota
    via the BQ job side-channel."""
    _reject(
        "SELECT * FROM ML.GENERATE_TEXT(MODEL `proj.devpath.m`, "
        "(SELECT 'x' AS prompt)) LIMIT 5",
        "ml.generate_text",
    )


def test_ml_predict_rejected():
    """S2: ML.PREDICT against an attacker-influenced model could leak."""
    _reject(
        "SELECT * FROM ML.PREDICT(MODEL `proj.devpath.m`, "
        "TABLE `proj.devpath.trajectories`) LIMIT 5",
        "ml.predict",
    )


def test_object_table_rejected():
    """S2: BigQuery object tables expose GCS contents to a SELECT.
    Substring is caught even when smuggled into an identifier name."""
    _reject(
        "SELECT * FROM `proj.devpath.product_object_table` LIMIT 5",
        "object_table",
    )


def test_limit_above_hard_cap_rejected():
    """S3: previously only the *presence* of LIMIT was checked; a huge
    numeric literal slipped through and let a single query exfiltrate
    the entire trajectories table."""
    _reject(
        "SELECT * FROM `proj.devpath.trajectories` LIMIT 1000000",
        "exceeds hard cap",
    )


def test_limit_at_hard_cap_boundary_passes():
    """S3: LIMIT == MAX_HARD_LIMIT is allowed (inclusive boundary)."""
    _ok(f"SELECT * FROM `proj.devpath.trajectories` LIMIT {MAX_HARD_LIMIT}")


def test_limit_one_above_cap_rejected():
    """S3: LIMIT == MAX_HARD_LIMIT + 1 is rejected (boundary check)."""
    _reject(
        f"SELECT * FROM `proj.devpath.trajectories` LIMIT {MAX_HARD_LIMIT + 1}",
        "exceeds hard cap",
    )


def test_full_triple_with_default_limit_passes():
    """S1 happy path: fully-qualified ref + LIMIT 50 passes."""
    _ok("SELECT employee_id FROM `proj.devpath.trajectories` LIMIT 50")


def test_limit_only_in_subquery_rejected():
    """S3 follow-up (Copilot): LIMIT inside a subquery does not bound the
    outer query. The validator must require a trailing top-level LIMIT."""
    _reject(
        "SELECT * FROM `proj.devpath.trajectories` "
        "WHERE EXISTS (SELECT 1 FROM `proj.devpath.clusters` LIMIT 1)",
        "top-level LIMIT",
    )


def test_limit_only_in_cte_rejected():
    """S3 follow-up: LIMIT inside a CTE body doesn't bound the outer
    SELECT — `WITH bounded AS (... LIMIT 1) SELECT * FROM bounded`
    returns one row from `bounded`, but a CTE whose body unions in
    unbounded sources still leaks at the outer level."""
    _reject(
        "WITH bounded AS (SELECT * FROM `proj.devpath.clusters` LIMIT 1) "
        "SELECT * FROM bounded",
        "top-level LIMIT",
    )


def test_trailing_limit_with_offset_passes():
    """Pagination form `LIMIT N OFFSET M` at the tail is accepted."""
    _ok(
        "SELECT * FROM `proj.devpath.trajectories` LIMIT 50 OFFSET 100"
    )


def test_trailing_limit_with_semicolon_passes():
    """An optional trailing `;` is tolerated by the trailing-LIMIT matcher
    (the single-statement check already rejects mid-statement `;`)."""
    _ok("SELECT * FROM `proj.devpath.trajectories` LIMIT 50;")


# -- S8 SQL masking tests ------------------------------------------------------


def test_mask_project_dataset_strips_backticked_prefix():
    """`<project>.<dataset>.<table>` → `<table>` in the client-facing SQL.
    The unmasked form is what we execute; the masked form is what we echo
    so the GCP project ID isn't reconnaissance gold for unauthenticated
    callers."""
    sql = "SELECT * FROM `ai-agent-hackathon-499013.devpath.trajectories` LIMIT 50"
    masked = _mask_project_dataset(sql, "ai-agent-hackathon-499013", "devpath")
    assert masked == "SELECT * FROM `trajectories` LIMIT 50"


def test_mask_project_dataset_handles_multiple_refs():
    """JOIN across two allowed tables — both prefixes are stripped."""
    sql = (
        "SELECT t.employee_id FROM `ai-agent-hackathon-499013.devpath.trajectories` t "
        "JOIN `ai-agent-hackathon-499013.devpath.embeddings` e "
        "ON t.employee_id = e.employee_id LIMIT 10"
    )
    masked = _mask_project_dataset(sql, "ai-agent-hackathon-499013", "devpath")
    assert "ai-agent-hackathon-499013" not in masked
    assert "`trajectories`" in masked
    assert "`embeddings`" in masked


def test_mask_project_dataset_case_insensitive_match():
    """Defensive: model output uses the project ID as-given by the prompt,
    but if a future prompt template upper-cases part of it, the mask
    should still fire — IAM-enumeration risk doesn't depend on case."""
    sql = "SELECT * FROM `Ai-Agent-Hackathon-499013.DEVPATH.trajectories` LIMIT 5"
    masked = _mask_project_dataset(sql, "ai-agent-hackathon-499013", "devpath")
    assert "ai-agent-hackathon-499013" not in masked.lower()
    assert "`trajectories`" in masked


def test_mask_project_dataset_leaves_other_projects_intact():
    """Refs to project IDs that aren't ours pass through unchanged. (The
    validator separately rejects them, but this helper is purely about
    not leaking *our* project ID — it must not silently rewrite somebody
    else's project name as a side effect.)"""
    sql = "SELECT * FROM `someone-else.public_ds.trajectories` LIMIT 5"
    masked = _mask_project_dataset(sql, "ai-agent-hackathon-499013", "devpath")
    assert masked == sql


def test_mask_project_dataset_noop_when_project_or_dataset_empty():
    """If state isn't fully initialised (unit tests, very early startup),
    the helper is a no-op rather than producing garbled output."""
    sql = "SELECT * FROM `proj.devpath.trajectories` LIMIT 5"
    assert _mask_project_dataset(sql, "", "devpath") == sql
    assert _mask_project_dataset(sql, "proj", "") == sql


def test_mask_project_dataset_strips_bare_unquoted_prefix():
    """BigQuery exception strings and validator error messages spell out
    the fully-qualified `proj.dataset.table` form without backticks; the
    masker has to catch that too or the masking goal is defeated."""
    text = "BigQuery error: Not found: Table ai-agent-hackathon-499013.devpath.trajectories"
    masked = _mask_project_dataset(text, "ai-agent-hackathon-499013", "devpath")
    assert "ai-agent-hackathon-499013" not in masked
    assert "trajectories" in masked


def test_mask_project_dataset_masks_validator_error_with_disallowed_triple():
    """The validator returns `Disallowed tables: ['proj.devpath.eval_results']`
    when the model emits a 3-segment ref matching our project/dataset but a
    table not on the allowlist. That string MUST be masked before going back
    to the caller."""
    err = "Disallowed tables: ['ai-agent-hackathon-499013.devpath.eval_results']"
    masked = _mask_project_dataset(err, "ai-agent-hackathon-499013", "devpath")
    assert "ai-agent-hackathon-499013" not in masked
    assert "devpath." not in masked
    assert "eval_results" in masked


def test_mask_project_dataset_does_not_split_longer_identifiers():
    """A project id that happens to be a *prefix* of a longer identifier
    must not be partially rewritten. e.g. if our project is `proj` and a
    string contains `proj2.foo` it must stay intact."""
    text = "leave alone: proj2.devpath.trajectories"
    masked = _mask_project_dataset(text, "proj", "devpath")
    assert masked == text
