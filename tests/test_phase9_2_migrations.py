"""Adversarial schema-migration tests for Phase 9.2."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from atlas.core.errors import MigrationError
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION, Migration


def _populate(db: Database) -> None:
    db.execute(
        "INSERT INTO source (source_id,name,kind,licence,redistribution,created_at) "
        "VALUES ('fixture','Fixture','manual','public_domain','public_domain','2026-01-01T00:00:00Z')"
    )
    db.execute(
        "INSERT INTO issuer (issuer_id,cik,legal_name,created_at,updated_at) "
        "VALUES ('ISS-1','1','Preserved Co','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )


def test_fresh_install_reaches_explicit_version(tmp_path):
    db = Database(tmp_path / "fresh.db")
    assert db.schema_version() == 0
    assert db.migrate() == list(range(1, 14))
    assert db.schema_version() == LATEST_VERSION == 13
    tables = set(db.tables())
    assert {"regulatory_entity", "regulatory_observation", "entity_reconciliation",
            "market_price_series"} <= tables
    assert db.migrate() == []
    db.close()


def test_populated_phase9_1_database_upgrades_without_data_loss(tmp_path):
    path = tmp_path / "upgrade.db"
    db = Database(path)
    assert db.migrate(target=10) == list(range(1, 11))
    _populate(db)
    db.close()

    upgraded = Database(path, create=False)
    assert upgraded.migrate() == [11, 12, 13]
    assert upgraded.scalar("SELECT legal_name FROM issuer WHERE issuer_id='ISS-1'") == "Preserved Co"
    assert upgraded.schema_version() == 13
    upgraded.close()


def test_interrupted_migration_rolls_back_and_is_retryable(tmp_path):
    db = Database(tmp_path / "interrupted.db")
    db.migrate()
    before = db.schema_version()
    bad = Migration(version=99, name="interrupted", sql=(
        "CREATE TABLE migration_probe (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO table_that_does_not_exist VALUES (1);"
    ))
    with pytest.raises(MigrationError):
        db._apply(bad)
    assert db.schema_version() == before
    assert "migration_probe" not in db.tables()
    assert db.scalar("SELECT COUNT(*) FROM schema_migration WHERE version=99") == 0
    db.close()


def test_concurrent_startup_applies_each_migration_once(tmp_path):
    path = tmp_path / "concurrent.db"
    seed = Database(path)
    seed.migrate(target=10)
    seed.close()

    def run() -> int:
        local = Database(path, create=False)
        try:
            local.migrate()
            return local.schema_version()
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = list(pool.map(lambda _: run(), range(2)))
    assert versions == [13, 13]
    check = Database(path, create=False)
    assert check.scalar("SELECT COUNT(*) FROM schema_migration WHERE version IN (11,12,13)") == 3
    check.close()


def test_service_constructor_is_read_only(tmp_path):
    path = tmp_path / "readonly.db"
    db = Database(path)
    db.migrate(target=10)
    assert "regulatory_entity" not in db.tables()
    EquityResearchService(db)
    assert "regulatory_entity" not in db.tables()
    assert db.schema_version() == 10
    db.close()


def test_backup_is_openable_and_matches_integrity(tmp_path):
    db = Database(tmp_path / "backup.db")
    db.migrate()
    _populate(db)
    digest = db.backup_to(tmp_path / "verified-backup.db")
    assert len(digest) == 64
    restored = Database(tmp_path / "verified-backup.db", create=False)
    assert restored.integrity_check() == "ok"
    assert restored.scalar("SELECT legal_name FROM issuer") == "Preserved Co"
    restored.close()
    db.close()
