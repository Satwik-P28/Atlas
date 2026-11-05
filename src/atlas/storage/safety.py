"""Guarded database migration with integrity checks and a pre-upgrade backup."""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path
from typing import Any

from ..core.errors import MigrationError
from .db import Database
from .migrations import LATEST_VERSION


def _check(db: Database, label: str) -> None:
    state = db.integrity_check()
    if str(state).lower() != "ok":
        raise MigrationError("database integrity check failed", stage=label, result=state)
    violations = db.foreign_key_violations()
    if violations:
        raise MigrationError("database foreign-key check failed", stage=label,
                             violations=len(violations))


def _backup(db: Database, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    source = Path(db.path)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"{source.name}.pre-migration-{stamp}.bak"
    target = sqlite3.connect(destination)
    try:
        db.connection.backup(target)
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
    verify = Database(destination, create=False)
    try:
        _check(verify, "backup")
    finally:
        verify.close()
    return destination


def migrate_safely(db: Database, *, backup_dir: str | Path | None = None) -> dict[str, Any]:
    """Check, back up, migrate and re-check. A failed migration commits no DDL."""
    current = db.schema_version()
    _check(db, "before")
    if current > LATEST_VERSION:
        raise MigrationError("database schema is newer than this Atlas build", database=current,
                             supported=LATEST_VERSION)
    if current == LATEST_VERSION:
        return {
            "schema": "atlas.migration.safety.v1",
            "database": db.path,
            "from_version": current,
            "to_version": current,
            "migrations_applied": [],
            "backup_path": None,
            "status": "already_current",
        }
    backup_path = None
    if db.path != ":memory:":
        target = Path(backup_dir) if backup_dir else Path(db.path).parent / "backups"
        backup_path = _backup(db, target)
    try:
        applied = db.migrate()
        _check(db, "after")
        final = db.schema_version()
        if final != LATEST_VERSION:
            raise MigrationError("migration did not reach the supported schema", found=final,
                                 supported=LATEST_VERSION)
    except Exception as exc:
        raise MigrationError(
            f"migration failed; the pre-upgrade backup is retained at {backup_path}",
            from_version=current, backup_path=str(backup_path) if backup_path else None,
            error=str(exc),
        ) from exc
    return {
        "schema": "atlas.migration.safety.v1",
        "database": db.path,
        "from_version": current,
        "to_version": LATEST_VERSION,
        "migrations_applied": applied,
        "backup_path": str(backup_path) if backup_path else None,
        "status": "migrated",
        "note": "SQLite DDL and version rows commit in one transaction; a failed migration is rolled back.",
    }


__all__ = ["migrate_safely"]
