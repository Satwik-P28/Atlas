"""Storage: migrations, restart safety, transaction rollback, integrity validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.core.errors import StorageError
from atlas.evidence.kernel import EvidenceKernel
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.storage.quality import issue_summary, list_issues, record_issue, resolve_issue
from atlas.storage.sources import ensure_default_sources
from atlas.validation import run_validation, summarize


def test_migrations_are_versioned_and_idempotent(file_db):
    assert file_db.schema_version() == LATEST_VERSION
    assert file_db.migrate() == []
    applied = file_db.applied_migrations()
    assert [row["version"] for row in applied] == list(range(1, LATEST_VERSION + 1))
    assert file_db.integrity_check() == "ok"


def test_restart_preserves_data(tmp_path, make_fact):
    path = tmp_path / "restart.db"
    database = Database(path)
    database.migrate()
    ensure_default_sources(database)
    kernel = EvidenceKernel(database)
    record = make_fact()
    kernel.ingest(record)
    database.close()

    reopened = Database(path)
    assert reopened.migrate() == []
    assert reopened.schema_version() == LATEST_VERSION
    assert EvidenceKernel(reopened).count() == 1
    assert EvidenceKernel(reopened).get(record.evidence_id).value_numeric == "100000000"
    assert reopened.integrity_check() == "ok"
    reopened.close()


def test_transaction_rollback_leaves_no_partial_state(db, make_fact):
    kernel = EvidenceKernel(db)
    with pytest.raises(RuntimeError):
        with db.transaction():
            kernel.ingest(make_fact())
            raise RuntimeError("simulated interruption")
    assert kernel.count() == 0


def test_interrupted_ingestion_is_rerunnable_and_idempotent(db, make_fact):
    records = [
        make_fact(),
        make_fact(concept="net_income", source_concept="NetIncomeLoss", value=Decimal("5")),
    ]
    kernel = EvidenceKernel(db)
    with pytest.raises(RuntimeError):
        with db.transaction():
            for record in records:
                kernel.ingest(record)
            raise RuntimeError("process killed mid-ingestion")
    assert kernel.count() == 0

    first = kernel.ingest_many(records)
    assert first.inserted == 2
    second = kernel.ingest_many(records)
    assert second.duplicates == 2 and second.inserted == 0
    assert kernel.count() == 2


def test_nested_transaction_savepoints(db, make_fact):
    kernel = EvidenceKernel(db)
    with db.transaction():
        kernel.ingest(make_fact())
        try:
            with db.transaction():
                kernel.ingest(make_fact(concept="net_income", source_concept="NetIncomeLoss", value=Decimal("7")))
                raise ValueError("inner failure")
        except ValueError:
            pass
    # Outer commit survives; inner work rolled back.
    assert kernel.count() == 1


def test_foreign_keys_are_enforced(db, apple_security):
    with pytest.raises(StorageError):
        db.execute(
            "INSERT INTO listing (listing_id, security_id, mic, valid_from) VALUES ('LST-bad','SEC-missing','XNAS','2020-01-01')"
        )


def test_quality_issues_are_deduplicated_and_resolvable(db):
    first = record_issue(db, scope="test", subject_id="x", code="c", severity="warning", detail="d")
    second = record_issue(db, scope="test", subject_id="x", code="c", severity="warning", detail="d")
    assert first == second
    assert len(list_issues(db)) == 1
    assert issue_summary(db)["warning"] == 1
    resolve_issue(db, first)
    assert list_issues(db) == []
    assert issue_summary(db)["warning"] == 0


def test_validation_passes_on_clean_database(db):
    report = run_validation(db)
    assert report.ok
    assert report.findings == []
    assert "evidence_temporal_invariants" in report.checks_run


def test_validation_detects_invalid_ohlc(db, apple_security):
    db.execute(
        "INSERT INTO bar (security_id, mic, interval, ts_utc, revision_seq, open, high, low, close, currency, "
        "adjustment_status, source_id, observed_at, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (apple_security, "XNAS", "1d", "2020-08-28T20:00:00Z", 1, "10", "9", "11", "10",
         "USD", "raw", "atlas-synthetic", "2020-08-28T21:00:00Z", "2020-08-28T21:00:00Z"),
    )
    report = run_validation(db)
    assert any(finding.code == "invalid_ohlc" for finding in report.errors)


def test_validation_detects_evidence_without_availability(db, make_fact):
    kernel = EvidenceKernel(db)
    record = make_fact()
    kernel.ingest(record)
    db.execute("UPDATE evidence SET availability_time = NULL WHERE evidence_id = ?", (record.evidence_id,))
    report = run_validation(db)
    assert any(finding.code == "availability_timestamp_missing" for finding in report.errors)


def test_validation_detects_ticker_overlap_warning(db, master):
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    first_issuer = master.register_issuer(legal_name="Overlap One Inc.", cik="1910001")
    first = master.ensure_security(first_issuer, class_designation="common stock")
    first_listing = master.ensure_listing(first, "XNAS", valid_from="2020-01-01")
    master.assign_ticker(first_listing, "DUP", valid_from="2020-01-01", status="confirmed")
    second_issuer = master.register_issuer(legal_name="Overlap Two Inc.", cik="1910002")
    second = master.ensure_security(second_issuer, class_designation="common stock")
    second_listing = master.ensure_listing(second, "XNAS", valid_from="2020-06-01")
    master.assign_ticker(second_listing, "DUP", valid_from="2020-06-01", status="confirmed")
    report = run_validation(db)
    assert any(finding.code == "ticker_claimed_by_two_securities" for finding in report.warnings)


def test_validation_detects_supersession_cycle(db, make_fact):
    kernel = EvidenceKernel(db)
    first = make_fact()
    second = make_fact(value=Decimal("1"), accession_number="A-2",
                       availability=__import__("atlas").core.temporal.availability_from_instant(
                           "2024-09-01T00:00:00Z", "t"))
    kernel.ingest(first)
    kernel.ingest(second)
    # Deliberately corrupt the graph to prove the detector works.
    db.execute(
        "INSERT OR IGNORE INTO evidence_supersession (superseded_id, superseding_id, reason, created_at) "
        "VALUES (?,?,?,?)",
        (second.evidence_id, first.evidence_id, "intentional-test-cycle", "2024-09-02T00:00:00Z"),
    )
    report = run_validation(db)
    assert any(finding.code == "supersession_cycle" for finding in report.errors)


def test_summary_reports_dataset_shape(db, make_fact):
    EvidenceKernel(db).ingest(make_fact())
    stats = summarize(db)
    assert stats["schema_version"] == LATEST_VERSION
    assert stats["evidence"]["evidence_records"] == 1
    assert stats["tables"]["evidence"] == 1
    assert stats["integrity_check"] == "ok"
