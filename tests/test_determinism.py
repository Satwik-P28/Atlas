"""Deterministic replay, Parquet import and provider independence."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.ingestion.market_csv import import_csv_bars, import_parquet_bars
from atlas.ingestion.sec_sync import SecIngestor, load_fixture_payloads
from atlas.market.bars import Bar, BarStore
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RESTATEMENT_DIR = FIXTURES / "sec_restatement"
RESTATEMENT_CIK = "0001999999"

ROWS = [
    ("2024-01-02", "100.00", "101.00", "99.50", "100.50", "1000000"),
    ("2024-01-03", "100.50", "102.00", "100.00", "101.50", "1200000"),
    ("2024-01-04", "101.50", "101.75", "100.25", "100.75", "900000"),
    ("2024-01-05", "100.75", "103.00", "100.50", "102.50", "1500000"),
]


def _fresh_db(path: Path) -> Database:
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    return db


def _evidence_dump(db: Database) -> list[tuple]:
    return [tuple(row) for row in db.query("SELECT * FROM evidence ORDER BY evidence_id")]


def _write_csv(path: Path, header: list[str], rows: list[tuple[str, ...]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _security(db: Database, name: str) -> str:
    master = SecurityMaster(db)
    issuer = master.register_issuer(legal_name=name, cik=f"1700{abs(hash(name)) % 9999:03d}"[:7])
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    security = master.ensure_security(issuer, class_designation="common stock")
    master.ensure_listing(security, "XNAS", valid_from="2000-01-01", is_primary=True)
    return security


# --------------------------------------------------------------------------- #
# Deterministic replay
# --------------------------------------------------------------------------- #
def test_ingestion_replay_is_byte_identical(tmp_path):
    submissions, facts, _, _ = load_fixture_payloads(RESTATEMENT_DIR, RESTATEMENT_CIK)
    dumps = []
    for run in (1, 2):
        db = _fresh_db(tmp_path / f"replay-{run}.db")
        try:
            SecIngestor(db).sync_payloads(
                RESTATEMENT_CIK,
                submissions_payload=submissions,
                companyfacts_payload=facts,
                observed_at="2026-01-01T00:00:00Z",
            )
            dumps.append(_evidence_dump(db))
        finally:
            db.close()
    assert dumps[0], "the replay must produce evidence"
    assert dumps[0] == dumps[1], "identical inputs must produce identical stored records"


def test_replay_produces_identical_as_of_answers(tmp_path):
    submissions, facts, _, _ = load_fixture_payloads(RESTATEMENT_DIR, RESTATEMENT_CIK)
    answers = []
    for run in (1, 2):
        db = _fresh_db(tmp_path / f"answers-{run}.db")
        try:
            report = SecIngestor(db).sync_payloads(
                RESTATEMENT_CIK,
                submissions_payload=submissions,
                companyfacts_payload=facts,
                observed_at="2026-01-01T00:00:00Z",
            )
            result = EvidenceKernel(db).as_of(report.issuer_id, "2024-06-01T00:00:00Z")
            answers.append(result.to_dict())
        finally:
            db.close()
    assert answers[0] == answers[1]


def test_second_ingest_is_a_no_op(tmp_path):
    submissions, facts, _, _ = load_fixture_payloads(RESTATEMENT_DIR, RESTATEMENT_CIK)
    db = _fresh_db(tmp_path / "idempotent.db")
    try:
        ingestor = SecIngestor(db)
        first = ingestor.sync_payloads(
            RESTATEMENT_CIK, submissions_payload=submissions, companyfacts_payload=facts,
            observed_at="2026-01-01T00:00:00Z",
        )
        before = _evidence_dump(db)
        second = ingestor.sync_payloads(
            RESTATEMENT_CIK, submissions_payload=submissions, companyfacts_payload=facts,
            observed_at="2026-01-02T00:00:00Z",
        )
        assert _evidence_dump(db) == before
        assert second.evidence["inserted"] == 0
        assert second.evidence["superseding"] == 0
        assert second.evidence["duplicates"] == first.evidence["inserted"] + first.evidence["superseding"]
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Parquet and provider independence
# --------------------------------------------------------------------------- #
def test_parquet_import_matches_csv(tmp_path):
    pyarrow = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    csv_path = _write_csv(
        tmp_path / "bars.csv",
        ["Date", "Open", "High", "Low", "Close", "Volume"],
        ROWS,
    )
    table = pyarrow.table(
        {
            "Date": [row[0] for row in ROWS],
            "Open": [float(row[1]) for row in ROWS],
            "High": [float(row[2]) for row in ROWS],
            "Low": [float(row[3]) for row in ROWS],
            "Close": [float(row[4]) for row in ROWS],
            "Volume": [int(row[5]) for row in ROWS],
        }
    )
    parquet_path = tmp_path / "bars.parquet"
    pq.write_table(table, parquet_path)

    from_csv = import_csv_bars(csv_path, security_id="SEC-TEST", mic="XNAS", source_id="csv-import")
    from_parquet = import_parquet_bars(
        parquet_path, security_id="SEC-TEST", mic="XNAS", source_id="csv-import"
    )
    assert [bar.to_dict() for bar in from_csv.bars] == [bar.to_dict() for bar in from_parquet.bars]
    assert from_parquet.columns["format"] == "parquet"
    assert not from_parquet.issues


def test_provider_column_aliases_and_order_do_not_change_values(tmp_path):
    canonical = _write_csv(
        tmp_path / "canonical.csv",
        ["date", "open", "high", "low", "close", "volume"],
        ROWS,
    )
    vendor = _write_csv(
        tmp_path / "vendor.csv",
        ["Timestamp", "Volume", "Close", "Low", "High", "Open"],
        [(row[0], row[5], row[4], row[3], row[2], row[1]) for row in ROWS],
    )
    first = import_csv_bars(canonical, security_id="SEC-A", mic="XNAS", source_id="csv-import")
    second = import_csv_bars(vendor, security_id="SEC-A", mic="XNAS", source_id="csv-import")
    assert [bar.ohlcv() for bar in first.bars] == [bar.ohlcv() for bar in second.bars]
    assert [bar.ts_utc for bar in first.bars] == [bar.ts_utc for bar in second.bars]


def test_adjusted_only_file_is_refused(tmp_path):
    from atlas.core.errors import NotSupportedError

    path = _write_csv(
        tmp_path / "adjusted.csv",
        ["Date", "Adj Close"],
        [(row[0], row[4]) for row in ROWS],
    )
    with pytest.raises(Exception) as excinfo:
        import_csv_bars(path, security_id="SEC-A", mic="XNAS", source_id="csv-import")
    assert "adjusted" in str(excinfo.value).lower() or isinstance(excinfo.value, NotSupportedError)


def test_two_providers_keep_separate_raw_series(db):
    from atlas.storage.sources import SourceRegistry

    registry = SourceRegistry(db)
    provider_a = registry.ensure_custom("provider a", kind="csv_import")
    provider_b = registry.ensure_custom("provider b", kind="csv_import")
    security = _security(db, "Provider Test Corp")
    store = BarStore(db)
    bar_a = Bar(
        security_id=security, mic="XNAS", ts_utc="2024-01-02T21:00:00Z",
        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100.5"),
        volume=Decimal("1000"), currency="USD", source_id=provider_a,
    )
    bar_b = Bar(
        security_id=security, mic="XNAS", ts_utc="2024-01-02T21:00:00Z",
        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100.6"),
        volume=Decimal("1000"), currency="USD", source_id=provider_b,
    )
    store.ingest([bar_a, bar_b])

    rows = db.query(
        "SELECT source_id, close FROM bar WHERE security_id = ? ORDER BY source_id", (security,)
    )
    assert [row["source_id"] for row in rows] == sorted([provider_a, provider_b])
    assert [row["close"] for row in rows] == ["100.5", "100.6"]
    # Neither provider's observation replaced the other's: raw history is per source.
    assert len(store.query(security, "XNAS", "2024-01-02", "2024-01-02")) == 2


def test_identical_provider_data_is_idempotent(db):
    security = _security(db, "Idempotent Corp")
    store = BarStore(db)
    bar = Bar(
        security_id=security, mic="XNAS", ts_utc="2024-01-02T21:00:00Z",
        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100.5"),
        volume=Decimal("1000"), currency="USD", source_id="csv-import",
    )
    first = store.ingest([bar])
    second = store.ingest([bar])
    assert first.inserted == 1
    assert second.duplicates == 1
    assert db.scalar("SELECT COUNT(*) FROM bar WHERE security_id = ?", (security,)) == 1
