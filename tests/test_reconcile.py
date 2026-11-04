"""Independent reconciliation: stored facts vs the original SEC payload.

These tests deliberately corrupt stored data with direct SQL and assert that
reconciliation notices. A validator that only ever sees correct data proves nothing.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from atlas.evidence.kernel import EvidenceKernel
from atlas.ingestion.sec_sync import SecIngestor, load_fixture_payloads
from atlas.reconcile import reconcile_companyfacts

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
APPLE_DIR = FIXTURES / "sec"
RESTATEMENT_DIR = FIXTURES / "sec_restatement"
APPLE_CIK = "0000320193"
RESTATEMENT_CIK = "0001999999"


@pytest.fixture()
def restatement(db):
    submissions, facts = load_fixture_payloads(RESTATEMENT_DIR, RESTATEMENT_CIK)[:2]
    report = SecIngestor(db).sync_payloads(
        RESTATEMENT_CIK,
        submissions_payload=submissions,
        companyfacts_payload=facts,
        observed_at="2026-01-01T00:00:00Z",
    )
    return db, submissions, facts, report


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_restatement_payload_reconciles_clean(restatement):
    db, _, facts, _ = restatement
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    assert report.ok, report.findings
    assert report.expected_observations > 0
    assert report.matched == report.expected_observations
    assert report.mismatched_values == 0
    assert report.missing_from_store == 0
    assert report.unexpected_in_store == 0
    assert report.duplicate_keys == 0
    assert report.availability_issues == 0
    assert "revenue" in report.concepts_checked


def test_real_apple_payload_reconciles_clean(db):
    submissions, facts = load_fixture_payloads(APPLE_DIR, APPLE_CIK)[:2]
    SecIngestor(db).sync_payloads(
        APPLE_CIK,
        submissions_payload=submissions,
        companyfacts_payload=facts,
        observed_at="2026-01-01T00:00:00Z",
    )
    report = reconcile_companyfacts(db, facts, cik=APPLE_CIK)
    assert report.ok, report.errors[:3]
    assert report.expected_observations > 4000
    assert report.matched == report.expected_observations
    assert report.mismatched_values == 0
    assert report.missing_from_store == 0
    assert report.unexpected_in_store == 0
    assert report.stored_source_facts == report.expected_observations


def test_tampered_value_is_detected(restatement):
    db, _, facts, _ = restatement
    row = db.query_one(
        "SELECT evidence_id, value_numeric FROM evidence WHERE concept = 'revenue' "
        "AND unit = 'USD' AND value_numeric = '100000000' LIMIT 1"
    )
    db.execute(
        "UPDATE evidence SET value_numeric = '100000001' WHERE evidence_id = ?",
        (row["evidence_id"],),
    )
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    assert not report.ok
    assert "stored_value_differs_from_source" in _codes(report)
    assert report.mismatched_values >= 1
    assert report.expected_observations == report.matched + report.mismatched_values


def test_deleted_observation_is_detected(restatement):
    db, _, facts, _ = restatement
    row = db.query_one(
        "SELECT evidence_id FROM evidence WHERE evidence_id NOT IN "
        "(SELECT superseded_id FROM evidence_supersession) AND evidence_id NOT IN "
        "(SELECT superseding_id FROM evidence_supersession) AND concept = 'revenue' LIMIT 1"
    )
    assert row is not None, "need an unlinked revenue observation to delete"
    deleted = row["evidence_id"]
    db.execute("DELETE FROM evidence WHERE evidence_id = ?", (deleted,))
    assert db.query_one("SELECT 1 FROM evidence WHERE evidence_id = ?", (deleted,)) is None
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    assert not report.ok
    assert "source_observation_not_stored" in _codes(report)
    assert report.missing_from_store >= 1


def test_unexpected_stored_fact_is_detected(restatement, make_fact):
    db, _, facts, report_in = restatement
    kernel = EvidenceKernel(db)
    # A fact for a period the source never reported (1999) must be flagged.
    from atlas.core.temporal import ReportingPeriod

    kernel.ingest(
        make_fact(
            entity_id=report_in.issuer_id,
            concept="revenue",
            value="123456",
            accession_number="0001999999-99-000001",
            period=ReportingPeriod(end=date(1999, 3, 31), start=date(1999, 1, 1)),
        )
    )
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    assert "stored_fact_not_in_source" in _codes(report)
    assert report.unexpected_in_store >= 1


def test_amendment_marking_is_checked(restatement):
    db, _, facts, _ = restatement
    row = db.query_one(
        "SELECT evidence_id FROM evidence WHERE revision_kind = 'amendment' LIMIT 1"
    )
    assert row is not None
    db.execute(
        "UPDATE evidence SET revision_kind = 'original' WHERE evidence_id = ?", (row["evidence_id"],)
    )
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    assert "amendment_not_marked" in _codes(report)
    assert report.amendment_issues >= 1


def test_duration_without_start_is_detected(restatement):
    db, _, facts, _ = restatement
    row = db.query_one(
        "SELECT evidence_id FROM evidence WHERE concept = 'revenue' AND period_start IS NOT NULL LIMIT 1"
    )
    db.execute("UPDATE evidence SET period_start = NULL WHERE evidence_id = ?", (row["evidence_id"],))
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    # The stored row no longer matches the source key (which includes the start date),
    # so it appears both as missing and unexpected plus the duration check on the
    # remaining records still runs.
    assert not report.ok
    assert report.missing_from_store >= 1
    assert "stored_fact_not_in_source" in _codes(report)


def test_availability_disagreement_is_detected(restatement):
    db, _, facts, _ = restatement
    row = db.query_one(
        "SELECT evidence_id FROM evidence WHERE availability_precision = 'exact' LIMIT 1"
    )
    db.execute(
        "UPDATE evidence SET availability_precision = 'date' WHERE evidence_id = ?",
        (row["evidence_id"],),
    )
    report = reconcile_companyfacts(db, facts, cik=RESTATEMENT_CIK)
    assert "date_availability_not_end_of_day" in _codes(report)
    assert report.availability_issues >= 1
