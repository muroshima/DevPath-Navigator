"""Tests for the NL→SQL safety validator."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.tools.nlq_over_corpus import (
    MAX_SQL_LENGTH,
    _strip_comments,
    _validate_sql,
)


def _ok(sql: str) -> None:
    err = _validate_sql(sql)
    assert err is None, f"expected pass, got: {err}"


def _reject(sql: str, hint: str) -> None:
    err = _validate_sql(sql)
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
