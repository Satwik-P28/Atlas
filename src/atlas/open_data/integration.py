"""Bridge from acquired SEC bulk snapshots into the existing Atlas evidence kernel.

This is deliberately narrow. Company facts have an existing, tested normaliser
(``atlas.ingestion.sec_companyfacts``) and an existing point-in-time evidence model, so
the bridge reuses both rather than inventing a second interpretation of XBRL. Macro and
other non-issuer series stay in the open-data index, which exposes them through a
typed query API; forcing them into ``evidence.entity_kind`` would be a lie.

The bridge is built for the full archive, not a demonstration:

* members are read one at a time in sorted order, so memory is bounded by the largest
  single company payload rather than the archive;
* every company is committed before the next one starts, and a checkpoint records the
  processed CIKs, so an interrupted run resumes instead of re-parsing;
* evidence is written in batched transactions;
* identity is the permanent SEC CIK, never a ticker;
* ticker assignments are recorded with an interval and prior assignments are closed
  rather than overwritten, so a historical query resolves the old symbol;
* invalid observations are quarantined with their accession and reason instead of
  being silently dropped or coerced.
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..core.ids import normalize_cik
from ..core.temporal import iso, iso_date, utcnow
from ..entities.master import SecurityMaster
from ..evidence.kernel import EvidenceKernel
from ..ingestion.sec_companyfacts import parse_companyfacts
from ..storage.db import open_database
from ..storage.sources import SEC_EDGAR, SourceRegistry, ensure_default_sources
from .engine import AcquisitionEngine
from .store import Snapshot, sha256_file

SEC_DATASET = "sec.companyfacts"
TICKER_DATASET = "sec.company_tickers"
INTEGRATION_SCHEMA = "atlas.open_data.sec_integration.v1"

EXCHANGE_MICS = {
    "NASDAQ": "XNAS",
    "NASDAQ GLOBAL SELECT MARKET": "XNAS",
    "NASDAQ GLOBAL MARKET": "XNAS",
    "NASDAQ CAPITAL MARKET": "XNAS",
    "NYSE": "XNYS",
    "NEW YORK STOCK EXCHANGE": "XNYS",
    "NYSE AMERICAN": "XASE",
    "NYSE MKT": "XASE",
    "NYSE ARCA": "ARCX",
    "CBOE": "XCBO",
    "CBOE BZX": "XCBO",
    "OTC": "OTCM",
    "OTCQX": "OTCM",
    "OTCQB": "OTCM",
}


@dataclass(slots=True)
class IntegrationCounts:
    companies_this_run: int = 0
    companies_total: int = 0
    eligible_total: int = 0
    ineligible_total: int = 0
    records_parsed: int = 0
    inserted: int = 0
    duplicates: int = 0
    superseding: int = 0
    supersessions: int = 0
    rejected: int = 0
    securities: int = 0
    ticker_assignments: int = 0
    ticker_changes: int = 0

    def add(self, other: "IntegrationCounts") -> None:
        for name in self.__slots__:  # type: ignore[attr-defined]
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def to_dict(self) -> dict[str, int]:
        return {name: int(getattr(self, name)) for name in self.__slots__}  # type: ignore[attr-defined]


def _snapshot(engine: AcquisitionEngine, dataset_id: str, snapshot_id: str | None) -> Snapshot:
    if snapshot_id is None:
        snapshot = engine.store.latest(dataset_id)
        if snapshot is None:
            raise FileNotFoundError(f"no acquired {dataset_id} snapshot is available")
        return snapshot
    for candidate in engine.store.list_snapshots(dataset_id):
        if candidate.snapshot_id == snapshot_id:
            return candidate
    raise FileNotFoundError(f"snapshot {snapshot_id} not found for {dataset_id}")


def _archive_member(snapshot: Snapshot, suffix: str) -> Path:
    for entry in snapshot.files:
        if entry["name"].endswith(suffix):
            return snapshot.path / "files" / entry["path"]
    raise FileNotFoundError(f"{snapshot.dataset_id} snapshot has no member ending {suffix!r}")


def _checkpoint_path(engine: AcquisitionEngine, snapshot: Snapshot, directory: str | Path | None) -> Path:
    root = Path(directory) if directory else engine.store.checkpoint_root
    root.mkdir(parents=True, exist_ok=True)
    return root / f"integration.sec.companyfacts.{snapshot.snapshot_id}.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False,
                                    default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_ticker_map(engine: AcquisitionEngine) -> tuple[dict[str, dict[str, str]], str | None]:
    """Map ``CIK`` to the SEC's current ticker and exchange, when the dataset exists."""
    snapshot = engine.store.latest(TICKER_DATASET)
    if snapshot is None:
        return {}, None
    entry = next((f for f in snapshot.files if f["name"].endswith(".json")), None)
    if entry is None:
        return {}, snapshot.snapshot_id
    try:
        payload = json.loads((snapshot.path / "files" / entry["path"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, snapshot.snapshot_id
    fields = payload.get("fields") or []
    rows = payload.get("data") or []
    try:
        cik_at = fields.index("cik")
        ticker_at = fields.index("ticker")
        exchange_at = fields.index("exchange")
        name_at = fields.index("name") if "name" in fields else None
    except ValueError:
        return {}, snapshot.snapshot_id
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) <= max(cik_at, ticker_at):
            continue
        cik = normalize_cik(str(row[cik_at]))
        ticker = str(row[ticker_at] or "").strip().upper()
        if not cik or not ticker:
            continue
        mapping[cik] = {
            "ticker": ticker,
            "exchange": str(row[exchange_at] or "") if exchange_at < len(row) else "",
            "name": str(row[name_at] or "") if name_at is not None and name_at < len(row) else "",
        }
    return mapping, snapshot.snapshot_id


def integrate_tickers(
    engine: AcquisitionEngine,
    atlas_db: str | Path,
    *,
    effective_date: str | None = None,
) -> dict[str, Any]:
    """Record SEC ticker identity without destroying prior assignments."""
    mapping, snapshot_id = _load_ticker_map(engine)
    if not mapping:
        return {"status": "skipped", "reason": "no acquired sec.company_tickers snapshot",
                "assignments": 0, "changes": 0}
    moment = iso_date(effective_date) if effective_date else iso_date(utcnow())
    db = open_database(atlas_db)
    try:
        ensure_default_sources(db)
        SourceRegistry(db).ensure(SEC_EDGAR)
        master = SecurityMaster(db)
        assignments = 0
        changes = 0
        missing_issuers = 0
        for cik, item in sorted(mapping.items()):
            issuer = master.issuer_by_cik(cik)
            if issuer is None:
                missing_issuers += 1
                continue
            security_id = master.ensure_security(issuer["issuer_id"], source_id=SEC_EDGAR.source_id,
                                                 note="SEC company_tickers exchange mapping")
            exchange = item["exchange"].strip().upper()
            mic = EXCHANGE_MICS.get(exchange)
            if mic is None:
                if not exchange:
                    continue
                mic = "OTCM"
            master.ensure_venue(mic, exchange.title() or mic, country="US")
            listing_id = master.ensure_listing(security_id, mic, valid_from=moment,
                                               currency="USD", is_primary=True,
                                               source_id=SEC_EDGAR.source_id)
            current = master.current_ticker(security_id, as_of=moment)
            if current and str(current["ticker"]).upper() != item["ticker"]:
                master.record_ticker_change(
                    security_id, item["ticker"], moment, source_id=SEC_EDGAR.source_id,
                    note=f"SEC company_tickers mapping changed from {current['ticker']}",
                )
                changes += 1
            else:
                master.assign_ticker(listing_id, item["ticker"], valid_from=moment,
                                     confidence=1.0, source_id=SEC_EDGAR.source_id,
                                     evidence_note="SEC current ticker mapping; earlier assignments are not evidenced")
            assignments += 1
        return {
            "status": "integrated",
            "snapshot_id": snapshot_id,
            "effective_date": moment,
            "tickers_in_source": len(mapping),
            "assignments": assignments,
            "changes": changes,
            "issuers_not_yet_integrated": missing_issuers,
        }
    finally:
        db.close()


def integrate_sic_from_fsds(
    engine: AcquisitionEngine,
    atlas_db: str | Path,
) -> dict[str, Any]:
    """Populate issuer SIC and fiscal-year-end from the latest FSDS ``sub.txt``.

    Companyfacts carries no industry code, and without it a bank is indistinguishable
    from an industrial company, so the valuation core would apply an invalid DCF. The
    FSDS submission table is the authoritative source already in the store.
    """
    import csv

    snapshot = engine.store.latest("sec.financial_statement_data_sets")
    if snapshot is None:
        return {"status": "skipped", "reason": "no acquired FSDS snapshot"}
    archives = sorted(
        (entry for entry in snapshot.files if entry["name"].endswith(".zip")),
        key=lambda entry: entry["name"],
    )
    if not archives:
        return {"status": "skipped", "reason": "FSDS snapshot has no zip files"}
    db = open_database(atlas_db)
    try:
        updated = 0
        unchanged = 0
        absent = 0
        seen = 0
        latest_file = archives[-1]
        with zipfile.ZipFile(snapshot.path / "files" / latest_file["path"]) as zf:
            member = next((name for name in zf.namelist() if name.lower().endswith("sub.txt")), None)
            if member is None:
                return {"status": "skipped", "reason": "FSDS archive has no sub.txt"}
            with zf.open(member) as raw:
                import io
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"),
                                        delimiter="\t")
                for row in reader:
                    cik = row.get("cik")
                    sic = (row.get("sic") or "").strip()
                    if not cik or not sic:
                        continue
                    cik = normalize_cik(str(cik))
                    seen += 1
                    issuer = db.query_one("SELECT issuer_id, sic FROM issuer WHERE cik=?", (cik,))
                    if issuer is None:
                        absent += 1
                        continue
                    fye = (row.get("fye") or "").strip() or None
                    if str(issuer["sic"] or "") == sic and not fye:
                        unchanged += 1
                        continue
                    db.execute(
                        "UPDATE issuer SET sic=?, fiscal_year_end=COALESCE(?, fiscal_year_end), "
                        "updated_at=? WHERE issuer_id=?",
                        (sic, fye, iso(utcnow()), issuer["issuer_id"]),
                    )
                    updated += 1
        return {
            "status": "integrated",
            "snapshot_id": snapshot.snapshot_id,
            "source_file": latest_file["name"],
            "rows_seen": seen,
            "updated": updated,
            "unchanged": unchanged,
            "cik_not_integrated": absent,
        }
    finally:
        db.close()


def integrate_sec_metadata(engine: AcquisitionEngine, atlas_db: str | Path) -> dict[str, Any]:
    return {
        "tickers": integrate_tickers(engine, atlas_db),
        "sic": integrate_sic_from_fsds(engine, atlas_db),
    }


def _quarantine_writer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")

    def write(record: Mapping[str, Any]) -> None:
        handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")

    return handle, write


PROGRESS_SCHEMA = "atlas.open_data.integration_progress.v1"


# -------------------------------------------------------- destination-database truth
def _empty_counts() -> IntegrationCounts:
    return IntegrationCounts()


def _counts_from(payload: Mapping[str, Any] | None) -> IntegrationCounts:
    return IntegrationCounts(**{
        name: int((payload or {}).get(name, 0)) for name in IntegrationCounts.__slots__  # type: ignore[attr-defined]
    })


def _read_progress(db, snapshot: Snapshot) -> dict[str, Any] | None:
    """Read the authoritative progress rows stored inside the destination database."""
    row = db.query_one(
        "SELECT * FROM open_data_integration WHERE dataset_id=? AND snapshot_id=?",
        (SEC_DATASET, snapshot.snapshot_id),
    )
    if row is None:
        return None
    members = db.query(
        "SELECT cik, status, evidence_rows FROM open_data_integration_member "
        "WHERE dataset_id=? AND snapshot_id=?",
        (SEC_DATASET, snapshot.snapshot_id),
    )
    try:
        counts = json.loads(row["counts_json"] or "{}")
    except json.JSONDecodeError:
        counts = {}
    return {
        "database_uuid": str(row["database_uuid"]),
        "integration_schema": str(row["integration_schema"]),
        "manifest_sha256": str(row["manifest_sha256"]),
        "archive_sha256": str(row["archive_sha256"]),
        "status": str(row["status"]),
        "started_at": str(row["started_at"]),
        "counts": counts,
        "processed": {str(item["cik"]) for item in members},
        "integrated": {str(item["cik"]) for item in members if item["status"] == "integrated"},
        "ineligible": {str(item["cik"]) for item in members
                       if item["status"] in ("ineligible", "rejected")},
        "rejected": {str(item["cik"]) for item in members if item["status"] == "rejected"},
        "evidence_rows": {str(item["cik"]): int(item["evidence_rows"] or 0) for item in members},
    }


def _evidence_by_cik(db, snapshot: Snapshot) -> dict[str, int]:
    """Evidence rows in this database attributable to this exact archive snapshot.

    The snapshot id is embedded in every ``source_url`` the bridge writes, so this
    answers "is the evidence the checkpoint claims actually here?" without trusting
    the checkpoint.
    """
    rows = db.query(
        "SELECT i.cik AS cik, COUNT(e.evidence_id) AS rows FROM evidence e "
        "JOIN issuer i ON i.issuer_id = e.entity_id "
        "WHERE e.source_url LIKE ? GROUP BY i.cik",
        (f"%snapshot={snapshot.snapshot_id}%",),
    )
    return {str(row["cik"]): int(row["rows"] or 0) for row in rows}


def _write_member(db, snapshot: Snapshot, cik: str, status: str,
                  evidence_rows: int, member: str | None) -> None:
    db.execute(
        "INSERT INTO open_data_integration_member "
        "(dataset_id, snapshot_id, cik, status, evidence_rows, member, updated_at) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(dataset_id, snapshot_id, cik) DO UPDATE SET "
        "status=excluded.status, evidence_rows=excluded.evidence_rows, "
        "member=excluded.member, updated_at=excluded.updated_at",
        (SEC_DATASET, snapshot.snapshot_id, cik, status, int(evidence_rows), member,
         iso(utcnow())),
    )


def _write_run(db, snapshot: Snapshot, database_uuid: str, archive_sha: str,
               counts: IntegrationCounts, processed: set[str], integrated: set[str],
               ineligible: set[str], rejected: set[str], *, status: str,
               started_at: str, finished: bool = False) -> None:
    stamp = iso(utcnow())
    db.execute(
        "INSERT INTO open_data_integration "
        "(dataset_id, snapshot_id, database_uuid, integration_schema, manifest_sha256, "
        "archive_sha256, status, processed_ciks, integrated_ciks, ineligible_ciks, "
        "rejected_ciks, counts_json, started_at, updated_at, finished_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(dataset_id, snapshot_id) DO UPDATE SET "
        "database_uuid=excluded.database_uuid, integration_schema=excluded.integration_schema, "
        "manifest_sha256=excluded.manifest_sha256, archive_sha256=excluded.archive_sha256, "
        "status=excluded.status, processed_ciks=excluded.processed_ciks, "
        "integrated_ciks=excluded.integrated_ciks, ineligible_ciks=excluded.ineligible_ciks, "
        "rejected_ciks=excluded.rejected_ciks, counts_json=excluded.counts_json, "
        "updated_at=excluded.updated_at, finished_at=excluded.finished_at",
        (
            SEC_DATASET, snapshot.snapshot_id, database_uuid, INTEGRATION_SCHEMA,
            snapshot.manifest_sha256, archive_sha, status, len(processed), len(integrated),
            len(ineligible), len(rejected), json.dumps(counts.to_dict(), sort_keys=True),
            started_at, stamp, stamp if finished else None,
        ),
    )


def _clear_progress(db, snapshot: Snapshot) -> None:
    db.execute("DELETE FROM open_data_integration_member WHERE dataset_id=? AND snapshot_id=?",
               (SEC_DATASET, snapshot.snapshot_id))
    db.execute("DELETE FROM open_data_integration WHERE dataset_id=? AND snapshot_id=?",
               (SEC_DATASET, snapshot.snapshot_id))


def _reconcile_progress(
    db,
    snapshot: Snapshot,
    *,
    database_uuid: str,
    archive_sha: str,
    external: Mapping[str, Any],
    restart: bool,
    verify_evidence: bool,
) -> dict[str, Any]:
    """Decide what may be resumed, using the destination database as the authority.

    Four failure modes are detected here:

    * the database was deleted and recreated (new UUID, no progress rows);
    * it was replaced by a different database (foreign UUID / no rows for this
      archive);
    * it was rolled back to a copy older than the external checkpoint (the database
      is behind, so the missing issuers are re-parsed rather than skipped);
    * a checkpoint claims issuers whose evidence is not present (they are re-parsed).

    In every case the recovery is the same: trust only what the database can prove.
    """
    events: list[dict[str, Any]] = []
    if restart:
        with db.transaction():
            _clear_progress(db, snapshot)
        events.append({"kind": "restart_requested",
                       "detail": "existing progress rows for this snapshot were cleared"})
        progress = None
    else:
        progress = _read_progress(db, snapshot)

    if progress is not None:
        if progress["database_uuid"] != database_uuid:
            events.append({"kind": "foreign_database_progress",
                           "recorded_for": progress["database_uuid"],
                           "database": database_uuid})
            progress = None
        elif progress["integration_schema"] != INTEGRATION_SCHEMA:
            events.append({"kind": "progress_schema_changed",
                           "recorded": progress["integration_schema"],
                           "current": INTEGRATION_SCHEMA})
            progress = None
        elif progress["manifest_sha256"] != snapshot.manifest_sha256:
            raise ValueError(
                "the destination database holds integration progress for a different "
                f"snapshot manifest ({progress['manifest_sha256']} != {snapshot.manifest_sha256}); "
                "use --restart to discard it"
            )
        elif progress["archive_sha256"] != archive_sha:
            raise ValueError(
                "the destination database holds integration progress for archive bytes "
                f"{progress['archive_sha256']} but the stored archive hashes to {archive_sha}; "
                "use --restart to discard the old progress"
            )

    if progress is None:
        # A database with no progress rows for this snapshot is either new, recreated
        # or replaced. Nothing in the external checkpoint can be trusted for it.
        if external and external.get("processed_ciks"):
            events.append({
                "kind": "checkpoint_not_used",
                "reason": "destination database has no matching progress",
                "checkpoint_database_uuid": external.get("database_uuid"),
                "database_uuid": database_uuid,
                "checkpoint_processed": len(external.get("processed_ciks") or []),
            })
        processed: set[str] = set()
        integrated: set[str] = set()
        ineligible: set[str] = set()
        rejected: set[str] = set()
        counts = _empty_counts()
        started_at = iso(utcnow())
        evidence_rows: dict[str, int] = {}
    else:
        processed = set(progress["processed"])
        integrated = set(progress["integrated"])
        ineligible = set(progress["ineligible"])
        rejected = set(progress["rejected"])
        counts = _counts_from(progress["counts"])
        started_at = progress["started_at"]
        evidence_rows = dict(progress["evidence_rows"])
        if external:
            if external.get("database_uuid") not in (None, database_uuid):
                events.append({"kind": "checkpoint_database_mismatch",
                               "checkpoint": external.get("database_uuid"),
                               "database": database_uuid})
            if external.get("manifest_sha256") not in (None, snapshot.manifest_sha256) \
                    or external.get("archive_sha256") not in (None, archive_sha):
                raise ValueError(
                    "the integration checkpoint describes different archive bytes; "
                    "use --restart to start a new checkpoint instead of mixing archives"
                )
            checkpoint_processed = {str(cik) for cik in external.get("processed_ciks") or []}
            checkpoint_integrated = {str(cik) for cik in external.get("integrated_ciks") or []}
            unrecorded = checkpoint_processed - processed
            if unrecorded:
                events.append({
                    "kind": "checkpoint_ahead_of_database",
                    "detail": "the database was rolled back or restored from an older copy; "
                              "claimed issuers are re-parsed",
                    "count": len(unrecorded),
                    "sample": sorted(unrecorded)[:10],
                })
            claimed_without_rows = checkpoint_integrated - integrated
            if claimed_without_rows:
                events.append({
                    "kind": "checkpoint_claims_unrecorded_members",
                    "count": len(claimed_without_rows),
                    "sample": sorted(claimed_without_rows)[:10],
                })

    if verify_evidence and integrated:
        actual = _evidence_by_cik(db, snapshot)
        absent = sorted(cik for cik in integrated if actual.get(cik, 0) == 0)
        if absent:
            # A checkpoint (or a progress row) that claims an issuer whose evidence is
            # gone is wrong. Re-parse those issuers instead of skipping them.
            events.append({
                "kind": "claims_absent_evidence",
                "count": len(absent),
                "sample": absent[:10],
                "action": "re-parse",
            })
            with db.transaction():
                for cik in absent:
                    processed.discard(cik)
                    integrated.discard(cik)
                    ineligible.discard(cik)
                    rejected.discard(cik)
                    evidence_rows.pop(cik, None)
                    db.execute(
                        "DELETE FROM open_data_integration_member "
                        "WHERE dataset_id=? AND snapshot_id=? AND cik=?",
                        (SEC_DATASET, snapshot.snapshot_id, cik),
                    )
        evidence_rows = {cik: actual.get(cik, 0) for cik in integrated}

    return {
        "database_uuid": database_uuid,
        "processed": processed,
        "integrated": integrated,
        "ineligible": ineligible,
        "rejected": rejected,
        "counts": counts,
        "started_at": started_at,
        "events": events,
        "authority": "destination_database",
        "resumed": progress is not None,
    }


def integration_progress(atlas_db: str | Path, *, snapshot_id: str) -> dict[str, Any]:
    """Public read of the progress recorded inside a destination database."""
    db = open_database(atlas_db, migrate=False)
    try:
        database_uuid = db.identity_uuid()
        rows = db.query(
            "SELECT * FROM open_data_integration WHERE snapshot_id=?", (snapshot_id,))
        members = db.query(
            "SELECT status, COUNT(*) AS n FROM open_data_integration_member "
            "WHERE snapshot_id=? GROUP BY status", (snapshot_id,))
        return {
            "database_uuid": database_uuid,
            "snapshot_id": snapshot_id,
            "runs": [dict(row) for row in rows],
            "members": {str(row["status"]): int(row["n"]) for row in members},
        }
    finally:
        db.close()


def integrate_companyfacts(
    engine: AcquisitionEngine,
    atlas_db: str | Path,
    *,
    snapshot_id: str | None = None,
    ciks: Iterable[str] | None = None,
    limit: int | None = 100,
    batch_size: int = 500,
    checkpoint_dir: str | Path | None = None,
    restart: bool = False,
    max_seconds: float | None = None,
    continue_on_error: bool = True,
    tickers: bool = True,
    verify_progress: bool = True,
) -> dict[str, Any]:
    """Integrate company facts from the full archive, resumably and safely.

    ``limit`` is the target number of *cumulative* issuers recorded in the destination
    database, not a per-run sample. Passing ``limit=100`` twice does not parse two
    different hundreds: the second run continues after the first. ``limit=None``
    integrates every eligible issuer and is safe to interrupt at any point.

    Progress is written inside the same transaction as the evidence it describes, so
    the database is the authority. The JSON file beside the store checkpoint is a
    mirror for operators; when it disagrees with the database, the database wins and
    the disagreement is reported in ``progress.events``.
    """
    started = time.monotonic()
    snapshot = _snapshot(engine, SEC_DATASET, snapshot_id)
    archive = _archive_member(snapshot, "companyfacts.zip")
    archive_sha = sha256_file(archive)
    manifest_sha = snapshot.manifest_sha256
    checkpoint = _checkpoint_path(engine, snapshot, checkpoint_dir)
    external: dict[str, Any] = {}
    if checkpoint.exists() and not restart:
        try:
            external = json.loads(checkpoint.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            external = {}
        if external.get("manifest_sha256") not in (None, manifest_sha):
            raise ValueError(
                "integration checkpoint belongs to a different snapshot manifest; "
                "use --restart to start a new checkpoint instead of mixing archives"
            )
    wanted = {normalize_cik(str(cik)) for cik in ciks} if ciks else None
    run_counts = IntegrationCounts()
    target = None if limit is None or limit <= 0 else int(limit)
    quarantine_path = checkpoint.parent / f"quarantine.sec.companyfacts.{snapshot.snapshot_id}.jsonl"
    handle, write_quarantine = _quarantine_writer(quarantine_path)
    stopped_reason = "complete"
    ticker_result: dict[str, Any] = {}

    db = open_database(atlas_db)
    try:
        ensure_default_sources(db)
        SourceRegistry(db).ensure(SEC_EDGAR)
        database_uuid = db.ensure_identity()
        resolved = _reconcile_progress(
            db, snapshot, database_uuid=database_uuid, archive_sha=archive_sha,
            external=external, restart=restart, verify_evidence=verify_progress,
        )
        processed: set[str] = resolved["processed"]
        integrated: set[str] = resolved["integrated"]
        ineligible: set[str] = resolved["ineligible"]
        rejected: set[str] = resolved["rejected"]
        counts: IntegrationCounts = resolved["counts"]
        run_started_at: str = resolved["started_at"]
        state: dict[str, Any] = {
            "schema": INTEGRATION_SCHEMA,
            "dataset_id": SEC_DATASET,
            "snapshot_id": snapshot.snapshot_id,
            "manifest_sha256": manifest_sha,
            "archive_sha256": archive_sha,
            "database_uuid": database_uuid,
            "started_at": run_started_at,
        }
        resumed_from = len(processed)
        with db.transaction():
            _write_run(db, snapshot, database_uuid, archive_sha, counts, processed,
                       integrated, ineligible, rejected, status="running",
                       started_at=run_started_at)
        master = SecurityMaster(db)
        kernel = EvidenceKernel(db)
        with zipfile.ZipFile(archive) as zf:
            names = sorted(name for name in zf.namelist() if name.endswith(".json"))
            for position, name in enumerate(names, start=1):
                if target is not None and len(processed) >= target:
                    stopped_reason = "target_reached"
                    break
                if max_seconds is not None and time.monotonic() - started >= max_seconds:
                    stopped_reason = "time_budget"
                    break
                try:
                    raw = zf.read(name)
                    payload = json.loads(raw)
                except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    write_quarantine({"member": name, "stage": "parse", "error": str(exc),
                                      "snapshot_id": snapshot.snapshot_id})
                    run_counts.rejected += 1
                    with db.transaction():
                        _write_run(db, snapshot, database_uuid, archive_sha,
                                   _merge(state, counts, run_counts), processed, integrated,
                                   ineligible, rejected, status="running",
                                   started_at=run_started_at)
                    continue
                cik_value = payload.get("cik")
                if cik_value is None:
                    write_quarantine({"member": name, "stage": "identity", "error": "no cik",
                                      "snapshot_id": snapshot.snapshot_id})
                    run_counts.rejected += 1
                    with db.transaction():
                        _write_run(db, snapshot, database_uuid, archive_sha,
                                   _merge(state, counts, run_counts), processed, integrated,
                                   ineligible, rejected, status="running",
                                   started_at=run_started_at)
                    continue
                cik = normalize_cik(str(cik_value))
                if wanted is not None and cik not in wanted:
                    continue
                if cik in processed:
                    continue
                legal_name = payload.get("entityName") or f"CIK {cik}"
                issuer_id = master.register_issuer(
                    legal_name=str(legal_name), cik=cik, source_id=SEC_EDGAR.source_id,
                )
                try:
                    parsed = parse_companyfacts(
                        payload,
                        issuer_id=issuer_id,
                        source_id=SEC_EDGAR.source_id,
                        source_url=(
                            f"https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
                            f"#member={name}&cik={cik}&zip_sha256={archive_sha}"
                            f"&snapshot={snapshot.snapshot_id}"
                        ),
                        observed_at=(snapshot.manifest.get("retrieval") or {}).get("completed_at"),
                    )
                except Exception as exc:  # noqa: BLE001 - one malformed issuer is quarantined
                    write_quarantine({"member": name, "cik": cik, "stage": "normaliser",
                                      "error": f"{type(exc).__name__}: {exc}",
                                      "snapshot_id": snapshot.snapshot_id})
                    with db.transaction():
                        processed.add(cik)
                        ineligible.add(cik)
                        rejected.add(cik)
                        run_counts.companies_this_run += 1
                        run_counts.rejected += 1
                        _write_member(db, snapshot, cik, "rejected", 0, name)
                        _write_run(db, snapshot, database_uuid, archive_sha,
                                   _merge(state, counts, run_counts), processed, integrated,
                                   ineligible, rejected, status="running",
                                   started_at=run_started_at)
                    continue
                if parsed.records:
                    # Evidence, the per-issuer progress row and the run totals commit
                    # together: there is no window where one exists without the other.
                    with db.transaction():
                        summary = kernel.ingest_many(
                            parsed.records, continue_on_error=continue_on_error,
                            batch_size=batch_size,
                        )
                        run_counts.records_parsed += len(parsed.records)
                        run_counts.inserted += summary.inserted
                        run_counts.duplicates += summary.duplicates
                        run_counts.superseding += summary.superseding
                        run_counts.supersessions += summary.supersessions
                        run_counts.rejected += summary.rejected
                        run_counts.companies_this_run += 1
                        processed.add(cik)
                        if summary.inserted + summary.superseding > 0 or summary.duplicates > 0:
                            integrated.add(cik)
                            ineligible.discard(cik)
                            rejected.discard(cik)
                            stored = int(db.scalar(
                                "SELECT COUNT(*) FROM evidence e JOIN issuer i "
                                "ON i.issuer_id=e.entity_id WHERE i.cik=? AND e.source_url LIKE ?",
                                (cik, f"%snapshot={snapshot.snapshot_id}%"), default=0) or 0)
                            _write_member(db, snapshot, cik, "integrated", stored, name)
                        else:
                            ineligible.add(cik)
                            _write_member(db, snapshot, cik, "ineligible", 0, name)
                        _write_run(db, snapshot, database_uuid, archive_sha,
                                   _merge(state, counts, run_counts), processed, integrated,
                                   ineligible, rejected, status="running",
                                   started_at=run_started_at)
                    for rejection in summary.rejections[:200]:
                        write_quarantine({
                            "member": name, "cik": cik, "stage": "evidence",
                            "accession_number": rejection.get("accession_number"),
                            "concept": rejection.get("concept"),
                            "evidence_id": rejection.get("evidence_id"),
                            "error": rejection.get("error"),
                            "snapshot_id": snapshot.snapshot_id,
                        })
                    for issue in parsed.issues[:50]:
                        write_quarantine({"member": name, "cik": cik, "stage": "normaliser",
                                          **dict(issue), "snapshot_id": snapshot.snapshot_id})
                else:
                    with db.transaction():
                        run_counts.companies_this_run += 1
                        processed.add(cik)
                        ineligible.add(cik)
                        _write_member(db, snapshot, cik, "ineligible", 0, name)
                        _write_run(db, snapshot, database_uuid, archive_sha,
                                   _merge(state, counts, run_counts), processed, integrated,
                                   ineligible, rejected, status="running",
                                   started_at=run_started_at)
                if run_counts.companies_this_run % 10 == 0:
                    _save_state(checkpoint, state, processed, integrated, ineligible,
                                _merge(state, counts, run_counts), snapshot, archive_sha,
                                database_uuid=database_uuid)
        if tickers:
            ticker_result = integrate_sec_metadata(engine, atlas_db)
            run_counts.ticker_assignments += int((ticker_result.get("tickers") or {}).get("assignments") or 0)
            run_counts.ticker_changes += int((ticker_result.get("tickers") or {}).get("changes") or 0)
        final = _merge(state, counts, run_counts)
        final.companies_total = len(processed)
        final.eligible_total = len(integrated)
        final.ineligible_total = len(ineligible)
        with db.transaction():
            _write_run(db, snapshot, database_uuid, archive_sha, final, processed, integrated,
                       ineligible, rejected, status=stopped_reason,
                       started_at=run_started_at, finished=True)
        _save_state(checkpoint, state, processed, integrated, ineligible, final, snapshot,
                    archive_sha, database_uuid=database_uuid)
        engine.index.record_integration(
            SEC_DATASET, snapshot.snapshot_id, target=str(atlas_db),
            records=final.records_parsed, entities=len(integrated),
        )
        return {
            "schema": INTEGRATION_SCHEMA,
            "dataset": SEC_DATASET,
            "snapshot_id": snapshot.snapshot_id,
            "manifest_sha256": manifest_sha,
            "archive_sha256": archive_sha,
            "atlas_db": str(atlas_db),
            "database_uuid": database_uuid,
            "progress": {
                "schema": PROGRESS_SCHEMA,
                "authority": resolved["authority"],
                "resumed": resolved["resumed"],
                "events": resolved["events"],
                "rows": len(processed),
            },
            "checkpoint": str(checkpoint),
            "quarantine": str(quarantine_path),
            "resumed_from": resumed_from,
            "target": target,
            "stopped_reason": stopped_reason,
            "companies_this_run": run_counts.companies_this_run,
            "companies_total": len(processed),
            "eligible_total": len(integrated),
            "ineligible_total": len(ineligible),
            "records_parsed_this_run": run_counts.records_parsed,
            "records_parsed_total": final.records_parsed,
            "evidence_inserted_total": final.inserted + final.superseding,
            "evidence_duplicates_total": final.duplicates,
            "evidence_rejected_total": final.rejected,
            "supersessions_total": final.supersessions,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "tickers": ticker_result,
            "counts": final.to_dict(),
        }
    finally:
        handle.close()
        db.close()


def _merge(state: Mapping[str, Any], base: IntegrationCounts,
           run: IntegrationCounts) -> IntegrationCounts:
    merged = IntegrationCounts(**{name: int(getattr(base, name)) for name in IntegrationCounts.__slots__})  # type: ignore[attr-defined]
    merged.add(run)
    return merged


def _save_state(path: Path, state: Mapping[str, Any], processed: set[str],
                integrated: set[str], ineligible: set[str], counts: IntegrationCounts,
                snapshot: Snapshot, archive_sha: str, *, database_uuid: str) -> None:
    """Write the operator mirror. It is never read as the authority."""
    payload = dict(state)
    payload.update({
        "schema": INTEGRATION_SCHEMA,
        "dataset_id": SEC_DATASET,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "archive_sha256": archive_sha,
        "database_uuid": database_uuid,
        "processed_ciks": sorted(processed),
        "integrated_ciks": sorted(integrated),
        "ineligible_ciks": sorted(ineligible),
        "counts": counts.to_dict(),
        "updated_at": iso(utcnow()),
        "authority": "destination_database",
    })
    _atomic_json(path, payload)


def ticker_history(atlas_db: str | Path, cik: str) -> list[dict[str, Any]]:
    """Every recorded ticker interval for an issuer, oldest first."""
    db = open_database(atlas_db)
    try:
        master = SecurityMaster(db)
        issuer = master.issuer_by_cik(cik)
        if issuer is None:
            return []
        rows: list[dict[str, Any]] = []
        for security in master.securities_for_issuer(issuer["issuer_id"]):
            for listing in master.listings(security["security_id"]):
                for row in db.query(
                    "SELECT ticker, valid_from, valid_to, status, confidence, evidence_note "
                    "FROM ticker_assignment WHERE listing_id=? ORDER BY valid_from",
                    (listing["listing_id"],),
                ):
                    rows.append({**dict(row), "mic": listing["mic"],
                                 "security_id": security["security_id"]})
        return sorted(rows, key=lambda item: (item["valid_from"], item["ticker"]))
    finally:
        db.close()


def observation_rows(engine: AcquisitionEngine, dataset_id: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Public API used by research code: point-in-time observation query."""
    return engine.index.observations(dataset_id, **kwargs)
