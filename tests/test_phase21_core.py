"""Phase 2.1 core tests: migration 004, read cache, batched listing, vendor adapter."""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.entities.master import SecurityMaster
from atlas.ingestion.market_alphavantage import (
    parse_daily,
    parse_dividends,
    parse_splits,
)
from atlas.market.actions import ActionType
from atlas.market.bars import Bar, BarStore
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.storage.sources import ensure_default_sources
from atlas.terminal import cache, read_models


def test_schema_v4_adds_indexes_and_research_tables(tmp_path):
    db = Database(tmp_path / "v4.db")
    db.migrate()
    assert LATEST_VERSION == 6
    assert db.scalar("SELECT MAX(version) FROM schema_migration") == 6
    indexes = {row["name"] for row in db.query("PRAGMA index_list('bar')")}
    assert {"idx_bar_latest_v4", "idx_bar_security_v4"} <= indexes
    tables = {row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"research_object", "research_object_evidence"} <= tables
    db.close()


def test_cache_generation_changes_when_bars_are_added(tmp_path):
    db = Database(tmp_path / "cache.db")
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    issuer = master.register_issuer(legal_name="Cache Co", cik="0000000099", source_id="sec-edgar")
    master.ensure_venue("XNAS", "Nasdaq")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(listing, "CCH", valid_from="2020-01-01", confidence=0.6,
                         status="probable", source_id="sec-edgar")
    BarStore(db).ingest([
        Bar(security_id=security, mic="XNAS", ts_utc="2024-01-02T21:00:00Z",
            open=Decimal("10"), high=Decimal("11"), low=Decimal("9"), close=Decimal("10"),
            volume=Decimal("100"), currency="USD", source_id="atlas-synthetic"),
    ])
    first = read_models.list_companies(db)
    assert first[0]["securities"][0]["last_close"] == Decimal("10")
    before = cache.generation(db)
    BarStore(db).ingest([
        Bar(security_id=security, mic="XNAS", ts_utc="2024-01-03T21:00:00Z",
            open=Decimal("10"), high=Decimal("12"), low=Decimal("10"), close=Decimal("11"),
            volume=Decimal("100"), currency="USD", source_id="atlas-synthetic"),
    ])
    assert cache.generation(db) != before
    second = read_models.list_companies(db)
    assert second[0]["securities"][0]["last_close"] == Decimal("11")
    db.close()


def test_batched_company_list_matches_individual_detail(tmp_path):
    db = Database(tmp_path / "batch.db")
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    issuer = master.register_issuer(legal_name="Batch Co", cik="0000000100", source_id="sec-edgar")
    master.ensure_venue("XNAS", "Nasdaq")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(listing, "BCH", valid_from="2020-01-01", confidence=0.6,
                         status="probable", source_id="sec-edgar")
    db.execute(
        "INSERT INTO filing (filing_id, issuer_id, cik, accession_number, form_type, filed_date, "
        "source_id) VALUES (?,?,?,?,?,?,?)",
        ("F-B", issuer, "0000000100", "0000000100-24-000001", "10-K", "2024-02-01", "sec-edgar"),
    )
    listed = read_models.list_companies(db)
    detail = read_models.company_detail(db, issuer)
    for key in ("issuer_id", "legal_name", "evidence_count", "filing_count", "securities"):
        assert listed[0][key] == detail[key]
    db.close()


def _daily_payload():
    return {
        "Meta Data": {"2. Symbol": "IBM"},
        "Time Series (Daily)": {
            "2024-01-03": {"1. open": "160.10", "2. high": "161.00", "3. low": "159.50",
                           "4. close": "160.50", "5. volume": "4000000"},
            "2024-01-02": {"1. open": "159.00", "2. high": "160.00", "3. low": "158.00",
                           "4. close": "159.50", "5. volume": "3500000"},
        },
    }


def test_alphavantage_daily_parser_is_ordered_and_close_timestamped():
    bars = parse_daily(_daily_payload(), security_id="SEC-ibm", mic="XNYS")
    assert [bar.session_date for bar in bars] == ["2024-01-02", "2024-01-03"]
    assert bars[0].close == Decimal("159.50")
    assert bars[0].ts_utc.endswith("21:00:00Z")  # 16:00 America/New_York in January
    assert all(bar.adjustment_status == "raw" for bar in bars)


def test_alphavantage_rejects_error_payloads():
    with pytest.raises(Exception):
        parse_daily({"Error Message": "Invalid API call"}, security_id="SEC-ibm", mic="XNYS")


def test_alphavantage_split_and_dividend_mapping():
    splits = parse_splits(
        {"symbol": "IBM", "data": [{"effective_date": "2021-11-04", "split_factor": "1.0460"}]},
        security_id="SEC-ibm",
    )
    assert splits[0].action_type == ActionType.SPLIT.value
    assert splits[0].ratio_to == Decimal("1.0460")
    assert splits[0].split_factor == Decimal("1.0460")

    dividends = parse_dividends(
        {"symbol": "IBM", "data": [{"ex_dividend_date": "2024-02-08", "amount": "1.66",
                                    "declaration_date": "2024-01-30", "record_date": "2024-02-09",
                                    "payment_date": "2024-03-09"}]},
        security_id="SEC-ibm",
    )
    assert dividends[0].action_type == ActionType.CASH_DIVIDEND.value
    assert dividends[0].cash_amount == Decimal("1.66")
    assert dividends[0].currency == "USD"


def test_migration_v3_to_v4_is_additive_and_preserves_rows(tmp_path):
    path = tmp_path / "upgrade.db"
    db = Database(path)
    applied = db.migrate(target=3)
    assert applied == [1, 2, 3]
    ensure_default_sources(db)
    issuer_id = SecurityMaster(db).register_issuer(
        legal_name="Upgrade Co", cik="0000000101", source_id="sec-edgar"
    )
    db.execute(
        "INSERT INTO app_setting (owner_id, key, value, updated_at) VALUES (?,?,?,?)",
        ("local", "theme", '"dark"', "2026-01-01T00:00:00Z"),
    )
    assert db.schema_version() == 3
    assert db.migrate() == [4, 5, 6]
    assert db.schema_version() == LATEST_VERSION
    assert db.scalar("SELECT legal_name FROM issuer WHERE issuer_id = ?", (issuer_id,)) == "Upgrade Co"
    assert db.scalar("SELECT value FROM app_setting WHERE key = 'theme'") == '"dark"'
    assert {"idx_bar_latest_v4", "idx_bar_security_v4"} <= {
        row["name"] for row in db.query("PRAGMA index_list('bar')")
    }
    db.close()
