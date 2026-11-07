"""Phase 9.2.1 adversarial market-data integrity tests.

These tests fail against the former delete-by-session importer: it removed provider A's
observation when provider B imported the same session and mutated a single shared source
record's rights.
"""

from __future__ import annotations

import pytest

from atlas.entities.master import SecurityMaster
from atlas.research.prices import (
    PriceImportError,
    import_price_series,
    price_history,
    price_on_or_before,
    price_summary,
)
from atlas.storage.sources import ensure_default_sources


def _identity(db, *, ticker: str = "TST", mic: str = "XNYS"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Test Bank", cik="1000001", sic="6021")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, mic, valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(
        listing, ticker, valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return master, issuer, security, listing


def _row(close: float, *, day: str = "2025-01-02"):
    return {
        "date": day, "open": close - 0.5, "high": close + 0.5,
        "low": close - 1.0, "close": close, "volume": 1000,
    }


def _import(db, *, close: float, source: str, licence: str, ticker: str = "TST",
            redistribution: str = "restricted", adjustment_semantics: str = "unadjusted",
            **kwargs):
    return import_price_series(
        db, ticker=ticker, rows=[_row(close)], source_name=source,
        licence=licence, redistribution=redistribution,
        adjustment_semantics=adjustment_semantics, **kwargs,
    )


def test_two_providers_can_report_the_same_session(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    first = _import(db, close=10.0, source="Provider A", licence="A restricted")
    second = _import(db, close=20.0, source="Provider B", licence="B restricted")
    assert first["source"]["source_id"] != second["source"]["source_id"]
    assert db.scalar("SELECT COUNT(*) FROM bar") == 2
    a = price_on_or_before(db, security, "2025-01-02", source_id=first["source"]["source_id"])
    b = price_on_or_before(db, security, "2025-01-02", source_id=second["source"]["source_id"])
    assert a["close"] == 10.0
    assert b["close"] == 20.0
    summary = price_summary(db, security)
    assert summary["source_selection"]["conflict"] is True
    assert len(summary["source_selection"]["alternatives"]) == 1


def test_identical_replay_is_idempotent_and_a_correction_is_an_appended_revision(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    first = _import(db, close=10.0, source="Provider A", licence="A restricted")
    replay = _import(db, close=10.0, source="Provider A", licence="A restricted")
    assert first["written"] == 1
    assert replay["written"] == 0
    assert replay["duplicates"] == 1
    assert db.scalar("SELECT COUNT(*) FROM bar") == 1
    correction = _import(db, close=11.0, source="Provider A", licence="A restricted")
    assert correction["revisions"] == 1
    rows = db.query(
        "SELECT revision_seq, close, supersedes_bar FROM bar ORDER BY revision_seq"
    )
    assert [(row["revision_seq"], row["close"], row["supersedes_bar"]) for row in rows] == [
        (1, "10", None), (2, "11", 1),
    ]
    selected = price_on_or_before(
        db, security, "2025-01-02", source_id=first["source"]["source_id"]
    )
    assert selected["close"] == 11.0
    assert selected["revision_seq"] == 2


def test_saved_source_selection_reproduces_after_a_new_provider_arrives(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    a = _import(db, close=10.0, source="Provider A", licence="A restricted")
    original = price_on_or_before(
        db, security, "2025-01-02", source_id=a["source"]["source_id"]
    )
    _import(db, close=20.0, source="Provider B", licence="B restricted")
    replay = price_on_or_before(
        db, security, "2025-01-02", source_id=original["source_id"]
    )
    assert replay["close"] == original["close"] == 10.0
    assert replay["source_selection"]["policy"] == "atlas.market_price.selection.v1"


def test_explicit_source_change_selects_the_new_provider(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, source="Provider A", licence="A restricted")
    b = _import(db, close=20.0, source="Provider B", licence="B restricted")
    changed = price_on_or_before(
        db, security, "2025-01-02", source_id=b["source"]["source_id"]
    )
    assert changed["close"] == 20.0
    assert changed["source_id"] == b["source"]["source_id"]


def test_a_failed_batch_leaves_no_partial_rows(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    with pytest.raises(PriceImportError):
        import_price_series(
            db, ticker="TST",
            rows=[_row(10.0), {"date": "2025-01-03", "close": "not-a-number"}],
            source_name="Provider A", licence="A restricted",
            redistribution="restricted", adjustment_semantics="unadjusted",
        )
    assert db.scalar("SELECT COUNT(*) FROM bar WHERE security_id=?", (security,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM market_price_series") == 0


def test_rights_are_not_inherited_across_licences(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    restricted = _import(db, close=10.0, source="Same feed", licence="Restricted terms")
    public = _import(
        db, close=11.0, source="Same feed", licence="Explicit public grant",
        redistribution="public_domain", authorization_basis="test fixture: public grant",
    )
    assert restricted["source"]["source_id"] != public["source"]["source_id"]
    old = db.query_one(
        "SELECT licence, redistribution FROM source WHERE source_id=?",
        (restricted["source"]["source_id"],),
    )
    assert (old["licence"], old["redistribution"]) == ("Restricted terms", "restricted")
    assert price_summary(
        db, security, source_id=restricted["source"]["source_id"]
    )["source"]["export_allowed"] is False
    assert price_summary(
        db, security, source_id=public["source"]["source_id"]
    )["source"]["export_allowed"] is True


def test_ambiguous_ticker_requires_an_explicit_security_and_venue(db):
    ensure_default_sources(db)
    master, issuer, first_security, _ = _identity(db)
    second_security = master.ensure_security(
        issuer, class_designation="class B common stock", currency="USD"
    )
    second_listing = master.ensure_listing(
        second_security, "XNYS", valid_from="2020-01-01", is_primary=False
    )
    master.assign_ticker(
        second_listing, "TST", valid_from="2020-01-01", confidence=1.0,
        status="confirmed", source_id="sec-edgar",
    )
    with pytest.raises(PriceImportError, match="ambiguous"):
        _import(db, close=10.0, source="Provider A", licence="A restricted")
    selected = _import(
        db, close=10.0, source="Provider A", licence="A restricted",
        security_id=first_security, mic="XNYS",
    )
    assert selected["security_id"] == first_security
    with pytest.raises(PriceImportError, match="no active listing"):
        _import(
            db, close=10.0, source="Provider A", licence="A restricted",
            security_id=first_security, mic="XNAS",
        )


def test_ticker_reuse_does_not_reassign_historical_observations(db):
    ensure_default_sources(db)
    master, issuer, first_security, first_listing = _identity(db)
    master.assign_ticker(
        first_listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    first = _import(
        db, close=10.0, source="Provider A", licence="A restricted", as_of="2024-12-31"
    )
    second_security = master.ensure_security(
        issuer, class_designation="new common stock", currency="USD"
    )
    second_listing = master.ensure_listing(second_security, "XNYS", valid_from="2025-01-01")
    master.assign_ticker(
        second_listing, "TST", valid_from="2025-01-01", confidence=1.0,
        status="confirmed", source_id="sec-edgar",
    )
    second = _import(
        db, close=20.0, source="Provider B", licence="B restricted", as_of="2025-01-02"
    )
    assert first["security_id"] == first_security
    assert second["security_id"] == second_security
    assert price_summary(db, first_security)["latest_close"] == 10.0
    assert price_summary(db, second_security)["latest_close"] == 20.0


def test_derived_adjusted_series_is_rejected_not_stored_as_raw(db):
    ensure_default_sources(db)
    _identity(db)
    with pytest.raises(PriceImportError, match="raw/unadjusted"):
        _import(
            db, close=10.0, source="Provider A", licence="A restricted",
            adjustment_semantics="split_adjusted",
        )
    assert db.scalar("SELECT COUNT(*) FROM bar") == 0
