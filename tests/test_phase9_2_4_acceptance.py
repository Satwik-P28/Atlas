"""Phase 9.2.4 regression tests for defects found while running the browser journeys.

Two provenance defects were only visible once the browser journeys actually executed:

* a project-authored synthetic series was registered under source kind ``market_data``,
  so the read models labelled the synthetic ATLS prices as *reported* exchange data;
* an unavailable market comparison omitted the accounting-period field entirely, so a
  caller could not distinguish "no comparison happened" from a truncated payload.
"""

from __future__ import annotations

from atlas.entities.master import SecurityMaster
from atlas.research.prices import import_price_series, market_analysis
from atlas.terminal.read_models import _source_status


def _identity(db):
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Synthetic Markets Corp", cik="1099999", sic="9999")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2019-01-01", is_primary=True)
    master.assign_ticker(listing, "SYN", valid_from="2019-01-01", confidence=1.0,
                         status="confirmed", source_id="sec-edgar")
    return security


def _import(db, security_id: str, *, collection_method: str):
    return import_price_series(
        db,
        ticker="SYN",
        rows=[{"date": "2024-12-12", "open": 99.0, "high": 101.0, "low": 98.0,
               "close": 100.0, "volume": 1000}],
        source_name="Atlas synthetic market fixture",
        licence="Apache-2.0 (project-authored fixtures)",
        redistribution="project_authored",
        adjustment_semantics="unadjusted",
        collection_method=collection_method,
        security_id=security_id,
        mic="XNAS",
    )


def test_synthetic_fixture_registers_a_synthetic_source(db):
    security_id = _identity(db)
    source_id = _import(db, security_id, collection_method="synthetic_fixture")["source"]["source_id"]
    row = db.query_one("SELECT kind FROM source WHERE source_id = ?", (source_id,))
    assert row is not None, "the synthetic fixture did not register a source"
    assert row["kind"] == "synthetic", (
        f"a project-authored fixture registered as {row['kind']!r}, which read models "
        "present as reported market data"
    )
    assert _source_status(db, source_id) == "synthetic"


def test_vendor_import_still_registers_a_market_source(db):
    security_id = _identity(db)
    source_id = _import(db, security_id, collection_method="user_import")["source"]["source_id"]
    row = db.query_one("SELECT kind FROM source WHERE source_id = ?", (source_id,))
    assert row["kind"] == "market_data"
    assert _source_status(db, source_id) == "reported"


def test_unavailable_market_analysis_exposes_explicit_nulls():
    analysis = market_analysis(
        price=None, history=None, value_per_share=12.5,
        accounting_period_end="2024-12-31", information_cutoff="2025-06-30",
    )
    assert analysis["status"] == "unavailable"
    assert analysis["price"] is None
    assert analysis["accounting_period_end"] is None, (
        "an unavailable comparison must not assert an accounting period"
    )
    assert analysis["information_cutoff"] == "2025-06-30"
