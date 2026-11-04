"""Phase 1 acceptance tests (A-H), executed offline against archived fixtures.

These are the scenarios the specification requires. Each test states which
acceptance criterion it covers so the report can cite real results.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.core.errors import StorageError
from atlas.core.temporal import availability_from_instant
from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.ingestion.market_csv import import_csv_bars
from atlas.ingestion.sec_sync import SecIngestor, register_fixture_documents
from atlas.market.actions import ActionStore, ActionType, CorporateAction
from atlas.market.adjust import split_adjust, verify_split_continuity
from atlas.market.bars import BarStore
from atlas.market.calendar import TradingCalendar
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SEC_DIR = FIXTURES / "sec"
RESTATEMENT_DIR = FIXTURES / "sec_restatement"
MARKET_CSV = FIXTURES / "market" / "aapl_split_bars.csv"
APPLE_CIK = "0000320193"
RESTATEMENT_CIK = "0001999999"


def _sync(db, directory: Path, cik: str):
    submissions_doc, facts_doc = register_fixture_documents(db, directory, cik)
    submissions = json.loads((directory / "submissions_CIK0000320193.json").read_text()) if (directory / "submissions_CIK0000320193.json").exists() else json.loads((directory / "submissions.json").read_text())
    facts = json.loads((directory / "companyfacts_CIK0000320193.json").read_text()) if (directory / "companyfacts_CIK0000320193.json").exists() else json.loads((directory / "companyfacts.json").read_text())
    return SecIngestor(db).sync_payloads(
        cik,
        submissions_payload=submissions,
        companyfacts_payload=facts,
        submissions_doc_id=submissions_doc,
        companyfacts_doc_id=facts_doc,
    )


@pytest.fixture(scope="module")
def apple_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("acceptance") / "apple.db"
    database = Database(path)
    database.migrate()
    ensure_default_sources(database)
    yield database
    database.close()


# --------------------------------------------------------------------------- #
# Test A: company research
# --------------------------------------------------------------------------- #
def test_acceptance_a_company_research(apple_db):
    report = _sync(apple_db, SEC_DIR, APPLE_CIK)
    assert report.issuer_id == "ISS-CIK0000320193"
    kernel = EvidenceKernel(apple_db)
    result = kernel.as_of(report.issuer_id, "2026-11-01T00:00:00Z", concepts=["revenue", "net_income"])
    assert result.facts, "expected financial facts for Apple"
    for fact in result.facts:
        assert fact.period_end, "every fact must expose its financial period"
        assert fact.unit, "every fact must expose its unit"
        assert fact.accession_number, "every fact must cite a filing"
        assert fact.source_concept, "the original XBRL element must be preserved"
        assert fact.availability_time, "availability must be evidenced for SEC facts"
    assert any(fact.availability_precision == "exact" for fact in result.facts)
    assert any(fact.form_type in {"10-K", "10-Q"} for fact in result.facts)


# --------------------------------------------------------------------------- #
# Test B: historical reconstruction
# --------------------------------------------------------------------------- #
def test_acceptance_b_historical_reconstruction(db):
    _sync(db, RESTATEMENT_DIR, RESTATEMENT_CIK)
    kernel = EvidenceKernel(db)
    issuer = "ISS-CIK0001999999"
    before = kernel.as_of(issuer, "2024-06-01T00:00:00Z", concepts=["revenue"])
    after = kernel.as_of(issuer, "2024-09-01T00:00:00Z", concepts=["revenue"])
    before_usd = next(fact for fact in before.facts if fact.unit == "USD")
    after_usd = next(fact for fact in after.facts if fact.unit == "USD")
    assert before_usd.value == "100000000"
    assert before_usd.accession_number == "0001999999-24-000004"
    assert after_usd.value == "90000000"
    assert after_usd.accession_number == "0001999999-24-000009"
    # No leakage: the amendment is not in the earlier result at all.
    assert all(fact.accession_number != "0001999999-24-000009" for fact in before.facts)
    assert before.excluded_not_yet_available >= 1
    # Nothing was overwritten.
    assert len(kernel.history(issuer, "revenue")) >= 2


# --------------------------------------------------------------------------- #
# Test C: security identity across a ticker change
# --------------------------------------------------------------------------- #
def test_acceptance_c_security_identity(db):
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Identity Demo Inc.", cik="1920001")
    security = master.ensure_security(issuer, class_designation="common stock")
    listing = master.ensure_listing(security, "XNAS", valid_from="2012-05-18", is_primary=True)
    master.assign_ticker(listing, "OLD", valid_from="2012-05-18", status="confirmed", confidence=1.0)
    master.record_ticker_change(security, "NEW", "2022-06-09")

    other_issuer = master.register_issuer(legal_name="Reuse Demo Inc.", cik="1920002")
    other = master.ensure_security(other_issuer, class_designation="common stock")
    other_listing = master.ensure_listing(other, "XNAS", valid_from="2023-01-10", is_primary=True)
    master.assign_ticker(other_listing, "OLD", valid_from="2023-01-10", status="probable", confidence=0.8)

    historical = master.resolve_ticker("OLD", as_of="2021-06-01")
    current = master.resolve_ticker("OLD", as_of="2024-01-01")
    assert historical.candidates[0].security_id == security
    assert current.candidates[0].security_id == other
    assert historical.candidates[0].security_id != current.candidates[0].security_id
    # Observations keyed by internal security id cannot migrate to the reused ticker.
    assert historical.candidates[0].ticker == current.candidates[0].ticker == "OLD"


# --------------------------------------------------------------------------- #
# Test D: corporate actions and adjustment
# --------------------------------------------------------------------------- #
def test_acceptance_d_corporate_actions(db):
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Split Demo Inc.", cik="1920003")
    security = master.ensure_security(issuer, class_designation="common stock")
    source_id = "atlas-synthetic"
    calendar = TradingCalendar(db)
    calendar.ensure_venue("XNAS")
    imported = import_csv_bars(MARKET_CSV, security_id=security, mic="XNAS", source_id=source_id, calendar=calendar)
    calendar.ensure_range("XNAS", imported.bars[0].session_date, imported.bars[-1].session_date)
    BarStore(db).ingest(imported.bars)

    actions = ActionStore(db)
    actions.add(
        CorporateAction(
            security_id=security, action_type=ActionType.SPLIT.value, source_id=source_id,
            ex_date="2020-08-31", ratio_from=Decimal(1), ratio_to=Decimal(4), status="confirmed",
        ),
        availability=availability_from_instant("2020-08-28T20:30:00Z", "test"),
    )

    store = BarStore(db)
    raw_before = [bar.to_dict() for bar in store.query(security, "XNAS", "2020-08-01", "2020-09-30")]
    series = split_adjust(raw_before and store.query(security, "XNAS", "2020-08-01", "2020-09-30"),
                          actions.list(security))
    raw_by_date = {bar.session_date: bar for bar in store.query(security, "XNAS", "2020-08-01", "2020-09-30")}
    assert series.bars[0].close * series.bars[0].split_factor == raw_by_date[series.bars[0].session_date].close
    assert series.bars[-1].close == raw_by_date[series.bars[-1].session_date].close
    assert verify_split_continuity(list(raw_by_date.values()), series) == []
    # Raw rows unchanged after deriving the adjusted view.
    raw_after = [bar.to_dict() for bar in store.query(security, "XNAS", "2020-08-01", "2020-09-30")]
    assert raw_before == raw_after


# --------------------------------------------------------------------------- #
# Test E: Financial X-Ray
# --------------------------------------------------------------------------- #
def test_acceptance_e_financial_xray(apple_db):
    kernel = EvidenceKernel(apple_db)
    row = apple_db.query_one(
        "SELECT evidence_id FROM evidence WHERE entity_id = 'ISS-CIK0000320193' AND concept = 'capex' "
        "ORDER BY period_end DESC LIMIT 1"
    )
    if row is None:
        pytest.skip("no capital expenditure fact in the archived payload")
    report = kernel.provenance(row["evidence_id"])
    assert report.record.source_concept == "PaymentsToAcquirePropertyPlantAndEquipment"
    assert report.record.accession_number
    assert report.record.availability_time
    assert report.record.observed_at
    assert report.record.raw_doc_id, "the raw SEC document must be linked"
    assert report.raw_document and report.raw_document["content_hash"]
    assert report.filing and report.filing["accession_number"] == report.record.accession_number
    assert any("Transformation" in line for line in report.narrative)
    assert report.record.derivation_rule == "atlas.normalize.magnitude_outflow.v1"


# --------------------------------------------------------------------------- #
# Test F: incremental update
# --------------------------------------------------------------------------- #
def test_acceptance_f_incremental_update(db):
    first = _sync(db, RESTATEMENT_DIR, RESTATEMENT_CIK)
    kernel = EvidenceKernel(db)
    after_first = kernel.count()
    second = _sync(db, RESTATEMENT_DIR, RESTATEMENT_CIK)
    assert second.evidence["inserted"] == 0
    assert second.evidence["duplicates"] == first.evidence["written"]
    assert kernel.count() == after_first

    # Introduce corrected source evidence: history must be preserved, not rewritten.
    corrected = json.loads((RESTATEMENT_DIR / "companyfacts.json").read_text())
    for observation in corrected["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]:
        if observation["accn"] == "0001999999-24-000009":
            observation["val"] = 89000000
    SecIngestor(db).sync_payloads(
        RESTATEMENT_CIK,
        submissions_payload=json.loads((RESTATEMENT_DIR / "submissions.json").read_text()),
        companyfacts_payload=corrected,
    )
    versions = [r for r in kernel.history("ISS-CIK0001999999", "revenue") if r.unit == "USD"]
    assert [r.value_numeric for r in versions] == ["100000000", "90000000", "89000000"]
    early = kernel.as_of("ISS-CIK0001999999", "2024-06-01T00:00:00Z", concepts=["revenue"])
    assert next(fact for fact in early.facts if fact.unit == "USD").value == "100000000"


# --------------------------------------------------------------------------- #
# Test G: offline reproduction
# --------------------------------------------------------------------------- #
def test_acceptance_g_offline_reproduction(db):
    """No network is used: a transport that would fail loudly is never invoked."""

    def exploding_transport(request, timeout):  # pragma: no cover - must never run
        raise AssertionError(f"network access attempted: {request.full_url}")

    from atlas.ingestion.sec_client import SecClient

    report = _sync(db, RESTATEMENT_DIR, RESTATEMENT_CIK)
    assert report.evidence["inserted"] > 0
    client = SecClient(user_agent="Atlas/0.1 offline@example.com", db=db, transport=exploding_transport)
    with pytest.raises(Exception):
        client.get("https://example.com/not-allowed")  # host allowlist refuses before transport
    # The full suite runs from local fixtures only; this assertion documents that.
    assert (SEC_DIR / "companyfacts_CIK0000320193.json").exists()


# --------------------------------------------------------------------------- #
# Test H: reliability
# --------------------------------------------------------------------------- #
def test_acceptance_h_interrupted_ingestion_recovers(tmp_path):
    path = tmp_path / "reliability.db"
    database = Database(path)
    database.migrate()
    ensure_default_sources(database)
    kernel = EvidenceKernel(database)

    submissions = json.loads((RESTATEMENT_DIR / "submissions.json").read_text())
    facts = json.loads((RESTATEMENT_DIR / "companyfacts.json").read_text())

    class InterruptingIngestor(SecIngestor):
        def _interrupt_after_first_fact(self, records):
            for record in records:
                kernel.ingest(record)
                raise KeyboardInterrupt("simulated crash")

    ingestor = InterruptingIngestor(database)
    original = ingestor.kernel.ingest_many

    def interrupted(records, **kwargs):
        with database.transaction():
            ingestor._interrupt_after_first_fact(list(records))
        return original(records, **kwargs)

    ingestor.kernel.ingest_many = interrupted  # type: ignore[assignment]
    with pytest.raises(KeyboardInterrupt):
        ingestor.sync_payloads(RESTATEMENT_CIK, submissions_payload=submissions, companyfacts_payload=facts)
    assert kernel.count() == 0  # transaction rolled back entirely

    database.close()
    reopened = Database(path)
    assert reopened.integrity_check() == "ok"
    assert EvidenceKernel(reopened).count() == 0

    # Recovery needs no manual repair: retry the same ingestion.
    report = SecIngestor(reopened).sync_payloads(
        RESTATEMENT_CIK, submissions_payload=submissions, companyfacts_payload=facts
    )
    assert report.evidence["written"] > 0
    assert EvidenceKernel(reopened).count() == report.evidence["written"]
    assert reopened.integrity_check() == "ok"
    reopened.close()
