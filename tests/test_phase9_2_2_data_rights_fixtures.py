"""Phase 9.2.2 distributable-fixture and data-rights tests.

The repository previously tracked Nasdaq quote-history CSVs and Alpha Vantage demo
responses. Neither carried a redistribution grant, so neither may sit in the tracked tree
or in CI. These tests fail if restricted vendor data returns, if a synthetic fixture loses
its label, or if the hash manifest drifts from the bytes it describes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from atlas.entities.master import SecurityMaster
from atlas.ingestion.market_alphavantage import load_synthetic_fixture
from atlas.research.prices import SOURCE_SELECTION_POLICY, import_price_series, price_summary
from atlas.storage.sources import ensure_default_sources

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "market"
VENDOR_NAMES = (
    "nasdaq_JPM.csv",
    "nasdaq_GS.csv",
    "nasdaq_UNH.csv",
    "nasdaq_AAPL.csv",
    "nasdaq_AMZN.csv",
    "ibm_daily_alphavantage.json",
    "ibm_dividends_alphavantage.json",
    "ibm_splits_alphavantage.json",
    "alphavantage_manifest.json",
)


def test_no_vendor_market_file_is_tracked():
    for name in VENDOR_NAMES:
        assert not (MARKET / name).exists(), (
            f"{name} is vendor-derived market history without a redistribution grant; "
            "it must not be tracked (see docs/DATA_RIGHTS_AUDIT.md)"
        )


def test_market_manifest_declares_synthetic_and_vendor_free():
    manifest = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["contains_vendor_data"] is False
    assert manifest["redistribution"] == "public_domain"
    assert manifest["authorization_basis"]
    assert manifest["retrieved_at"] is None, "synthetic data has no provider retrieval instant"
    for series in manifest["series"]:
        assert series["synthetic"] is True
        assert (ROOT / series["path"]).exists()


def test_fixture_hash_manifest_matches_the_tracked_bytes():
    manifest = json.loads((MARKET / "synthetic_manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True and manifest["contains_vendor_data"] is False
    assert manifest["files"]
    for entry in manifest["files"]:
        payload = (ROOT / entry["path"]).read_bytes()
        assert len(payload) == entry["bytes"], f"{entry['path']} size drifted"
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"], (
            f"{entry['path']} content drifted from its declared hash"
        )
        assert entry["synthetic"] is True


def test_synthetic_payload_is_labelled_and_parsed_through_the_provider_shape():
    payload = load_synthetic_fixture(
        MARKET, security_id="SYN-TEST", mic="XNAS", source_id="synthetic-market-fixture"
    )
    assert payload["synthetic"] is True
    assert len(payload["bars"]) == 10
    assert payload["actions"], "synthetic split and dividend fixtures exercise the action path"
    assert all(bar.source_id == "synthetic-market-fixture" for bar in payload["bars"])
    # A 2:1 split halves the price from 104.50 to 52.75 in the generated series.
    closes = {bar.ts.date().isoformat(): float(bar.close) for bar in payload["bars"]}
    assert closes["2024-12-06"] == pytest.approx(104.50)
    assert closes["2024-12-09"] == pytest.approx(52.75)


def test_unlabelled_payload_is_refused(tmp_path):
    daily = json.loads((MARKET / "synthetic_daily_bars.json").read_text())
    daily["Meta Data"].pop("6. Synthetic")
    (tmp_path / "synthetic_daily_bars.json").write_text(json.dumps(daily))
    (tmp_path / "synthetic_splits.json").write_text(
        (MARKET / "synthetic_splits.json").read_text()
    )
    (tmp_path / "synthetic_dividends.json").write_text(
        (MARKET / "synthetic_dividends.json").read_text()
    )
    with pytest.raises(Exception, match="not labelled synthetic"):
        load_synthetic_fixture(tmp_path, security_id="SYN-TEST", mic="XNAS")


def test_vendor_archive_loader_requires_caller_supplied_files(tmp_path):
    """No vendor archive ships with the repository; the adapter fails closed without one."""
    from atlas.ingestion.market_alphavantage import load_archived

    with pytest.raises(FileNotFoundError):
        load_archived(tmp_path, security_id="SYN-TEST", mic="XNAS")


def test_synthetic_import_is_exportable_and_restricted_import_is_not(db):
    ensure_default_sources(db)
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Atlas Synthetic Markets Corp", cik="0009999999", sic="9999")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2019-01-01", is_primary=True)
    master.assign_ticker(
        listing, "ATLS", valid_from="2019-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
        evidence_note="Project-authored synthetic identity; not an exchange assignment.",
    )
    manifest = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        {"date": "2024-12-02", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
    ]
    public = import_price_series(
        db, ticker="ATLS", rows=rows,
        source_name="Atlas synthetic market fixture", licence=manifest["licence"],
        redistribution="public_domain", adjustment_semantics="unadjusted",
        authorization_basis=manifest["authorization_basis"],
        collection_method="synthetic_fixture", security_id=security, mic="XNAS",
        retrieved_at="2024-12-13T21:00:00Z",
    )
    summary = price_summary(db, security, source_id=public["source"]["source_id"])
    assert summary["source"]["export_allowed"] is True
    assert summary["source_selection"]["policy"] == SOURCE_SELECTION_POLICY

    restricted = import_price_series(
        db, ticker="ATLS", rows=rows,
        source_name="Operator licensed feed", licence="Operator entitlement, no redistribution",
        redistribution="restricted", adjustment_semantics="unadjusted",
        security_id=security, mic="XNAS", retrieved_at="2024-12-13T21:00:00Z",
    )
    restricted_summary = price_summary(db, security, source_id=restricted["source"]["source_id"])
    assert restricted_summary["source"]["export_allowed"] is False
    assert restricted_summary["source"]["redistribution"] == "restricted"
