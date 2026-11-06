"""SQLite persistence layer.

SQLite is chosen for Phase 1 because the platform is local-first, the working set
fits comfortably in one file, and it gives real ACID transactions with no server to
operate. See ``docs/adr/0003-storage-engine.md`` for the rejected alternatives and
the migration path to columnar/DuckDB analytics.

Durability settings (all explicit, none inherited from defaults):

* ``journal_mode=WAL`` so a reader never blocks an ingestion writer.
* ``synchronous=FULL`` so a committed ingestion survives an OS crash. Performance
  measurements in ``docs/BENCHMARKS.md`` cover this setting.
* ``foreign_keys=ON`` (off by default in SQLite) so referential invariants hold.
* ``busy_timeout`` so concurrent processes back off instead of failing instantly.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ..core.errors import MigrationError, StorageError
from .migrations import LATEST_VERSION, MIGRATIONS, Migration, validate_migration_chain

_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL,
    duration_ms INTEGER
);
"""


class Database:
    """A thin, explicit wrapper around one SQLite connection.

    Transactions are explicit and nestable (nested scopes use SAVEPOINTs), so an
    ingestion routine can be composed of smaller units without committing early.
    """

    def __init__(self, path: str | Path, *, timeout: float = 30.0, create: bool = True) -> None:
        self.path = str(path)
        if not create and not Path(self.path).exists():
            raise StorageError("database does not exist", path=self.path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(
                self.path,
                isolation_level=None,  # we manage transactions ourselves
                timeout=timeout,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:  # pragma: no cover - environment dependent
            raise StorageError("cannot open database", path=self.path, error=str(exc)) from exc
        self._conn.row_factory = sqlite3.Row
        self._depth = 0
        self._configure()

    # ------------------------------------------------------------------ setup
    def _configure(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()

    # ------------------------------------------------------------- primitives
    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        try:
            return self._conn.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            raise StorageError(f"integrity violation: {exc}", sql=sql[:200]) from exc
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise StorageError(f"database error: {exc}", sql=sql[:200]) from exc

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        try:
            self._conn.executemany(sql, rows)
        except sqlite3.IntegrityError as exc:
            raise StorageError(f"integrity violation: {exc}", sql=sql[:200]) from exc
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise StorageError(f"database error: {exc}", sql=sql[:200]) from exc

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        return list(self.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        return row[0]

    # ------------------------------------------------------------ transactions
    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator["Database"]:
        """Explicit transaction with savepoint-based nesting."""
        root = self._depth == 0
        if root:
            begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
            try:
                self._conn.execute(begin)
            except sqlite3.Error as exc:
                raise StorageError(f"cannot begin transaction: {exc}") from exc
        else:
            self._conn.execute(f"SAVEPOINT atlas_sp_{self._depth}")
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if root:
                self._conn.execute("ROLLBACK")
            else:
                self._conn.execute(f"ROLLBACK TO atlas_sp_{self._depth}")
                self._conn.execute(f"RELEASE atlas_sp_{self._depth}")
            raise
        else:
            self._depth -= 1
            if root:
                self._conn.execute("COMMIT")
            else:
                self._conn.execute(f"RELEASE atlas_sp_{self._depth}")

    @contextmanager
    def savepoint(self, name: str) -> Iterator["Database"]:
        """Named savepoint for partial rollback inside a larger ingestion."""
        self._conn.execute(f"SAVEPOINT {name}")
        try:
            yield self
        except BaseException:
            self._conn.execute(f"ROLLBACK TO {name}")
            self._conn.execute(f"RELEASE {name}")
            raise
        else:
            self._conn.execute(f"RELEASE {name}")

    # ------------------------------------------------------------- migrations
    def schema_version(self) -> int:
        """Read the applied version without creating anything."""
        exists = self.scalar(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
        )
        if not exists:
            return 0
        row = self.query_one("SELECT MAX(version) AS v FROM schema_migration")
        return int(row["v"]) if row and row["v"] is not None else 0

    def applied_migrations(self) -> list[sqlite3.Row]:
        if not self.schema_version():
            return []
        return self.query("SELECT version, name, applied_at, duration_ms FROM schema_migration ORDER BY version")

    def migrate(self, target: int | None = None) -> list[int]:
        """Apply pending migrations in order. Returns the versions applied."""
        validate_migration_chain()
        target = min(target or LATEST_VERSION, LATEST_VERSION)
        self.execute(_SCHEMA_TABLE)
        current = self.schema_version()
        if current > LATEST_VERSION:  # pragma: no cover - forward compatibility guard
            raise MigrationError(
                "database schema is newer than this Atlas build", database=current, supported=LATEST_VERSION
            )
        applied: list[int] = []
        for migration in MIGRATIONS:
            if migration.version <= current or migration.version > target:
                continue
            if self._apply(migration):
                applied.append(migration.version)
        return applied

    def _apply(self, migration: Migration) -> bool:
        import time

        started = time.perf_counter()
        try:
            with self.transaction():
                # Re-read under BEGIN IMMEDIATE. Another process may have committed
                # this migration between migrate()'s initial read and this lock.
                latest = self.scalar("SELECT MAX(version) FROM schema_migration", default=0) or 0
                if int(latest) >= migration.version:
                    return False
                # executescript issues an implicit COMMIT in sqlite3; run statements
                # individually so the DDL stays inside our transaction.
                for statement in _split_statements(migration.sql):
                    self._conn.execute(statement)
                duration_ms = int((time.perf_counter() - started) * 1000)
                self._conn.execute(
                    "INSERT INTO schema_migration (version, name, applied_at, duration_ms) VALUES (?,?,?,?)",
                    (migration.version, migration.name, _now_iso(), duration_ms),
                )
                return True
        except sqlite3.Error as exc:
            raise MigrationError(
                f"migration {migration.version} ({migration.name}) failed: {exc}", version=migration.version
            ) from exc

    def needs_migration(self) -> bool:
        return self.schema_version() < LATEST_VERSION

    # ---------------------------------------------------------------- utility
    def tables(self) -> list[str]:
        rows = self.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [row["name"] for row in rows]

    def row_count(self, table: str) -> int:
        if not _SAFE_IDENTIFIER(table):
            raise StorageError("unsafe table identifier", table=table)
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}", default=0) or 0)

    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))

    def foreign_key_violations(self) -> list[sqlite3.Row]:
        return self.query("PRAGMA foreign_key_check")

    def backup_to(self, path: str | Path) -> str:
        """Write a consistent SQLite backup and return its SHA-256."""
        import hashlib

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as destination:
            self._conn.backup(destination)
        return hashlib.sha256(target.read_bytes()).hexdigest()

    def checkpoint(self) -> None:
        """Fold the WAL back into the main database file."""
        self.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover - closing twice
            pass

    def reopen(self) -> None:
        """Close and reopen the underlying connection (restart-safety tests)."""
        path = self.path
        self.close()
        self.__init__(path)  # type: ignore[misc]

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _split_statements(sql: str) -> list[str]:
    """Split a migration script on top-level semicolons.

    Migrations contain no trigger bodies or embedded semicolons inside strings, so a
    simple split is correct here; the guard keeps that assumption visible.
    """
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _now_iso() -> str:
    from ..core.temporal import iso, utcnow

    return iso(utcnow())


def _SAFE_IDENTIFIER(name: str) -> bool:
    return bool(name) and all(ch.isalnum() or ch == "_" for ch in name)


def open_database(path: str | Path, *, migrate: bool = True) -> Database:
    """Open (and by default migrate) an Atlas database."""
    db = Database(path)
    if migrate:
        db.migrate()
    return db
