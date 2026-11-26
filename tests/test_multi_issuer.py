"""Multi-issuer ingestion across industries, fiscal years, share classes and history.

Real SEC payloads for Microsoft (software, June year end, one class), Walmart (retail,
January year end, one class) and Alphabet (internet, December year end, three tickers
across two classes) are ingested into one database. The point is to exercise the ways
issuers differ, not to assert one company's numbers as if they were universal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.ingestion.sec_history import load_fixture_history
from atlas.ingestion.sec_sync import SecIngestor, load_fixture_payloads
from atlas.reconcile import reconcile_companyfacts
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.validation import run_validation

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

ISSUERS = [
    # ticker, fixture directory, CIK, expected fiscal-year end (MMDD)
    ("MSFT", FIXTURES / "sec_msft", "0000789019", "0630"),
    ("WMT", FIXTURES / "sec_wmt", "0000104169", "0131"),
    ("GOOGL", FIXTURES / "sec_googl", "0001652044", "1231"),
]


@pytest.fixture(scope="module")
def multi(tmp_path_factory):
    path = tmp_path_factory.mktemp("multi-issuer") / "atlas.db"
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    reports = {}
    for ticker, directory, cik, _ in ISSUERS:
        submissions, facts, _, _ = load_fixture_payloads(directory, cik)
        reports[ticker] = SecIngestor(db).sync_payloads(
            cik,
            submissions_payload=submissions,
            companyfacts_payload=facts,
            history_documents=load_fixture_history(directory, cik),
            observed_at="2026-01-01T00:00:00Z",
        )
    yield db, reports
    db.close()


def _issuer(db: Database, cik: str) -> dict:
    row = db.query_one("SELECT * FROM issuer WHERE cik = ?", (cik,))
    assert row is not None
    return {key: row[key] for key in row.keys()}


@pytest.mark.parametrize("ticker,directory,cik,fiscal_year_end", ISSUERS)
def test_each_issuer_is_ingested_with_complete_history(multi, ticker, directory, cik, fiscal_year_end):
    _, reports = multi
    report = reports[ticker]
    stats = report.companyfacts["stats"]
    assert report.issuer_id
    assert report.filings_written > 1000
    assert report.history["coverage"]["complete"] is True
    assert report.history["coverage"]["missing_files"] == []
    assert stats["availability_unknown"] == 0
    assert stats["availability_exact"] > stats["availability_date"]
    assert len(stats["concepts_covered"]) >= 25


def test_fiscal_year_ends_are_preserved_per_issuer(multi):
    db, _ = multi
    for _, _, cik, expected in ISSUERS:
        assert _issuer(db, cik)["fiscal_year_end"] == expected


def test_periods_follow_each_issuers_fiscal_calendar(multi):
    db, reports = multi
    kernel = EvidenceKernel(db)
    # Walmart's January year end means annual facts end in January, not December.
    walmart = kernel.as_of(
        reports["WMT"].issuer_id, "2026-12-31T00:00:00Z", concepts=["revenue"]
    )
    ends = [fact.period_end for fact in walmart.facts if fact.period_start]
    assert any(end.endswith("-01-31") for end in ends), ends[:10]
    # Microsoft's June year end produces June period ends.
    microsoft = kernel.as_of(
        reports["MSFT"].issuer_id, "2026-12-31T00:00:00Z", concepts=["revenue"]
    )
    assert any(fact.period_end.endswith("-06-30") for fact in microsoft.facts)


def test_revenue_magnitudes_are_plausible_for_each_business(multi):
    db, reports = multi
    kernel = EvidenceKernel(db)
    for ticker, ceiling in (("MSFT", 400_000_000_000), ("WMT", 800_000_000_000)):
        result = kernel.as_of(reports[ticker].issuer_id, "2026-12-31T00:00:00Z", concepts=["revenue"])
        annual = [
            fact for fact in result.facts
            if fact.period_start and fact.period_end and _days(fact.period_start, fact.period_end) > 300
        ]
        assert annual, f"{ticker} has annual revenue facts"
        latest = max(annual, key=lambda fact: fact.period_end)
        assert 50_000_000_000 < float(latest.value) < ceiling


def _days(start: str, end: str) -> int:
    from datetime import date

    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def test_multi_class_issuer_creates_provisional_securities_for_each_ticker(multi):
    db, reports = multi
    alphabet = _issuer(db, "0001652044")
    report = reports["GOOGL"]
    cover_page_tickers = {entry["ticker"] for entry in report.securities if entry["ticker"]}
    # SEC's cover page lists every registered symbol, including ones that are not the
    # primary listed class, so the count comes from the source rather than a guess.
    assert len(cover_page_tickers) >= 2
    securities = db.query(
        "SELECT security_id, class_designation FROM security WHERE issuer_id = ? ORDER BY security_id",
        (alphabet["issuer_id"],),
    )
    assert len(securities) == len(cover_page_tickers), (
        [row["class_designation"] for row in securities], cover_page_tickers
    )
    classes = [row["class_designation"] for row in securities]
    assert any("GOOGL" in value for value in classes)
    assert any("GOOG" in value for value in classes)
    statuses = db.query(
        "SELECT DISTINCT ta.status FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
        "WHERE l.security_id IN ({})".format(", ".join("?" for _ in securities)),
        tuple(row["security_id"] for row in securities),
    )
    assert {row["status"] for row in statuses} == {"unverified"}


def test_single_class_issuers_get_one_security(multi):
    db, _ = multi
    for cik in ("0000789019", "0000104169"):
        issuer = _issuer(db, cik)
        count = db.scalar("SELECT COUNT(*) FROM security WHERE issuer_id = ?", (issuer["issuer_id"],))
        assert count == 1


def test_ticker_resolution_is_issuer_specific(multi):
    db, reports = multi
    master = SecurityMaster(db)
    microsoft = master.resolve_ticker("MSFT").require_single()
    assert microsoft.issuer_id == reports["MSFT"].issuer_id

    googl = master.resolve_ticker("GOOGL").require_single()
    goog = master.resolve_ticker("GOOG").require_single()
    assert googl.security_id != goog.security_id
    assert googl.issuer_id == goog.issuer_id == _issuer(db, "0001652044")["issuer_id"]


def test_historical_ticker_resolution_is_conservative(multi):
    """SEC does not evidence when a ticker started, so a past date resolves to nothing.

    Atlas stores the retrieval date as the assignment start and says so, instead of
    pretending the symbol was active throughout the issuer's history.
    """
    db, _ = multi
    resolution = SecurityMaster(db).resolve_ticker("MSFT", as_of="2015-01-01")
    assert resolution.candidates == []
    assert resolution.confidence == "none"
    assert any("2015-01-01" in reason for reason in resolution.reasoning), resolution.reasoning


def test_industry_specific_concept_coverage_differs(multi):
    _, reports = multi
    msft = set(reports["MSFT"].companyfacts["stats"]["concepts_covered"])
    wmt = set(reports["WMT"].companyfacts["stats"]["concepts_covered"])
    assert msft != wmt
    # Microsoft reports research and development; a retailer typically does not.
    assert "research_and_development" in msft


@pytest.mark.parametrize("ticker,directory,cik,fiscal_year_end", ISSUERS)
def test_every_issuer_reconciles_against_its_source(multi, ticker, directory, cik, fiscal_year_end):
    db, _ = multi
    _, facts, _, _ = load_fixture_payloads(directory, cik)
    report = reconcile_companyfacts(db, facts, cik=cik)
    assert report.ok, report.errors[:3]
    assert report.matched == report.expected_observations
    assert report.mismatched_values == 0
    assert report.missing_from_store == 0
    assert report.unexpected_in_store == 0


def test_whole_dataset_passes_integrity_validation(multi):
    db, _ = multi
    report = run_validation(db)
    assert report.ok, [finding.to_dict() for finding in report.errors[:5]]
    assert len(report.checks_run) >= 7


def test_no_ticker_is_claimed_by_two_of_these_issuers(multi):
    db, _ = multi
    findings = [
        finding
        for finding in run_validation(db).findings
        if finding.code == "ticker_claimed_by_two_securities"
    ]
    assert findings == []
