"""Adversarial tests for checkpoint identity and transactional integration progress.

The property under test is that integration progress is bound to the destination
database and to the exact archive, and that a checkpoint can never cause an issuer to
be skipped after the database is deleted, replaced or rolled back.

Every fixture is a tiny synthetic companyfacts archive stored through the real
SnapshotStore; no network is used.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from atlas.open_data.engine import AcquisitionEngine
from atlas.open_data.integration import integrate_companyfacts, integration_progress
from atlas.storage.db import open_database

COMPANY_COUNT = 4


def _payload(number: int, *, name: str) -> dict:
    return {
        "cik": number,
        "entityName": name,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [{
                            "end": "2023-12-31",
                            "val": 1000 * number,
                            "accn": f"000000{number}-23-000001",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }]
                    },
                }
            }
        },
    }


def _engine(tmp_path: Path) -> AcquisitionEngine:
    engine = AcquisitionEngine(store_root=tmp_path / "store",
                               index_path=tmp_path / "index.db")
    archive = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for number in range(1, COMPANY_COUNT + 1):
            bundle.writestr(f"CIK{number:010d}.json",
                            json.dumps(_payload(number, name=f"Company {number}")))
    staging = engine.store.new_staging("sec.companyfacts")
    entry = engine.store.add_file(staging, archive, name="companyfacts.zip")
    engine.store.commit(staging, {
        "dataset_id": "sec.companyfacts",
        "source": {"download_endpoint": "https://www.sec.gov/Archives/edgar/xbrl/companyfacts.zip"},
        "retrieval": {"completed_at": "2026-11-25T00:00:00Z"},
        "files": [entry],
    })
    return engine


def _members(db_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM open_data_integration_member GROUP BY status")
        return {str(status): int(count) for status, count in rows}
    finally:
        connection.close()


def _events(result: dict) -> list[str]:
    return [str(event.get("kind")) for event in result["progress"]["events"]]


def _drop(path: Path) -> None:
    path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def test_a_deleted_and_recreated_database_does_not_inherit_the_checkpoint(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    database = tmp_path / "atlas.db"
    first = integrate_companyfacts(engine, database, limit=1, tickers=False)
    assert first["companies_total"] == 1
    checkpoint = Path(first["checkpoint"])
    assert checkpoint.exists()
    first_uuid = first["database_uuid"]

    _drop(database)
    second = integrate_companyfacts(engine, database, limit=2, tickers=False)

    assert second["database_uuid"] != first_uuid
    assert "checkpoint_not_used" in _events(second)
    # The new database integrates its own two issuers rather than trusting the
    # checkpoint's one processed issuer.
    assert second["companies_this_run"] == 2
    assert second["companies_total"] == 2
    assert sum(_members(database).values()) == 2


def test_a_replaced_database_with_its_own_identity_is_not_resumed(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    database = tmp_path / "atlas.db"
    first = integrate_companyfacts(engine, database, limit=2, tickers=False)

    replacement = tmp_path / "replacement.db"
    other = open_database(replacement)
    replacement_uuid = other.ensure_identity()
    other.close()

    _drop(database)
    shutil.copyfile(replacement, database)
    result = integrate_companyfacts(engine, database, limit=3, tickers=False)

    assert result["database_uuid"] == replacement_uuid != first["database_uuid"]
    assert "checkpoint_not_used" in _events(result)
    assert result["companies_total"] == 3
    assert sum(_members(database).values()) == 3


def test_a_rolled_back_database_reprocesses_the_missing_issuers(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    database = tmp_path / "atlas.db"
    integrate_companyfacts(engine, database, limit=1, tickers=False)

    backup = tmp_path / "backup.db"
    source = sqlite3.connect(database)
    target = sqlite3.connect(backup)
    source.backup(target)
    target.close()
    source.close()

    integrate_companyfacts(engine, database, limit=2, tickers=False)
    assert sum(_members(database).values()) == 2

    _drop(database)
    shutil.copyfile(backup, database)
    result = integrate_companyfacts(engine, database, limit=2, tickers=False)

    assert "checkpoint_ahead_of_database" in _events(result)
    assert result["companies_total"] == 2
    assert result["companies_this_run"] == 1
    assert sum(_members(database).values()) == 2


def test_a_checkpoint_claiming_evidence_that_is_gone_is_repaired(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    database = tmp_path / "atlas.db"
    first = integrate_companyfacts(engine, database, limit=2, tickers=False)
    snapshot_id = first["snapshot_id"]

    connection = sqlite3.connect(database)
    try:
        issuer_id = connection.execute(
            "SELECT issuer_id FROM issuer WHERE cik=?", ("0000000002",)).fetchone()[0]
        connection.execute("DELETE FROM evidence WHERE entity_id=?", (issuer_id,))
        connection.commit()
    finally:
        connection.close()

    result = integrate_companyfacts(engine, database, limit=2, tickers=False)

    assert "claims_absent_evidence" in _events(result)
    assert result["companies_this_run"] == 1
    restored = sqlite3.connect(database)
    try:
        count = restored.execute(
            "SELECT COUNT(*) FROM evidence WHERE entity_id=?", (issuer_id,)).fetchone()[0]
    finally:
        restored.close()
    assert count >= 1
    progress = integration_progress(database, snapshot_id=snapshot_id)
    assert sum(progress["members"].values()) == 2


def test_evidence_and_progress_commit_in_the_same_transaction(tmp_path: Path, monkeypatch) -> None:
    from atlas.open_data import integration as module

    engine = _engine(tmp_path)
    database = tmp_path / "atlas.db"

    def explode(*args, **kwargs):
        raise RuntimeError("simulated crash inside the evidence transaction")

    monkeypatch.setattr(module.EvidenceKernel, "ingest_many", explode)
    with pytest.raises(RuntimeError, match="simulated crash"):
        integrate_companyfacts(engine, database, limit=None, tickers=False)

    # The company that failed left neither evidence nor a progress row behind.
    assert sum(_members(database).values()) == 0
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    finally:
        connection.close()

    monkeypatch.undo()
    result = integrate_companyfacts(engine, database, limit=None, tickers=False)
    assert result["companies_total"] == COMPANY_COUNT
    assert sum(_members(database).values()) == COMPANY_COUNT


def test_progress_is_bound_to_the_archive_bytes(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    database = tmp_path / "atlas.db"
    integrate_companyfacts(engine, database, limit=1, tickers=False)

    connection = sqlite3.connect(database)
    try:
        connection.execute("UPDATE open_data_integration SET archive_sha256=?", ("0" * 64,))
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="archive bytes"):
        integrate_companyfacts(engine, database, limit=1, tickers=False)
    # The explicit recovery path discards the contradictory progress.
    restarted = integrate_companyfacts(engine, database, limit=1, tickers=False, restart=True)
    assert restarted["progress"]["resumed"] is False
    assert "restart_requested" in _events(restarted)
