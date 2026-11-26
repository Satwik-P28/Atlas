"""SQL structure safety: every spliced identifier must be a constant, an enum or guarded.

Values are always bound as parameters; the review in ``docs/SECURITY_SQL_REVIEW.md`` covers the
49 statements that are assembled with interpolation. These tests attack the three places where
a name is spliced into SQL text rather than bound, plus the full-text search path that takes
arbitrary user strings.
"""

from __future__ import annotations

import pytest

from atlas.core.errors import StorageError, ValidationError
from atlas.core.temporal import AsOfMode
from atlas.storage.db import Database


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.migrate()
    return database


@pytest.mark.parametrize("hostile", [
    "evidence; DROP TABLE evidence",
    "evidence--",
    "evidence) OR 1=1 --",
    "sqlite_master",
    "",
])
def test_row_count_refuses_anything_but_a_bare_identifier(db, hostile):
    """The one helper that splices a caller's table name checks it first."""
    if hostile == "sqlite_master":  # a real table name, allowed by the identifier rule
        assert db.row_count(hostile) >= 0
        return
    with pytest.raises(StorageError):
        db.row_count(hostile)
    assert "evidence" in db.tables()


def test_as_of_mode_can_only_select_an_allowlisted_column():
    """Selection code splices ``mode.column``; the mode is an enum, so the name cannot vary."""
    assert AsOfMode("public_available").column == "availability_time"
    assert AsOfMode("atlas_ingested").column == "observed_at"
    with pytest.raises(ValueError):
        AsOfMode("public_available; DROP TABLE evidence")


def test_mcp_health_counts_only_its_own_table_list(tmp_path):
    """The health tool interpolates table names from a literal tuple, not from its arguments."""
    from atlas.mcp.tools import ToolContext, inspect_data_health

    path = tmp_path / "health.db"
    database = Database(str(path))
    database.migrate()
    database.close()
    result = inspect_data_health(ToolContext(db_path=str(path)),
                                 {"table": "evidence; DROP TABLE evidence",
                                  "counts": "sqlite_master"})
    assert "counts" in result
    assert set(result["counts"]).issubset({
        "evidence", "issuer", "security", "bar", "knowledge_document", "knowledge_unit",
        "knowledge_table", "research_object", "economic_observation",
    })
    check = Database(str(path))
    try:
        assert "evidence" in check.tables()
    finally:
        check.close()


def test_search_terms_are_bound_not_spliced(db):
    """A SQL metacharacter payload in a search term is a value: it returns nothing, changes nothing."""
    from atlas.research.knowledge import KnowledgeEngine

    engine = KnowledgeEngine(db)
    before = db.row_count("knowledge_unit")
    for payload in ["' OR 1=1 --", '"; DROP TABLE knowledge_unit; --', "NEAR(", "revenue) --"]:
        result = engine.search(payload)
        assert isinstance(result.get("units", result), (list, dict))
        assert result.get("query") == payload, "the query is echoed as a value, not parsed as SQL"
    # A payload with no indexable terms is refused as a query, not passed through to SQL.
    with pytest.raises(ValidationError):
        engine.search("%")
    assert db.row_count("knowledge_unit") == before
    assert "knowledge_unit" in db.tables()


def test_unknown_concept_filter_cannot_become_sql(db):
    """Concept filters become bound placeholders; an unknown name is refused, not spliced."""
    from atlas.evidence.kernel import EvidenceKernel, ENGINE_SQL

    kernel = EvidenceKernel(db)
    with pytest.raises((ValidationError, ValueError)):
        kernel.as_of("ISS-NONE", "2025-01-01", mode="public_available",
                     concepts=["revenue'; DROP TABLE evidence; --"], engine=ENGINE_SQL)
    assert "evidence" in db.tables()
