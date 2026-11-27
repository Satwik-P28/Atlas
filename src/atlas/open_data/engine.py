"""Acquisition engine: download, validate, snapshot, index.

The engine never publishes a snapshot that failed structural validation, never
overwrites an existing snapshot, and never re-downloads a bulk archive whose provider
validator (ETag / Last-Modified / length) is unchanged unless ``force`` is set.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from . import adapters, archives
from .index import DEFAULT_INDEX, Observation, OpenDataIndex
from .registry import DEFAULT_REGISTRY, Dataset, Registry, audit_rights
from .rights import assert_allowed, classify, evaluate
from .store import Snapshot, SnapshotStore, StoreError, utcnow
from .transport import HttpTransport, RateLimit, TransportConfig, TransportError

DEFAULT_STORE = "var/open_data"
HARD_FAILURE_CODES = {
    "adapter_failure", "corrupt_archive", "path_traversal", "empty_snapshot",
    "bad_json_root", "size_mismatch", "unexpected_format",
}


class AcquisitionBlocked(RuntimeError):
    pass


@dataclass(slots=True)
class AcquisitionResult:
    dataset_id: str
    status: str
    snapshot_id: str | None
    run_id: str
    stats: dict[str, Any]
    manifest_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "status": self.status,
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "stats": self.stats,
            "manifest_path": self.manifest_path,
            "error": self.error,
        }


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _validate_json(path: Path) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _validate_tabular(path: Path, delimiter: str) -> int:
    import csv
    csv.field_size_limit(64 * 1024 * 1024)
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        header = next(reader, [])
        first = next(reader, [])
    if len(header) < 2 or not first:
        raise ValueError("expected at least two columns and one data row")
    return len(header)


class AcquisitionEngine:
    def __init__(
        self,
        *,
        registry: Registry | None = None,
        store: SnapshotStore | None = None,
        index: OpenDataIndex | None = None,
        transport: HttpTransport | None = None,
        store_root: str | Path = DEFAULT_STORE,
        index_path: str | Path = DEFAULT_INDEX,
        registry_path: str | Path = DEFAULT_REGISTRY,
    ) -> None:
        self.registry = registry or Registry.load(registry_path)
        self.store = store or SnapshotStore(store_root)
        self.index = index or OpenDataIndex(index_path)
        self.transport = transport or HttpTransport(TransportConfig())
        for entry in self.registry:
            self.index.register(entry.raw)
        self.index.record_rights_audit(audit_rights(self.registry.payload))

    def close(self) -> None:
        self.index.close()

    def __enter__(self) -> "AcquisitionEngine":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ helpers
    def _check(self, dataset: Dataset, *, automated: bool, public_distribution: bool) -> None:
        decision = assert_allowed(dataset.raw, "acquire", automated=automated,
                                  public_distribution=public_distribution)
        if dataset.download_endpoint is None:
            raise AcquisitionBlocked(f"{dataset.id}: no automated download endpoint; ingestion is manual")
        if dataset["auth_required"]:
            raise AcquisitionBlocked(f"{dataset.id}: provider requires authentication; set the documented key")

    def _unchanged(self, dataset: Dataset, checkpoint: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
        endpoint = dataset.download_endpoint
        if not endpoint or not checkpoint.get("etag") and not checkpoint.get("last_modified"):
            return False, {}
        try:
            head = self.transport.head(endpoint)
        except Exception:
            return False, {}
        if head.get("status") != 200:
            return False, head
        same_etag = head.get("etag") and checkpoint.get("etag") and head["etag"] == checkpoint["etag"]
        same_modified = (head.get("last_modified") and checkpoint.get("last_modified")
                         and head["last_modified"] == checkpoint["last_modified"])
        same_length = (head.get("content_length") and checkpoint.get("content_length")
                       and head["content_length"] == checkpoint["content_length"])
        return bool(same_etag or (same_modified and same_length)), head

    def _disk_guard(self, dataset: Dataset, expected: int | None) -> None:
        required = (expected or 0) * 2 + 512 * 1024**2
        free = _free_bytes(self.store.root)
        if expected and free < required:
            raise AcquisitionBlocked(
                f"{dataset.id}: needs about {required / 1e9:.1f} GB free under {self.store.root}; "
                f"{free / 1e9:.1f} GB available"
            )

    def _bulk_download(self, dataset: Dataset, staging: Path, *, max_bytes: int | None) -> tuple[dict[str, Any], Path]:
        cfg = dict(dataset.get("acquisition") or {})
        filename = cfg.get("filename") or f"{dataset.id.replace('.', '_')}.bin"
        raw_dir = staging / "raw"
        raw_dir.mkdir()
        destination = raw_dir / filename
        result = self.transport.download(dataset.download_endpoint, destination, max_bytes=max_bytes, resume=True)
        if result.not_modified:
            return result.to_dict(), destination
        return result.to_dict(), destination

    def _series_download(self, dataset: Dataset, staging: Path, *, max_bytes: int | None) -> tuple[dict[str, Any], list[Path]]:
        """Download an enumerated set of archive URLs into one historical snapshot.

        A series is used for providers that publish one archive per quarter or month.
        Optional members that return 404 are recorded as an explicit gap, never as an
        empty quarter: the acquisition then reports ``partial_scope`` rather than
        claiming a complete history.
        """
        cfg = dict(dataset.get("acquisition") or {})
        raw_dir = staging / "raw"
        raw_dir.mkdir()
        urls = list(cfg.get("urls") or [])
        if not urls:
            raise ValueError("url_series acquisition has no urls")
        headers = dict(cfg.get("headers") or {})
        files: list[Path] = []
        total = 0
        skipped: list[dict[str, Any]] = []
        started = time.monotonic()
        for index, item in enumerate(urls):
            url = str(item.get("url") if isinstance(item, Mapping) else item)
            label = str(item.get("name") if isinstance(item, Mapping) else "") or url.rsplit("/", 1)[-1]
            destination = raw_dir / f"{index:04d}-{label}"
            try:
                result = self.transport.download(
                    url, destination,
                    max_bytes=(max_bytes - total) if max_bytes else None,
                    resume=True, headers=headers,
                )
            except TransportError as exc:
                if getattr(exc, "status", None) == 404 or "404" in str(exc):
                    skipped.append({"url": url, "name": label, "reason": "404 not published"})
                    continue
                raise
            total += result.bytes_downloaded
            files.append(destination)
        if not files:
            raise ValueError("every URL in the archive series failed")
        return {
            "status": 206,
            "bytes_downloaded": total,
            "pages": len(files),
            "final_url": dataset.download_endpoint,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "skipped_urls": skipped,
            "requested_urls": len(urls),
        }, files

    def _paged_download(self, dataset: Dataset, staging: Path, *, max_bytes: int | None) -> tuple[dict[str, Any], list[Path]]:
        cfg = dict(dataset.get("acquisition") or {})
        parse = dict(dataset.get("parse") or {})
        kind = cfg.get("kind")
        raw_dir = staging / "raw"
        raw_dir.mkdir()
        files: list[Path] = []
        total = 0
        started = time.monotonic()
        base = dataset.download_endpoint or ""
        headers = dict(cfg.get("headers") or {})
        if kind == "fiscal_api":
            page = 1
            expected_pages: int | None = None
            expected_rows: int | None = None
            seen_rows = 0
            page_size = int(cfg.get("page_size") or 1000)
            while True:
                from urllib.parse import urlencode
                url = base + "?" + urlencode({"sort": cfg.get("sort", "record_date"),
                                              "page[number]": page, "page[size]": page_size})
                destination = raw_dir / f"page-{page:05d}.json"
                result = self.transport.download(url, destination, max_bytes=(max_bytes - total) if max_bytes else None,
                                                 resume=True, headers=headers)
                total += result.bytes_downloaded
                payload = json.loads(destination.read_text(encoding="utf-8"))
                rows = payload.get("data")
                meta = payload.get("meta") or {}
                pages = int(meta.get("total-pages") or 0)
                row_total = int(meta.get("total-count") or 0)
                if expected_pages is None:
                    expected_pages, expected_rows = pages, row_total
                    if not 1 <= expected_pages <= int(cfg.get("max_pages") or 10000):
                        raise ValueError(f"implausible pagination: {expected_pages} pages")
                if pages != expected_pages or row_total != expected_rows or not isinstance(rows, list) or not rows:
                    raise ValueError("inconsistent or empty pagination page")
                seen_rows += len(rows)
                files.append(destination)
                if page == expected_pages:
                    if seen_rows != expected_rows:
                        raise ValueError(f"incomplete pagination: {seen_rows} of {expected_rows} rows")
                    break
                page += 1
                if total > (max_bytes or 10**12):
                    raise ValueError("pagination exceeds byte budget")
        elif kind == "worldbank":
            page = 1
            per_page = int(cfg.get("page_size") or 20000)
            while True:
                sep = "&" if "?" in base else "?"
                url = f"{base}{sep}format=json&per_page={per_page}&page={page}"
                destination = raw_dir / f"page-{page:05d}.json"
                result = self.transport.download(url, destination, max_bytes=(max_bytes - total) if max_bytes else None,
                                                 resume=True, headers=headers)
                total += result.bytes_downloaded
                payload = json.loads(destination.read_text(encoding="utf-8"))
                files.append(destination)
                if not isinstance(payload, list) or len(payload) < 2:
                    raise ValueError("unexpected World Bank response shape")
                meta = payload[0] if isinstance(payload[0], dict) else {}
                if page >= int(meta.get("pages") or 1):
                    break
                page += 1
        elif kind == "json_api":
            offset = int(cfg.get("start") or 0)
            increment = int(cfg.get("increment") or 0)
            page = 1
            limit = int(cfg.get("page_size") or 1000)
            max_pages = int(cfg.get("max_pages") or 100)
            next_url: str | None = None
            while True:
                if next_url:
                    url = next_url
                else:
                    from urllib.parse import urlencode
                    url = base + ("&" if "?" in base else "?") + urlencode({
                        cfg.get("page_param", "offset"): offset,
                        cfg.get("page_size_param", "limit"): limit,
                        **(cfg.get("params") or {}),
                    })
                destination = raw_dir / f"page-{page:05d}.json"
                result = self.transport.download(url, destination, max_bytes=(max_bytes - total) if max_bytes else None,
                                                 resume=True, headers=headers)
                total += result.bytes_downloaded
                payload = json.loads(destination.read_text(encoding="utf-8"))
                files.append(destination)
                data_path = (dataset.get("parse") or {}).get("data_path") or "data"
                data: Any = payload
                for key in data_path.split("."):
                    data = data.get(key) if isinstance(data, Mapping) else None
                if not isinstance(data, list):
                    raise ValueError("unexpected JSON API response shape")
                if not data or page >= max_pages:
                    break
                next_url = None
                links = payload.get("links") if isinstance(payload, Mapping) else None
                if isinstance(links, Mapping) and isinstance(links.get("next"), str):
                    next_url = links["next"]
                    if next_url.startswith("/"):
                        from urllib.parse import urlsplit
                        parts = urlsplit(base)
                        next_url = f"{parts.scheme}://{parts.netloc}{next_url}"
                offset += increment or limit
                page += 1
                if total > (max_bytes or 10**12):
                    raise ValueError("pagination exceeds byte budget")
        else:
            raise ValueError(f"unsupported paged acquisition kind {kind!r}")
        result_dict = {
            "status": 206 if len(files) > 1 else 200,
            "bytes_downloaded": total,
            "pages": len(files),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "final_url": base,
        }
        return result_dict, files

    # ------------------------------------------------------------------ acquire
    def acquire(
        self,
        dataset_id: str,
        *,
        automated: bool = False,
        public_distribution: bool = False,
        force: bool = False,
        max_bytes: int | None = None,
        enqueue_only: bool = False,
    ) -> AcquisitionResult:
        dataset = self.registry.get(dataset_id)
        self._check(dataset, automated=automated, public_distribution=public_distribution)
        if enqueue_only:
            run_id = self.index.start_run(dataset_id, "enqueue")
            self.index.finish_run(run_id, status="blocked", error="enqueue only")
            return AcquisitionResult(dataset_id, "blocked", None, run_id, {}, error="enqueue only")
        cfg = dict(dataset.get("acquisition") or {})
        configured_max = int(cfg.get("max_bytes") or dataset.get("expected_size_bytes") or 0) or None
        byte_budget = min(filter(None, [max_bytes, configured_max])) if (max_bytes or configured_max) else None
        self._disk_guard(dataset, byte_budget)
        checkpoint = self.store.read_checkpoint(dataset_id)
        if not force and cfg.get("conditional", True):
            unchanged, head = self._unchanged(dataset, checkpoint)
            if unchanged and self.store.latest(dataset_id) is not None:
                run_id = self.index.start_run(dataset_id, "current")
                self.index.finish_run(run_id, status="not_modified", http_status=200,
                                      snapshot_id=checkpoint.get("snapshot_id"),
                                      downloaded_bytes=0, elapsed_seconds=0.0,
                                      stats_json={"reason": "provider validator unchanged", "head": head})
                return AcquisitionResult(dataset_id, "not_modified", checkpoint.get("snapshot_id"), run_id,
                                         {"reason": "provider validator unchanged", "head": head})
        run_id = self.index.start_run(dataset_id, "current")
        staging = self.store.new_staging(dataset_id)
        started = time.monotonic()
        try:
            kind = cfg.get("kind", "bulk")
            if kind == "bulk":
                transfer, raw = self._bulk_download(dataset, staging, max_bytes=byte_budget)
                raw_files = [raw]
            elif kind == "url_series":
                transfer, raw_files = self._series_download(dataset, staging, max_bytes=byte_budget)
            else:
                transfer, raw_files = self._paged_download(dataset, staging, max_bytes=byte_budget)
                transfer = dict(transfer)
            validation = self._validate_downloads(dataset, raw_files)
            files = self._register_files(dataset, staging, raw_files)
            snapshot_files = {entry["name"]: staging / "files" / entry["path"] for entry in files}
            analysis = adapters.analyze(dataset, snapshot_files)
            from datetime import date as _date
            if analysis.obs_end and analysis.obs_end > _date.today().isoformat():
                analysis.issues.append({
                    "code": "future_observation_date", "severity": "warning",
                    "detail": (f"provider rows extend to {analysis.obs_end}, beyond today; future-dated "
                               "periods are retained but must not be treated as observed history"),
                })
            if analysis.future_dates:
                analysis.issues.append({
                    "code": "future_observation_dates", "severity": "warning",
                    "detail": (f"{analysis.future_dates} provider rows carry a future period end; "
                               "they remain in the raw snapshot and are excluded from advertised coverage"),
                })
            if analysis.implausible_dates:
                analysis.issues.append({
                    "code": "implausible_observation_dates", "severity": "warning",
                    "detail": (f"{analysis.implausible_dates} provider rows carry dates outside "
                               "1900-01-01..today+2y; they remain in the raw snapshot but are excluded "
                               "from the advertised coverage range"),
                })
            hard_failures = [issue for issue in analysis.issues if issue.get("code") in HARD_FAILURE_CODES
                             or issue.get("severity") == "error" and issue.get("code") == "adapter_failure"]
            if hard_failures:
                raise ValueError("structural validation failed: " + "; ".join(
                    f"{issue['code']}: {issue['detail']}" for issue in hard_failures[:5]))
            derived = self._write_derived(dataset, staging, analysis)
            for entry in derived:
                files.append(entry)
            stats = analysis.to_stats(dataset_id)
            stats["validation"] = validation
            stats["transfer"] = transfer
            if transfer.get("skipped_urls"):
                analysis.extra["skipped_urls"] = transfer["skipped_urls"]
                analysis.extra["partial_scope"] = True
                analysis.issues.append({
                    "code": "archive_series_gap", "severity": "warning",
                    "detail": (f"{len(transfer['skipped_urls'])} of {transfer.get('requested_urls')} "
                               "enumerated archive URLs were not published; the snapshot is partial"),
                })
            rights = classify(dataset["rights_class"])
            redistributable = rights.may_distribute and bool(dataset.get("redistribution"))
            manifest = {
                "dataset_id": dataset_id,
                "provider": dataset["provider"],
                "title": dataset["title"],
                "source": {
                    "official_source_url": dataset["official_source_url"],
                    "download_endpoint": dataset["download_endpoint"],
                    "final_url": transfer.get("final_url"),
                    "etag": transfer.get("etag"),
                    "last_modified": transfer.get("last_modified"),
                    "content_type": transfer.get("content_type"),
                },
                "retrieval": {
                    "started_at": checkpoint.get("last_attempt") or utcnow(),
                    "completed_at": utcnow(),
                    "retrieved_by": "atlas.open_data.engine",
                },
                "rights": {
                    "rights_class": rights.value,
                    "license_name": dataset["license_name"],
                    "license_url": dataset.get("license_url"),
                    "rights_verified_at": dataset.get("rights_verified_at"),
                    "commercial_use": dataset.get("commercial_use"),
                    "redistribution": dataset.get("redistribution"),
                    "modification": dataset.get("modification"),
                    "attribution_required": dataset.get("attribution_required"),
                    "attribution_text": dataset.get("attribution_text"),
                    "third_party_exclusions": dataset.get("third_party_exclusions") or [],
                    "redistributable": redistributable,
                },
                "validation": {
                    "status": "valid",
                    "checks": validation,
                    "issues": analysis.issues,
                },
                "stats": stats,
                "files": files,
                "semantics": {
                    "observation_time": "obs_start/obs_end are provider observation dates",
                    "publication_time": "published_at is populated only when the provider publishes one",
                    "provider_revision_time": "provider_revision_at is a provider revision/filing date, when known",
                    "ingestion_time": "retrieval.completed_at is when Atlas acquired the bytes",
                    "historical_availability": "not inferred from retrieval time",
                },
            }
            snapshot = self.store.commit(staging, manifest)
            self.index.record_snapshot(snapshot, validation_status="valid",
                                       rights_class=rights.value, redistributable=redistributable, stats=stats)
            ingest_stats = self.index.ingest_observations(analysis.observations, snapshot_id=snapshot.snapshot_id)
            for entity_id in {o.entity_id for o in analysis.observations if o.entity_id}:
                self.index.upsert_entity(entity_id, kind="issuer" if dataset["provider"] == "SEC" else "entity",
                                         provider=dataset["provider"], snapshot_id=snapshot.snapshot_id)
            self.store.write_checkpoint(dataset_id, {
                "etag": transfer.get("etag"),
                "last_modified": transfer.get("last_modified"),
                "content_length": transfer.get("bytes_downloaded"),
                "snapshot_id": snapshot.snapshot_id,
                "completed_at": utcnow(),
                "last_attempt": utcnow(),
                "kind": kind,
            })
            elapsed = round(time.monotonic() - started, 3)
            summary = {
                **stats,
                "ingest": ingest_stats,
                "snapshot_id": snapshot.snapshot_id,
                "manifest_sha256": snapshot.manifest_sha256,
                "elapsed_seconds": elapsed,
                "downloaded_bytes": transfer.get("bytes_downloaded", 0),
                "http_status": transfer.get("status"),
            }
            self.index.finish_run(
                run_id, status="acquired", http_status=transfer.get("status"),
                downloaded_bytes=int(transfer.get("bytes_downloaded") or 0),
                decompressed_bytes=int(analysis.decompressed_bytes),
                file_count=len(files), record_count=analysis.record_count,
                entity_count=analysis.entity_count, obs_start=analysis.obs_start,
                obs_end=analysis.obs_end, validation_failures=0,
                sha256=files[0]["sha256"] if files else None, elapsed_seconds=elapsed,
                snapshot_id=snapshot.snapshot_id, stats_json=summary,
            )
            return AcquisitionResult(dataset_id, "acquired", snapshot.snapshot_id, run_id, summary,
                                     manifest_path=str(snapshot.path / "manifest.json"))
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, never hidden
            elapsed = round(time.monotonic() - started, 3)
            reason = f"{type(exc).__name__}: {exc}"
            quarantined = self.store.quarantine(staging, dataset_id, reason, {"dataset": dataset_id})
            self.index.finish_run(run_id, status="failed", error=reason,
                                  elapsed_seconds=elapsed, stats_json={"quarantine": str(quarantined)})
            return AcquisitionResult(dataset_id, "failed", None, run_id, {}, error=reason)

    # --------------------------------------------------------------- validation
    def _validate_downloads(self, dataset: Dataset, files: Iterable[Path]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        cfg = dict(dataset.get("acquisition") or {})
        for path in files:
            fmt = archives.detect_format(path)
            check: dict[str, Any] = {"file": path.name, "detected_format": fmt, "bytes": path.stat().st_size}
            if path.stat().st_size == 0:
                raise ValueError(f"empty download: {path.name}")
            if fmt in {"zip", "tar", "gzip"}:
                limits = archives.DEFAULT_LIMITS
                override = cfg.get("archive_limits") or {}
                if override:
                    limits = archives.ArchiveLimits(**{k: v for k, v in override.items()
                                                       if k in archives.ArchiveLimits.__dataclass_fields__})
                inspection = archives.inspect(path, limits)
                check.update({"archive_members": inspection.members,
                              "uncompressed_bytes": inspection.uncompressed_bytes,
                              "compression_ratio": round(inspection.ratio, 2)})
                if inspection.members < 1:
                    raise ValueError(f"empty archive: {path.name}")
            elif fmt == "json":
                _validate_json(path)
            elif path.suffix.lower() in {".csv", ".tsv"} or (dataset.get("parse") or {}).get("delimiter"):
                columns = _validate_tabular(path, "\t" if (dataset.get("parse") or {}).get("delimiter") == "\t" else ",")
                check["columns"] = columns
            else:
                expected = cfg.get("format")
                if expected and expected != "unknown" and fmt == "unknown":
                    raise ValueError(f"unexpected format for {path.name}: {fmt}")
            checks.append(check)
        if not checks:
            raise ValueError("no files downloaded")
        return {"files": checks, "status": "valid"}

    def _register_files(self, dataset: Dataset, staging: Path, raw_files: list[Path]) -> list[dict[str, Any]]:
        files = []
        for path in raw_files:
            fmt = archives.detect_format(path)
            content_type = {
                "zip": "application/zip", "gzip": "application/gzip", "json": "application/json",
                "tar": "application/x-tar",
            }.get(fmt, "text/csv" if path.suffix.lower() in {".csv"} else "application/octet-stream")
            files.append(self.store.add_file(staging, path, name=path.name, content_type=content_type))
        return files

    def _write_derived(self, dataset: Dataset, staging: Path, analysis: adapters.Analysis) -> list[dict[str, Any]]:
        if not analysis.observations and not analysis.extra.get("sample_companies"):
            return []
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            return []
        derived_dir = staging / "derived"
        derived_dir.mkdir(exist_ok=True)
        entries: list[dict[str, Any]] = []
        if analysis.observations:
            rows = [{
                "dataset_id": o.dataset_id, "series_key": o.series_key, "entity_id": o.entity_id,
                "concept": o.concept, "obs_date": o.obs_date, "period_start": o.period_start,
                "period_end": o.period_end, "value_numeric": o.value_numeric,
                "unit": o.unit, "currency": o.currency, "published_at": o.published_at,
                "provider_revision_at": o.provider_revision_at,
            } for o in analysis.observations]
            path = derived_dir / f"{dataset.id.replace('.', '_')}.parquet"
            pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
            entry = self.store.add_file(staging, path, name=path.name, content_type="application/vnd.apache.parquet",
                                        uncompressed_bytes=path.stat().st_size, records=len(rows),
                                        notes="derived observation table; raw source bytes are the authority")
            entries.append(entry)
            analysis.extra["derived_observations"] = len(rows)
            analysis.extra["derived_compression"] = "zstd"
        return entries

    def export_manifest(self, snapshot: Snapshot, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(snapshot.manifest)
        payload["exported_at"] = utcnow()
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target

    def adopt_snapshot(self, dataset_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
        """Re-index an already committed snapshot without downloading it again.

        Recovery path for a crash or index-lock failure after an immutable snapshot was
        published: the raw bytes are the authority, so they are re-analysed and the
        missing index rows are written. Nothing in the snapshot is modified.
        """
        snapshots = self.store.list_snapshots(dataset_id)
        snapshot = next((s for s in snapshots if snapshot_id is None or s.snapshot_id == snapshot_id), None)
        if snapshot is None:
            raise FileNotFoundError(f"no stored snapshot for {dataset_id} {snapshot_id or ''}".strip())
        report = self.store.verify(snapshot, deep=True)
        if not report["ok"]:
            raise ValueError(f"snapshot failed integrity verification: {report}")
        entry = self.registry.get(dataset_id)
        dataset = entry.to_dict()
        files = {item["name"]: snapshot.path / "files" / item["path"] for item in snapshot.files}
        analysis = adapters.analyze(dataset, files)
        if analysis.future_dates:
            analysis.issues.append({
                "code": "future_observation_dates", "severity": "warning",
                "detail": (f"{analysis.future_dates} provider rows carry a future period end; "
                           "they remain in the raw snapshot and are excluded from advertised coverage"),
            })
        if analysis.implausible_dates:
            analysis.issues.append({
                "code": "implausible_observation_dates", "severity": "warning",
                "detail": (f"{analysis.implausible_dates} provider rows carry dates outside "
                           "1900-01-01..today+2y; they remain in the raw snapshot but are excluded "
                           "from the advertised coverage range"),
            })
        rights = entry.rights_class
        stats = analysis.to_stats(dataset_id)
        self.index.record_snapshot(snapshot, validation_status="valid", rights_class=rights.value,
                                   redistributable=bool(entry.get("redistribution")), stats=stats)
        ingest = self.index.ingest_observations(analysis.observations, snapshot_id=snapshot.snapshot_id)
        return {"dataset": dataset_id, "snapshot": snapshot.snapshot_id, "stats": stats,
                "ingest": ingest, "verified": True}

    # ------------------------------------------------------------------- verify
    def verify(self, dataset_id: str | None = None, *, deep: bool = True) -> dict[str, Any]:
        snapshots = self.store.list_snapshots(dataset_id)
        reports = [self.store.verify(snapshot, deep=deep) for snapshot in snapshots]
        return {
            "datasets": len({s.dataset_id for s in snapshots}),
            "snapshots": len(snapshots),
            "ok": all(report["ok"] for report in reports),
            "failures": [report for report in reports if not report["ok"]],
            "reports": reports,
        }

    def sync(self, dataset_ids: Iterable[str] | None = None, *, provider: str | None = None,
             automated: bool = False, public_distribution: bool = False, force: bool = False,
             max_bytes: int | None = None) -> list[dict[str, Any]]:
        targets = self.registry.select(dataset_ids, provider=provider)
        if not targets:
            raise KeyError("no registry entries matched the requested selection")
        results = []
        for dataset in targets:
            results.append(self.acquire(dataset.id, automated=automated,
                                        public_distribution=public_distribution,
                                        force=force, max_bytes=max_bytes).to_dict())
        return results
