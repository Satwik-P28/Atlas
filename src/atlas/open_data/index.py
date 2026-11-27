"""SQLite index over snapshots and observations (separate from the evidence schema).

The index keeps three distinctions that dashboards must not conflate:

* a *discovered* dataset (in the registry),
* an *acquired* snapshot (raw bytes verified and stored),
* an *integrated* observation (a typed, queryable record with a point-in-time field).

Observations are append-only. An identical record is skipped; a changed value for the
same natural key becomes a new ``revision_seq`` that supersedes the previous row. The
old value is never overwritten, so a restatement is visible rather than silently
applied to history.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_INDEX = "var/open_data/atlas_open_data.db"
INDEX_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS od_schema (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS dataset (
    dataset_id      TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    title           TEXT NOT NULL,
    rights_class    TEXT NOT NULL,
    license_name    TEXT NOT NULL,
    license_url     TEXT,
    redistribution  INTEGER NOT NULL,
    commercial_use  INTEGER NOT NULL,
    registry_hash   TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acquisition_run (
    run_id              TEXT PRIMARY KEY,
    dataset_id          TEXT NOT NULL,
    mode                TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,        -- running | acquired | not_modified | blocked | failed
    http_status         INTEGER,
    downloaded_bytes    INTEGER NOT NULL DEFAULT 0,
    decompressed_bytes  INTEGER NOT NULL DEFAULT 0,
    file_count          INTEGER NOT NULL DEFAULT 0,
    record_count        INTEGER NOT NULL DEFAULT 0,
    entity_count        INTEGER NOT NULL DEFAULT 0,
    obs_start           TEXT,
    obs_end             TEXT,
    validation_failures INTEGER NOT NULL DEFAULT 0,
    sha256              TEXT,
    elapsed_seconds     REAL,
    snapshot_id         TEXT,
    error               TEXT,
    stats_json          TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_run_dataset ON acquisition_run (dataset_id, started_at);

CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id        TEXT NOT NULL,
    dataset_id         TEXT NOT NULL,
    path               TEXT NOT NULL,
    manifest_sha256    TEXT NOT NULL,
    completed_at       TEXT NOT NULL,
    etag               TEXT,
    last_modified      TEXT,
    bytes              INTEGER NOT NULL DEFAULT 0,
    file_count         INTEGER NOT NULL DEFAULT 0,
    record_count       INTEGER NOT NULL DEFAULT 0,
    entity_count       INTEGER NOT NULL DEFAULT 0,
    obs_start          TEXT,
    obs_end            TEXT,
    validation_status  TEXT NOT NULL,          -- valid | invalid
    rights_class       TEXT NOT NULL,
    redistributable    INTEGER NOT NULL,
    manifest_json      TEXT NOT NULL,
    PRIMARY KEY (snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_dataset ON snapshot (dataset_id, completed_at);

CREATE TABLE IF NOT EXISTS artifact (
    snapshot_id   TEXT NOT NULL,
    name          TEXT NOT NULL,
    path          TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    content_type  TEXT,
    records       INTEGER,
    PRIMARY KEY (snapshot_id, name)
);

CREATE TABLE IF NOT EXISTS entity (
    entity_id    TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    name         TEXT,
    provider     TEXT,
    identifiers_json TEXT NOT NULL DEFAULT '{}',
    first_snapshot TEXT,
    last_snapshot  TEXT
);

CREATE TABLE IF NOT EXISTS observation (
    observation_id       TEXT PRIMARY KEY,
    dataset_id           TEXT NOT NULL,
    series_key           TEXT NOT NULL,
    entity_id            TEXT,
    concept              TEXT,
    obs_date             TEXT,
    period_start         TEXT,
    period_end           TEXT,
    value_numeric        TEXT,
    value_text           TEXT,
    unit                 TEXT,
    currency             TEXT,
    published_at         TEXT,
    provider_revision_at TEXT,
    ingested_at          TEXT NOT NULL,
    availability_basis   TEXT NOT NULL,
    snapshot_id          TEXT NOT NULL,
    record_hash          TEXT NOT NULL,
    revision_seq         INTEGER NOT NULL DEFAULT 1,
    supersedes           TEXT,
    UNIQUE (dataset_id, record_hash)
);
CREATE INDEX IF NOT EXISTS idx_obs_series ON observation (dataset_id, series_key, obs_date);
CREATE INDEX IF NOT EXISTS idx_obs_entity ON observation (entity_id, concept, obs_date);
CREATE INDEX IF NOT EXISTS idx_obs_published ON observation (published_at);

CREATE TABLE IF NOT EXISTS issue (
    issue_id    TEXT PRIMARY KEY,
    dataset_id  TEXT NOT NULL,
    snapshot_id TEXT,
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL,       -- info | warning | error
    detail      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (dataset_id, snapshot_id, code, detail)
);

CREATE TABLE IF NOT EXISTS coverage (
    dataset_id        TEXT PRIMARY KEY,
    obs_start         TEXT,
    obs_end           TEXT,
    records           INTEGER NOT NULL DEFAULT 0,  -- typed observations indexed
    acquired_records  INTEGER NOT NULL DEFAULT 0,  -- records counted in the provider payload
    entities          INTEGER NOT NULL DEFAULT 0,
    series            INTEGER NOT NULL DEFAULT 0,
    missing_json      TEXT NOT NULL DEFAULT '[]',
    computed_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rights_audit (
    dataset_id  TEXT PRIMARY KEY,
    decision    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    audited_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integration (
    dataset_id   TEXT NOT NULL,
    snapshot_id  TEXT NOT NULL,
    target       TEXT NOT NULL,
    records      INTEGER NOT NULL DEFAULT 0,
    entities     INTEGER NOT NULL DEFAULT 0,
    integrated_at TEXT NOT NULL,
    PRIMARY KEY (dataset_id, snapshot_id, target)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Observation:
    dataset_id: str
    series_key: str
    obs_date: str | None
    value_numeric: str | None = None
    value_text: str | None = None
    unit: str | None = None
    currency: str | None = None
    entity_id: str | None = None
    concept: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    published_at: str | None = None
    provider_revision_at: str | None = None
    availability_basis: str = "publication_date_unknown"
    source_url: str | None = None

    def natural_key(self) -> tuple:
        return (self.dataset_id, self.series_key, self.obs_date or "",
                self.period_start or "", self.period_end or "")

    def record_hash(self) -> str:
        return _hash({
            "dataset_id": self.dataset_id,
            "series_key": self.series_key,
            "entity_id": self.entity_id,
            "concept": self.concept,
            "obs_date": self.obs_date,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "value_numeric": self.value_numeric,
            "value_text": self.value_text,
            "unit": self.unit,
            "currency": self.currency,
            "published_at": self.published_at,
        })

    def observation_id(self) -> str:
        return _hash({"hash": self.record_hash(), "rev": self.natural_key()})


class OpenDataIndex:
    def __init__(self, path: str | Path = DEFAULT_INDEX) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=180.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=180000")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(_SCHEMA)
        row = self.connection.execute("SELECT version FROM od_schema").fetchone()
        if row is None:
            self.connection.execute("INSERT INTO od_schema (version) VALUES (?)", (INDEX_VERSION,))
        elif int(row["version"]) != INDEX_VERSION:
            raise RuntimeError(f"open-data index schema {row['version']} != {INDEX_VERSION}")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "OpenDataIndex":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ----------------------------------------------------------------- registry
    def register(self, entry: Mapping[str, Any]) -> str:
        digest = _hash(entry)
        self.connection.execute(
            """INSERT INTO dataset (dataset_id, provider, title, rights_class, license_name, license_url,
                                    redistribution, commercial_use, registry_hash, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(dataset_id) DO UPDATE SET
                 provider=excluded.provider, title=excluded.title, rights_class=excluded.rights_class,
                 license_name=excluded.license_name, license_url=excluded.license_url,
                 redistribution=excluded.redistribution, commercial_use=excluded.commercial_use,
                 registry_hash=excluded.registry_hash, updated_at=excluded.updated_at""",
            (entry["id"], entry["provider"], entry["title"], entry["rights_class"],
             entry["license_name"], entry.get("license_url"),
             int(bool(entry.get("redistribution"))), int(bool(entry.get("commercial_use"))),
             digest, _now()),
        )
        self.connection.commit()
        return digest

    def record_rights_audit(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            self.connection.execute(
                "INSERT OR REPLACE INTO rights_audit (dataset_id, decision, reason, audited_at) VALUES (?,?,?,?)",
                (row["id"], "allow" if row["distribution_allowed"] else "deny", row["reason"], _now()),
            )
        self.connection.commit()

    # --------------------------------------------------------------------- runs
    def start_run(self, dataset_id: str, mode: str) -> str:
        run_id = f"{dataset_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.connection.execute(
            "INSERT INTO acquisition_run (run_id, dataset_id, mode, started_at, status) VALUES (?,?,?,?,?)",
            (run_id, dataset_id, mode, _now(), "running"),
        )
        self.connection.commit()
        return run_id

    def finish_run(self, run_id: str, *, status: str, **fields: Any) -> None:
        allowed = {
            "http_status", "downloaded_bytes", "decompressed_bytes", "file_count", "record_count",
            "entity_count", "obs_start", "obs_end", "validation_failures", "sha256",
            "elapsed_seconds", "snapshot_id", "error", "stats_json",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        if "stats_json" in clean and not isinstance(clean["stats_json"], str):
            clean["stats_json"] = json.dumps(clean["stats_json"], sort_keys=True, default=str)
        assignments = ", ".join(f"{key}=?" for key in clean)
        sql = f"UPDATE acquisition_run SET status=?, finished_at=?{', ' + assignments if assignments else ''} WHERE run_id=?"
        self.connection.execute(sql, (status, _now(), *clean.values(), run_id))
        self.connection.commit()

    # ---------------------------------------------------------------- snapshots
    def record_snapshot(self, snapshot, *, validation_status: str, rights_class: str,
                        redistributable: bool, stats: Mapping[str, Any]) -> None:
        manifest = snapshot.manifest
        self.connection.execute(
            """INSERT OR REPLACE INTO snapshot
               (snapshot_id, dataset_id, path, manifest_sha256, completed_at, etag, last_modified,
                bytes, file_count, record_count, entity_count, obs_start, obs_end,
                validation_status, rights_class, redistributable, manifest_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot.snapshot_id, snapshot.dataset_id, str(snapshot.path), snapshot.manifest_sha256,
                manifest.get("completed_at") or _now(),
                manifest.get("source", {}).get("etag") if isinstance(manifest.get("source"), dict) else None,
                manifest.get("source", {}).get("last_modified") if isinstance(manifest.get("source"), dict) else None,
                sum(int(f.get("bytes") or 0) for f in snapshot.files),
                len(snapshot.files), int(stats.get("record_count") or 0),
                int(stats.get("entity_count") or 0), stats.get("obs_start"), stats.get("obs_end"),
                validation_status, rights_class, int(redistributable),
                json.dumps(manifest, sort_keys=True, default=str),
            ),
        )
        for entry in snapshot.files:
            self.connection.execute(
                """INSERT OR REPLACE INTO artifact (snapshot_id, name, path, bytes, sha256, content_type, records)
                   VALUES (?,?,?,?,?,?,?)""",
                (snapshot.snapshot_id, entry["name"], entry["path"], entry["bytes"],
                 entry["sha256"], entry.get("content_type"), entry.get("record_count")),
            )
        for issue in stats.get("issues") or []:
            self.connection.execute(
                "INSERT OR IGNORE INTO issue (issue_id, dataset_id, snapshot_id, code, severity, detail, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (_hash({"d": snapshot.dataset_id, "s": snapshot.snapshot_id, "i": issue}), snapshot.dataset_id,
                 snapshot.snapshot_id, issue.get("code", "validation"), issue.get("severity", "warning"),
                 str(issue.get("detail") or issue)[:2000], _now()),
            )
        self.connection.execute(
            """INSERT INTO coverage (dataset_id, obs_start, obs_end, records, acquired_records, entities,
                                      series, missing_json, computed_at)
               VALUES (?,?,?,0,?,?,?,COALESCE((SELECT missing_json FROM coverage WHERE dataset_id=?),'[]'),?)
               ON CONFLICT(dataset_id) DO UPDATE SET
                 obs_start=COALESCE(excluded.obs_start, coverage.obs_start),
                 obs_end=COALESCE(excluded.obs_end, coverage.obs_end),
                 acquired_records=excluded.acquired_records,
                 entities=MAX(coverage.entities, excluded.entities),
                 series=MAX(coverage.series, excluded.series),
                 computed_at=excluded.computed_at""",
            (snapshot.dataset_id, stats.get("obs_start"), stats.get("obs_end"),
             int(stats.get("record_count") or 0), int(stats.get("entity_count") or 0),
             int(stats.get("series_count") or 0), snapshot.dataset_id, _now()),
        )
        self.connection.commit()

    # -------------------------------------------------------------- observations
    def upsert_entity(self, entity_id: str, *, kind: str, name: str | None = None,
                      provider: str | None = None, identifiers: Mapping[str, Any] | None = None,
                      snapshot_id: str | None = None) -> None:
        self.connection.execute(
            """INSERT INTO entity (entity_id, kind, name, provider, identifiers_json, first_snapshot, last_snapshot)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(entity_id) DO UPDATE SET
                 name=COALESCE(excluded.name, entity.name),
                 identifiers_json=CASE WHEN excluded.identifiers_json <> '{}'
                                       THEN excluded.identifiers_json ELSE entity.identifiers_json END,
                 last_snapshot=COALESCE(excluded.last_snapshot, entity.last_snapshot)""",
            (entity_id, kind, name, provider, json.dumps(dict(identifiers or {}), sort_keys=True),
             snapshot_id, snapshot_id),
        )

    def ingest_observations(self, observations: Iterable[Observation], *, snapshot_id: str,
                            batch_size: int = 5000) -> dict[str, int]:
        inserted = 0
        duplicates = 0
        revisions = 0
        skipped = 0
        batch: list[tuple] = []
        now = _now()
        dataset_ids = {observation.dataset_id for observation in observations}
        if not dataset_ids:
            return {"inserted": 0, "duplicates": 0, "revisions": 0, "skipped": 0}
        existing_hashes = {
            row[0] for row in self.connection.execute(
                f"SELECT record_hash FROM observation WHERE dataset_id IN ({','.join('?' for _ in dataset_ids)})",
                tuple(dataset_ids),
            )
        }
        latest: dict[tuple, tuple[str, int]] = {}
        for row in self.connection.execute(
            """SELECT observation_id, revision_seq, dataset_id, series_key, obs_date,
                      period_start, period_end FROM observation
               WHERE dataset_id IN ({}) ORDER BY revision_seq""".format(
                ','.join('?' for _ in dataset_ids)),
            tuple(dataset_ids),
        ):
            latest[(row["dataset_id"], row["series_key"], row["obs_date"] or "",
                    row["period_start"] or "", row["period_end"] or "")] = (
                row["observation_id"], int(row["revision_seq"]))
        self.connection.execute("BEGIN")
        try:
            for observation in observations:
                if (observation.value_numeric is None and observation.value_text is None) or not observation.series_key:
                    skipped += 1
                    continue
                digest = observation.record_hash()
                if digest in existing_hashes:
                    duplicates += 1
                    continue
                key = observation.natural_key()
                previous = latest.get(key)
                revision = previous[1] + 1 if previous else 1
                supersedes = previous[0] if previous else None
                if previous:
                    revisions += 1
                observation_id = observation.observation_id()
                batch.append((
                    observation_id, observation.dataset_id, observation.series_key,
                    observation.entity_id, observation.concept, observation.obs_date,
                    observation.period_start, observation.period_end, observation.value_numeric,
                    observation.value_text, observation.unit, observation.currency,
                    observation.published_at, observation.provider_revision_at, now,
                    observation.availability_basis, snapshot_id, digest, revision, supersedes,
                ))
                existing_hashes.add(digest)
                latest[key] = (observation_id, revision)
                inserted += 1
                if len(batch) >= batch_size:
                    self._flush(batch)
                    batch = []
            if batch:
                self._flush(batch)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        self._refresh_coverage(dataset_ids)
        return {"inserted": inserted, "duplicates": duplicates, "revisions": revisions, "skipped": skipped}

    def _flush(self, batch: list[tuple]) -> None:
        self.connection.executemany(
            """INSERT INTO observation (observation_id, dataset_id, series_key, entity_id, concept, obs_date,
                                        period_start, period_end, value_numeric, value_text, unit, currency,
                                        published_at, provider_revision_at, ingested_at, availability_basis,
                                        snapshot_id, record_hash, revision_seq, supersedes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            batch,
        )

    def _refresh_coverage(self, dataset_ids: set[str]) -> None:
        rows = self.connection.execute(
            """SELECT dataset_id, MIN(obs_date) AS obs_start, MAX(obs_date) AS obs_end,
                      COUNT(*) AS records, COUNT(DISTINCT entity_id) AS entities,
                      COUNT(DISTINCT series_key) AS series
               FROM observation GROUP BY dataset_id"""
        ).fetchall()
        for row in rows:
            self.connection.execute(
                """INSERT INTO coverage (dataset_id, obs_start, obs_end, records, entities, series, computed_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(dataset_id) DO UPDATE SET obs_start=excluded.obs_start, obs_end=excluded.obs_end,
                     records=excluded.records, entities=excluded.entities, series=excluded.series,
                     computed_at=excluded.computed_at""",
                (row["dataset_id"], row["obs_start"], row["obs_end"], row["records"],
                 row["entities"], row["series"], _now()),
            )
        self.connection.commit()

    def record_integration(self, dataset_id: str, snapshot_id: str, *, target: str,
                           records: int, entities: int) -> None:
        self.connection.execute(
            """INSERT INTO integration (dataset_id, snapshot_id, target, records, entities, integrated_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT(dataset_id, snapshot_id, target) DO UPDATE SET
                 records=excluded.records, entities=excluded.entities, integrated_at=excluded.integrated_at""",
            (dataset_id, snapshot_id, target, records, entities, _now()),
        )
        self.connection.commit()

    # ------------------------------------------------------------------ queries
    def observations(self, dataset_id: str, *, series_key: str | None = None,
                     start: str | None = None, end: str | None = None,
                     as_of: str | None = None, limit: int = 1000,
                     latest_only: bool = True) -> list[dict[str, Any]]:
        clauses = ["dataset_id=?"]
        params: list[Any] = [dataset_id]
        if series_key:
            clauses.append("series_key=?")
            params.append(series_key)
        if start:
            clauses.append("COALESCE(obs_date, period_end) >= ?")
            params.append(start)
        if end:
            clauses.append("COALESCE(obs_date, period_end) <= ?")
            params.append(end)
        if as_of:
            clauses.append("COALESCE(published_at, ingested_at) <= ?")
            params.append(as_of)
        if latest_only:
            clauses.append(
                "revision_seq = (SELECT MAX(o2.revision_seq) FROM observation o2 "
                "WHERE o2.dataset_id=observation.dataset_id AND o2.series_key=observation.series_key "
                "AND COALESCE(o2.obs_date,'')=COALESCE(observation.obs_date,'') "
                "AND COALESCE(o2.period_start,'')=COALESCE(observation.period_start,'') "
                "AND COALESCE(o2.period_end,'')=COALESCE(observation.period_end,''))"
            )
        params.append(int(limit))
        rows = self.connection.execute(
            f"SELECT * FROM observation WHERE {' AND '.join(clauses)} "
            "ORDER BY COALESCE(obs_date, period_end) DESC, series_key LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def status_rows(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT d.dataset_id, d.provider, d.title, d.rights_class, d.redistribution, d.commercial_use,
                      d.license_name, d.license_url,
                      (SELECT COUNT(*) FROM snapshot s WHERE s.dataset_id=d.dataset_id) AS snapshots,
                      (SELECT COUNT(*) FROM observation o WHERE o.dataset_id=d.dataset_id) AS observations,
                      (SELECT MAX(completed_at) FROM snapshot s WHERE s.dataset_id=d.dataset_id) AS last_snapshot,
                      (SELECT COUNT(*) FROM acquisition_run r WHERE r.dataset_id=d.dataset_id AND r.status='failed') AS failures,
                      (SELECT MAX(integrated_at) FROM integration i WHERE i.dataset_id=d.dataset_id) AS last_integrated,
                      (SELECT MAX(finished_at) FROM acquisition_run r WHERE r.dataset_id=d.dataset_id
                         AND r.status IN ('acquired','not_modified')) AS last_success,
                      c.obs_start, c.obs_end, c.records, c.acquired_records, c.entities, c.series
               FROM dataset d LEFT JOIN coverage c ON c.dataset_id=d.dataset_id
               ORDER BY d.provider, d.dataset_id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def dashboard(self) -> dict[str, Any]:
        def one(sql: str, params: Sequence[Any] = ()) -> Any:
            row = self.connection.execute(sql, params).fetchone()
            return row[0] if row else None

        discovered = int(one("SELECT COUNT(*) FROM dataset") or 0)
        approved = int(one("SELECT COUNT(*) FROM rights_audit WHERE decision='allow'") or 0)
        downloaded = int(one("SELECT COUNT(DISTINCT dataset_id) FROM snapshot") or 0)
        integrated = int(one("SELECT COUNT(DISTINCT dataset_id) FROM integration") or 0)
        with_observations = int(one("SELECT COUNT(DISTINCT dataset_id) FROM observation") or 0)
        published = int(one("SELECT COUNT(DISTINCT dataset_id) FROM snapshot WHERE redistributable=1") or 0)
        entities = int(one("SELECT COUNT(*) FROM entity") or 0)
        observations = int(one("SELECT COUNT(*) FROM observation") or 0)
        return {
            "datasets_discovered": discovered,
            "datasets_rights_approved": approved,
            "datasets_downloaded": downloaded,
            "datasets_integrated": integrated,
            "datasets_with_observations": with_observations,
            "datasets_publicly_distributable": published,
            "entities": entities,
            "observations": observations,
            "observation_series": int(one("SELECT COUNT(DISTINCT dataset_id || '|' || series_key) FROM observation") or 0),
            "snapshots": int(one("SELECT COUNT(*) FROM snapshot") or 0),
            "raw_bytes": int(one(
                "SELECT COALESCE(SUM(s.bytes),0) FROM snapshot s WHERE s.completed_at = "
                "(SELECT MAX(x.completed_at) FROM snapshot x WHERE x.dataset_id=s.dataset_id)"
            ) or 0),
            "failed_runs": int(one("SELECT COUNT(*) FROM acquisition_run WHERE status='failed'") or 0),
            "acquired_runs": int(one("SELECT COUNT(*) FROM acquisition_run WHERE status='acquired'") or 0),
            "quarantined": int(one("SELECT COUNT(*) FROM issue WHERE severity='error'") or 0),
            "coverage": [dict(row) for row in self.connection.execute(
                "SELECT * FROM coverage ORDER BY dataset_id").fetchall()],
            "freshness": [dict(row) for row in self.connection.execute(
                """SELECT dataset_id, MAX(completed_at) AS last_snapshot,
                          MAX(CASE WHEN validation_status='valid' THEN completed_at END) AS last_validated
                   FROM snapshot GROUP BY dataset_id ORDER BY dataset_id""").fetchall()],
            "licensing": [dict(row) for row in self.connection.execute(
                "SELECT rights_class, COUNT(*) AS datasets FROM dataset GROUP BY rights_class ORDER BY rights_class"
            ).fetchall()],
            "failures": [dict(row) for row in self.connection.execute(
                """SELECT dataset_id, started_at, status, error, http_status
                   FROM acquisition_run WHERE status IN ('failed','blocked')
                   ORDER BY started_at DESC LIMIT 25""").fetchall()],
        }
