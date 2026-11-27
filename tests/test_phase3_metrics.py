"""Phase 3 materialized metrics: historical cutoff, invalidation, screener reuse."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from atlas.core.temporal import ReportingPeriod, availability_from_instant
from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.evidence.model import EvidenceRecord
from atlas.storage.migrations import LATEST_VERSION
from atlas.terminal import metric_store, screener


def _fact(kernel, concept, value, *, end, available, accession, entity_id="ISS-CIK0000000200"):
    kernel.ingest(
        EvidenceRecord.build(
            entity_id=entity_id,
            entity_kind="issuer",
            concept=concept,
            source_id="sec-edgar",
            unit="USD",
            availability=availability_from_instant(available, "test.acceptance"),
            period=ReportingPeriod(
                end=end, start=date(end.year - 1, 12, 31),
                fiscal_year=end.year, fiscal_period="FY"
            ),
            value=Decimal(value),
            accession_number=accession,
            form_type="10-K",
            filed_date=available[:10],
            observed_at=available,
            quality="verified",
            verification="source_primary",
            source_dataset="sec_companyfacts",
            taxonomy="us-gaap",
            source_concept=f"us-gaap:{concept}",
        )
    )


def _issuer(db):
    master = SecurityMaster(db)
    issuer = master.register_issuer(
        legal_name="Materialized Co", cik="0000000200", source_id="sec-edgar"
    )
    master.ensure_venue("XNAS", "Nasdaq")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    master.ensure_listing(security, "XNAS", valid_from="2020-01-01", is_primary=True)
    return issuer


def test_schema_v5_and_snapshot_roundtrip(db):
    assert LATEST_VERSION >= 14
    issuer = _issuer(db)
    kernel = EvidenceKernel(db)
    _fact(kernel, "revenue", "100", end=date(2023, 12, 31),
          available="2024-02-01T16:00:00Z", accession="A-2023")
    first = metric_store.get_issuer_metrics(
        db, issuer, as_of="2024-06-01T23:59:59Z"
    )
    assert first["period_end"] == "2023-12-31"
    assert first["metrics"]["revenue"]["value"] == 100.0
    second = metric_store.get_issuer_metrics(
        db, issuer, as_of="2024-06-01T23:59:59Z"
    )
    assert second == first
    assert metric_store.stats(db)["snapshots"] == 1


def test_historical_key_does_not_use_later_disclosure(db):
    issuer = _issuer(db)
    kernel = EvidenceKernel(db)
    _fact(kernel, "revenue", "100", end=date(2023, 12, 31),
          available="2024-02-01T16:00:00Z", accession="A-2023")
    _fact(kernel, "revenue", "150", end=date(2024, 12, 31),
          available="2025-02-01T16:00:00Z", accession="A-2024")
    before = metric_store.get_issuer_metrics(db, issuer, as_of="2024-06-01T23:59:59Z")
    after = metric_store.get_issuer_metrics(db, issuer, as_of="2025-06-01T23:59:59Z")
    assert before["period_end"] == "2023-12-31"
    assert after["period_end"] == "2024-12-31"
    assert before["metrics"]["revenue"]["value"] == 100.0
    assert after["metrics"]["revenue"]["value"] == 150.0


def test_amendment_invalidates_only_affected_issuer(db):
    issuer = _issuer(db)
    kernel = EvidenceKernel(db)
    _fact(kernel, "revenue", "100", end=date(2023, 12, 31),
          available="2024-02-01T16:00:00Z", accession="A-2023")
    metric_store.get_issuer_metrics(db, issuer, as_of="2024-06-01T23:59:59Z")
    other = SecurityMaster(db).register_issuer(
        legal_name="Untouched Co", cik="0000000201", source_id="sec-edgar"
    )
    _fact(kernel, "revenue", "50", end=date(2023, 12, 31),
          available="2024-02-01T16:00:00Z", accession="A-OTHER", entity_id=other)
    metric_store.get_issuer_metrics(db, other, as_of="2024-06-01T23:59:59Z")
    before_generation = metric_store.generation(db, issuer)
    _fact(kernel, "revenue", "120", end=date(2023, 12, 31),
          available="2024-08-01T16:00:00Z", accession="A-2023")
    assert metric_store.generation(db, issuer) != before_generation
    historical = metric_store.get_issuer_metrics(db, issuer, as_of="2024-06-01T23:59:59Z")
    assert historical["metrics"]["revenue"]["value"] == 100.0
    refreshed = metric_store.get_issuer_metrics(db, issuer, as_of="2025-06-01T23:59:59Z")
    assert refreshed["metrics"]["revenue"]["value"] == 120.0
    untouched = metric_store.get_issuer_metrics(db, other, as_of="2024-06-01T23:59:59Z")
    assert untouched["metrics"]["revenue"]["value"] == 50.0


def test_screener_uses_materialized_snapshots(db):
    import time

    issuer = _issuer(db)
    kernel = EvidenceKernel(db)
    for concept, value in (("revenue", "100"), ("net_income", "10"), ("equity", "50"),
                           ("shares_outstanding", "10")):
        _fact(kernel, concept, value, end=date(2023, 12, 31),
              available="2024-02-01T16:00:00Z", accession="A-2023")
    started = time.perf_counter()
    first = screener.run_screener(db, limit=50)
    cold = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    second = screener.run_screener(db, limit=50)
    warm = (time.perf_counter() - started) * 1000
    assert first["matched"] == second["matched"] == 1
    assert metric_store.stats(db)["snapshots"] >= 1
    # This test is about reuse, not a brittle absolute benchmark.
    assert warm < cold
