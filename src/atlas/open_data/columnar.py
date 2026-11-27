"""Partitioned Parquet evidence storage with DuckDB queries and lazy materialisation.

The eager kernel keeps every observation in one SQLite database. That is correct and
transactional, but a 20,000-company archive turns into a multi-gigabyte file that a
researcher must import before asking a single question about one company.

This module is the alternative evaluated in Phase IV:

* every normalised evidence row is written once to partitioned Parquet (Zstandard),
  partitioned by a deterministic CIK bucket so a company lookup prunes to one file
  and sorted row groups keep per-company scans small;
* DuckDB queries the dataset in place, so point-in-time, statement, screening and
  restatement questions need no import;
* one company can be *materialised* into the existing SQLite kernel on demand, for
  the workflows that need the kernel's transaction and lineage guarantees;
* the authoritative archive is retained and every member's hash is recorded, so the
  exact source bytes remain reconstructable independently of the derived columns.

The column names mirror ``atlas.evidence.model.EvidenceRecord`` so a row can be
materialised without a second interpretation of XBRL.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from ..core.ids import normalize_cik
from ..core.temporal import iso, utcnow
from ..ingestion.sec_companyfacts import parse_companyfacts
from .store import sha256_file

DATASET_ID = "sec.companyfacts"
#: v2 adds ``consolidated_scope``. A v1 build cannot prove that a fact is a consolidated
#: entity-level observation, so cross-company ranking and statements refuse it rather than
#: assuming the scope. Rebuild is the documented migration.
SCHEMA_VERSION = "atlas.open_data.columnar.v2"
SCOPE_SCHEMA_VERSION = "atlas.open_data.columnar.v1"
BUCKET_COUNT = 16
FLUSH_COMPANIES = 50

#: ``companyfacts`` publishes entity-level XBRL facts with no dimension members, so every
#: archived row is a consolidated observation. The value is stored explicitly so a future
#: dimensioned store cannot be ranked against it by accident.
CONSOLIDATED_SCOPE = "consolidated"

#: Availability classes, in decreasing strength of evidence.
AVAILABILITY_OBSERVED = "observed"    # documented instant (EDGAR acceptanceDateTime)
AVAILABILITY_BOUNDED = "bounded"      # documented conservative upper bound (filing date, end of day)
AVAILABILITY_ESTIMATED = "estimated"  # modelled lag; not an observed public-release instant
AVAILABILITY_UNKNOWN = "unknown"      # no usable timing evidence
AVAILABILITY_CLASSES = (
    AVAILABILITY_OBSERVED,
    AVAILABILITY_BOUNDED,
    AVAILABILITY_ESTIMATED,
    AVAILABILITY_UNKNOWN,
)
#: Classes a historical (point-in-time) query may select. An estimated timestamp is a model,
#: not evidence of when the public could read the fact, so it is excluded with unknown.
HISTORICAL_AVAILABILITY = (AVAILABILITY_OBSERVED, AVAILABILITY_BOUNDED)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
#: Inclusive day range accepted as a fiscal year (52/53-week years are 364/371 days).
ANNUAL_DAYS = (300, 430)


QUARTER_DAYS = (80, 100)


def _duration_days(row: Mapping[str, Any]) -> int | None:
    start, end = row.get("period_start"), row.get("period_end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _annual_duration(row: Mapping[str, Any]) -> bool:
    days = _duration_days(row)
    return days is not None and ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]


def _quarter_duration(row: Mapping[str, Any]) -> bool:
    days = _duration_days(row)
    return days is not None and QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]


def availability_class(row: Mapping[str, Any]) -> str:
    """Classify one observation's public-availability evidence.

    The canonical evidence kernel stores an unknown precision as ``unknown`` with no
    timestamp, and that rule is repeated here so both layers agree. A modelled timestamp
    (an acceptance instant plus an assumed publication lag) is *estimated*: it is a
    bound produced by a model, not an observed public-release instant, and it is never
    used by a historical query.
    """
    moment = row.get("availability_time")
    precision = str(row.get("availability_precision") or "").lower()
    basis = str(row.get("availability_basis") or "").lower()
    if not moment or precision == AVAILABILITY_UNKNOWN:
        return AVAILABILITY_UNKNOWN
    if "estimated" in basis or "publication_lag" in basis:
        return AVAILABILITY_ESTIMATED
    if precision == "exact":
        return AVAILABILITY_OBSERVED
    if precision == "date":
        return AVAILABILITY_BOUNDED
    return AVAILABILITY_UNKNOWN

#: Parquet columns, in the order rows are built. `value_numeric` stays a canonical
#: decimal string: a float column would round the source.
COLUMNS: tuple[str, ...] = (
    "cik",
    "entity_name",
    "member",
    "concept",
    "value_numeric",
    "unit",
    "unit_kind",
    "currency",
    "consolidated_scope",
    "period_start",
    "period_end",
    "period_type",
    "fiscal_year",
    "fiscal_period",
    "availability_time",
    "availability_precision",
    "availability_basis",
    "filed_date",
    "acceptance_datetime",
    "accession_number",
    "form_type",
    "revision_kind",
    "quality",
    "taxonomy",
    "source_concept",
    "source_url",
    "content_hash",
    "source_snapshot",
    "ingest_seq",
)

#: Columns whose DuckDB type is numeric rather than text.
INTEGER_COLUMNS = {"fiscal_year": "int32", "ingest_seq": "int64"}


def _pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise RuntimeError(
            "pyarrow is required for the columnar evidence store; install the "
            "`columnar` or `open-data` extra") from exc
    return pa, pq


def arrow_schema():
    pa, _ = _pyarrow()
    fields = []
    for name in COLUMNS:
        if name == "fiscal_year":
            fields.append(pa.field(name, pa.int32()))
        elif name == "ingest_seq":
            fields.append(pa.field(name, pa.int64()))
        else:
            fields.append(pa.field(name, pa.string()))
    return pa.schema(fields)


def bucket_for(cik: str, buckets: int = BUCKET_COUNT) -> int:
    """Deterministic CIK bucket. Documented so a rebuild lands in the same files."""
    digits = "".join(ch for ch in normalize_cik(cik) if ch.isdigit())
    return int(digits or "0") % buckets


def _row(record, *, cik: str, entity_name: str, member: str, snapshot_id: str) -> dict[str, Any]:
    return {
        "cik": cik,
        "entity_name": entity_name,
        "member": member,
        "concept": record.concept,
        "value_numeric": record.value_numeric,
        "unit": record.unit,
        "unit_kind": record.unit_kind,
        "currency": record.currency,
        "consolidated_scope": CONSOLIDATED_SCOPE,
        "period_start": record.period_start,
        "period_end": record.period_end,
        "period_type": record.period_type,
        "fiscal_year": record.fiscal_year,
        "fiscal_period": record.fiscal_period,
        "availability_time": record.availability_time,
        "availability_precision": record.availability_precision,
        "availability_basis": record.availability_basis,
        "filed_date": record.filed_date,
        "acceptance_datetime": record.acceptance_datetime,
        "accession_number": record.accession_number,
        "form_type": record.form_type,
        "revision_kind": record.revision_kind,
        "quality": record.quality,
        "taxonomy": record.taxonomy,
        "source_concept": record.source_concept,
        "source_url": record.source_url,
        "content_hash": record.content_hash,
        "source_snapshot": snapshot_id,
        "ingest_seq": int(record.ingest_seq or 0),
    }


class _BucketWriter:
    def __init__(self, root: Path, buckets: int) -> None:
        self.root = root
        self.buckets = buckets
        _, self.pq = _pyarrow()
        self.schema = arrow_schema()
        self.writers: dict[int, Any] = {}
        self.buffers: dict[int, list[dict[str, Any]]] = {}
        self.rows = 0
        self.files: dict[int, str] = {}

    def _writer(self, bucket: int):
        writer = self.writers.get(bucket)
        if writer is None:
            directory = self.root / "evidence" / f"cik_bucket={bucket:02d}"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "part-00000.parquet"
            writer = self.pq.ParquetWriter(path, self.schema, compression="zstd",
                                           use_dictionary=True, write_statistics=True)
            self.writers[bucket] = writer
            self.files[bucket] = path.relative_to(self.root).as_posix()
        return writer

    def add(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.buffers.setdefault(bucket_for(row["cik"], self.buckets), []).append(row)
            self.rows += 1

    def flush(self) -> None:
        pa, _ = _pyarrow()
        for bucket, rows in self.buffers.items():
            if not rows:
                continue
            # Sorting by cik keeps per-company row groups tight; sorting by the rest
            # keeps a statement scan within one company deterministic.
            rows.sort(key=lambda item: (item["cik"], item["concept"],
                                        item["period_end"] or "", item["accession_number"] or ""))
            table = pa.Table.from_pylist(rows, schema=self.schema)
            self._writer(bucket).write_table(table)
        self.buffers.clear()

    def close(self) -> None:
        self.flush()
        for writer in self.writers.values():
            writer.close()
        self.writers.clear()


def build_from_archive(
    archive: str | Path,
    out_dir: str | Path,
    *,
    snapshot_id: str,
    bucket_count: int = BUCKET_COUNT,
    limit: int | None = None,
    member_names: Sequence[str] | None = None,
    observed_at: str | None = None,
    flush_companies: int = FLUSH_COMPANIES,
    source_id: str = "sec_edgar",
    progress: bool = False,
) -> dict[str, Any]:
    """Normalise members of a companyfacts archive into partitioned Parquet.

    ``limit`` counts archive members in deterministic name order, so a limited build
    describes exactly the same companies as a limited SQLite integration.
    ``member_names`` selects an explicit list (used for a stratified validation
    sample) and takes precedence over ``limit``.
    """
    started = time.monotonic()
    source = Path(archive)
    archive_sha = sha256_file(source)
    archive_bytes = source.stat().st_size
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    writer = _BucketWriter(root, bucket_count)
    member_index: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    companies = 0
    ineligible = 0
    with zipfile.ZipFile(source) as bundle:
        if member_names is not None:
            names = sorted(member_names)
        else:
            names = sorted(name for name in bundle.namelist() if name.endswith(".json"))
            if limit is not None:
                names = names[:limit]
        for name in names:
            raw = bundle.read(name)
            digest = hashlib.sha256(raw).hexdigest()
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                rejected.append({"member": name, "stage": "parse", "error": str(exc)})
                continue
            cik_value = payload.get("cik")
            if cik_value is None:
                rejected.append({"member": name, "stage": "identity", "error": "no cik"})
                continue
            cik = normalize_cik(str(cik_value))
            entity_name = str(payload.get("entityName") or f"CIK {cik}")
            try:
                parsed = parse_companyfacts(
                    payload, issuer_id=f"CIK{cik}", source_id=source_id,
                    source_url=(f"https://www.sec.gov/Archives/edgar/daily-index/xbrl/"
                                f"companyfacts.zip#member={name}&cik={cik}"
                                f"&zip_sha256={archive_sha}"
                                f"&snapshot={snapshot_id}"),
                    observed_at=observed_at,
                )
            except Exception as exc:  # noqa: BLE001 - one malformed issuer is reported
                rejected.append({"member": name, "cik": cik, "stage": "normaliser",
                                 "error": f"{type(exc).__name__}: {exc}"})
                companies += 1
                ineligible += 1
                continue
            companies += 1
            member_index.append({"member": name, "cik": cik, "bytes": len(raw),
                                 "sha256": digest, "records": len(parsed.records)})
            if not parsed.records:
                ineligible += 1
                continue
            writer.add(_row(record, cik=cik, entity_name=entity_name, member=name,
                            snapshot_id=snapshot_id)
                       for record in parsed.records)
            if companies % flush_companies == 0:
                writer.flush()
            if progress and companies % 500 == 0:
                print(json.dumps({"companies": companies, "rows": writer.rows,
                                  "elapsed_seconds": round(time.monotonic() - started, 1)}),
                      flush=True)
    writer.close()
    elapsed = time.monotonic() - started

    parquet_files = sorted(path for path in (root / "evidence").rglob("*.parquet"))
    file_entries = [{"path": path.relative_to(root).as_posix(),
                     "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                    for path in parquet_files]
    manifest = {
        "schema": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "snapshot_id": snapshot_id,
        "created_at": iso(utcnow()),
        "archive": {"path": str(source), "bytes": archive_bytes, "sha256": archive_sha},
        "scope": {
            "column": "consolidated_scope",
            "value": CONSOLIDATED_SCOPE,
            "why": ("companyfacts publishes entity-level facts without dimension members; "
                    "the value is stored so a dimensioned store cannot be ranked with it"),
        },
        "availability": {
            "classes": list(AVAILABILITY_CLASSES),
            "historical": list(HISTORICAL_AVAILABILITY),
            "why": ("an unknown or modelled availability cannot place a fact in time; "
                    "historical queries exclude both and report the count"),
        },
        "partitioning": {
            "column": "cik_bucket",
            "buckets": bucket_count,
            "function": "int(normalize_cik(cik)) % buckets",
            "sort_order": ["cik", "concept", "period_end", "accession_number"],
            "why": ("one bucket per company keeps a company lookup to one file; sorting by "
                    "cik keeps row-group statistics tight without one file per company"),
        },
        "columns": list(COLUMNS),
        "companies": companies,
        "ineligible_companies": ineligible,
        "records": writer.rows,
        "members": len(member_index),
        "member_index": member_index,
        "rejected": rejected[:500],
        "files": file_entries,
        "parquet_bytes": sum(item["bytes"] for item in file_entries),
        "elapsed_seconds": round(elapsed, 2),
        "exact_source": (
            "The archive is the authoritative copy and is not rewritten. Every member's "
            "SHA-256 is recorded, so `extract_member` reconstructs the exact source bytes "
            "independently of the derived columns."
        ),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_manifest(root: str | Path) -> dict[str, Any]:
    return json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))


def extract_member(root: str | Path, cik: str) -> dict[str, Any]:
    """Return the exact archived bytes for one company, verified against the index."""
    manifest = load_manifest(root)
    cik = normalize_cik(cik)
    entry = next((item for item in manifest["member_index"] if item["cik"] == cik), None)
    if entry is None:
        raise KeyError(f"CIK {cik} is not in this columnar build")
    archive = Path(manifest["archive"]["path"])
    with zipfile.ZipFile(archive) as bundle:
        raw = bundle.read(entry["member"])
    actual = hashlib.sha256(raw).hexdigest()
    if actual != entry["sha256"]:
        raise ValueError(f"{entry['member']} hashes to {actual}, index says {entry['sha256']}")
    return {"member": entry["member"], "bytes": len(raw), "sha256": actual, "content": raw}


# --------------------------------------------------------------------------- query
#: Kernel quality ranking, repeated so columnar adjudication orders versions the same way.
QUALITY_RANK = {"verified": 0, "unverified": 1, "suspect": 2, "quarantined": 3}


class IncomparableScreen(ValueError):
    """A ranking request that cannot be answered without an explicit choice.

    The exception is a refusal, not a failure: it names the incompatible groups so the
    caller can restate the request in one currency, unit, scope and duration.
    """

    def __init__(self, message: str, *, groups: Sequence[Mapping[str, Any]] = ()) -> None:
        super().__init__(message)
        self.groups = [dict(group) for group in groups]


@dataclass(frozen=True)
class ScreenSpec:
    """What makes two observations comparable for one cross-company ranking."""

    concept: str
    fiscal_year: int | None = None
    period: str = "auto"  # annual | quarter | instant | auto
    currency: str | None = None
    unit: str | None = None
    scope: str = CONSOLIDATED_SCOPE
    as_of: str | None = None
    fiscal_period: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "fiscal_year": self.fiscal_year,
            "period": self.period,
            "currency": self.currency,
            "unit": self.unit,
            "scope": self.scope,
            "as_of": self.as_of,
            "fiscal_period": self.fiscal_period,
        }


def _period_kind(row: Mapping[str, Any]) -> str:
    days = _duration_days(row)
    if days is None:
        return "instant"
    if ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]:
        return "annual"
    if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
        return "quarter"
    return "other"


def _quality(row: Mapping[str, Any]) -> int:
    return QUALITY_RANK.get(str(row.get("quality") or ""), 9)


@dataclass
class ColumnarEvidence:
    """DuckDB access to one columnar build. Nothing is imported into SQLite.

    Historical reads exclude observations whose public availability is unknown or only
    estimated, mirroring ``EvidenceKernel.as_of``: a fact that cannot be placed in time
    cannot answer "what was knowable then". ``include_unknown=True`` is the explicit
    opt-out and the result records how many observations it let through.
    """

    root: str | Path
    threads: int = 1

    def __post_init__(self) -> None:
        import duckdb  # noqa: PLC0415 - optional dependency, imported on use

        self.root = Path(self.root)
        self.manifest = load_manifest(self.root)
        self.conn = duckdb.connect(database=":memory:")
        self.conn.execute(f"SET threads={int(self.threads)}")
        pattern = str((self.root / "evidence" / "**" / "*.parquet")).replace("'", "''")
        self.conn.execute(
            "CREATE VIEW evidence AS SELECT * FROM read_parquet('" + pattern +
            "', hive_partitioning=1, union_by_name=true)")
        self.conn.execute("CREATE VIEW fact AS SELECT * FROM evidence WHERE value_numeric IS NOT NULL")
        described = self.conn.execute("DESCRIBE SELECT * FROM evidence").fetchall()
        self.columns = tuple(row[0] for row in described)
        # A build without the scope column cannot prove entity-level consolidation.
        self.scope_verified = "consolidated_scope" in self.columns
        self._files_by_bucket: dict[int, list[str]] = {}
        for entry in self.manifest.get("files") or []:
            match = re.search(r"cik_bucket=(\d+)", str(entry.get("path") or ""))
            if match:
                self._files_by_bucket.setdefault(int(match.group(1)), []).append(
                    str(self.root / str(entry["path"])))

    def _bucket_files(self, bucket: int) -> list[str]:
        return self._files_by_bucket.get(bucket, [])

    def _require_scope(self) -> None:
        if not self.scope_verified:
            raise IncomparableScreen(
                "this build predates the consolidated-scope column (schema "
                f"{self.manifest.get('schema')!r}); statements, screening and restatement "
                "identity cannot be certified without it. Rebuild with the current "
                f"{SCHEMA_VERSION} writer.")

    def _scope_clause(self) -> str:
        return "consolidated_scope = ?"

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ queries
    def _rows(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        cursor = self.conn.execute(sql, list(params))
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def company(self, cik: str, *, as_of: str | None = None,
                concepts: Sequence[str] | None = None,
                include_unknown: bool = False) -> list[dict[str, Any]]:
        normalized = normalize_cik(cik)
        # A company lives in exactly one bucket file. Reading that file directly is what
        # keeps a lookup cheap at full-universe scale: a glob over 256 files cost 1.2 s
        # per query, while one 4 MB file costs milliseconds.
        bucket = bucket_for(normalized, int(self.manifest["partitioning"]["buckets"]))
        files = self._bucket_files(bucket)
        source = ("read_parquet([" + ",".join(_literal(path) for path in files) + "])"
                  if files else "fact")
        sql = (f"SELECT cik, concept, value_numeric, unit, unit_kind, currency, "
               f" period_start, period_end, period_type, fiscal_year, fiscal_period, "
               f" availability_time, availability_precision, availability_basis, "
               f" filed_date, accession_number, form_type, revision_kind, quality, "
               f" taxonomy, source_concept, ingest_seq"
               + (", consolidated_scope" if self.scope_verified else "")
               + f" FROM {source} WHERE cik=?")
        params: list[Any] = [normalized]
        if as_of and not include_unknown:
            sql += " AND availability_time IS NOT NULL AND availability_time <= ?"
            params.append(as_of)
        elif as_of:
            sql += " AND (availability_time IS NULL OR availability_time <= ?)"
            params.append(as_of)
        if concepts:
            sql += " AND concept IN (" + ",".join("?" for _ in concepts) + ")"
            params.extend(concepts)
        sql += " ORDER BY period_end DESC, concept, accession_number, ingest_seq"
        rows = self._rows(sql, params)
        for row in rows:
            row.setdefault("consolidated_scope", CONSOLIDATED_SCOPE if self.scope_verified else None)
            row["availability_class"] = availability_class(row)
        return rows

    def search_companies(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Find issuers in the build by name fragment, for terminal and MCP lookups."""
        needle = f"%{query.strip().lower()}%"
        sql = ("SELECT cik, any_value(entity_name) AS entity_name, COUNT(*) AS observations, "
               "MIN(period_end) AS first_period_end, MAX(period_end) AS last_period_end "
               "FROM evidence WHERE lower(entity_name) LIKE ? GROUP BY cik "
               "ORDER BY entity_name, cik LIMIT ?")
        return self._rows(sql, [needle, int(limit)])

    def availability(self, cik: str) -> dict[str, Any]:
        """Count one company's observations by availability class, without a cutoff.

        This is the audit view for a point-in-time answer: it says how many observations
        the historical query had to exclude and why.
        """
        rows = self.company(cik)
        counts = {name: 0 for name in AVAILABILITY_CLASSES}
        for row in rows:
            counts[row["availability_class"]] += 1
        return {
            "cik": normalize_cik(cik),
            "observations": len(rows),
            "by_class": counts,
            "usable_historically": sum(counts[name] for name in HISTORICAL_AVAILABILITY),
            "excluded_from_history": counts[AVAILABILITY_ESTIMATED] + counts[AVAILABILITY_UNKNOWN],
        }

    def statement(self, cik: str, *, period_end: str | None = None,
                  as_of: str | None = None) -> dict[str, Any]:
        """One period's facts, selected the way the canonical evidence kernel selects.

        Grouping is by concept, period, unit, currency and scope; the latest available
        version wins, identical values keep the earliest document as provenance, and two
        different values at the same availability instant are reported as a contradiction
        rather than silently resolved by row order.
        """
        self._require_scope()
        rows = self.company(cik, as_of=as_of)
        if not rows:
            return {"cik": normalize_cik(cik), "period_end": period_end, "concepts": {},
                    "evidence": {}, "contradictions": [], "selection_policy": "kernel_parity_v1"}
        target = period_end or rows[0]["period_end"]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row["period_end"] == target:
                grouped.setdefault(row["concept"], []).append(row)
        selected: dict[str, dict[str, Any]] = {}
        contradictions: list[dict[str, Any]] = []
        for concept, candidates in grouped.items():
            # A fiscal year end is also the end of a fourth quarter, so the same concept
            # can carry a 3-month and a 12-month value for one date. Prefer the annual
            # duration, then an instant (balance-sheet) value, and only fall back to the
            # short periods when the issuer reports nothing else for that date.
            annual = [row for row in candidates if _annual_duration(row)]
            if annual:
                candidates = annual
            elif any(row["period_start"] is None for row in candidates):
                candidates = [row for row in candidates if row["period_start"] is None]
            # Identity: the same fact asserted for the same unit, currency and scope.
            by_identity: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for row in candidates:
                key = (concept, row.get("period_start") or "", row.get("period_end") or "",
                       row.get("unit") or "", row.get("currency") or "", CONSOLIDATED_SCOPE)
                by_identity.setdefault(key, []).append(row)
            for key, versions in by_identity.items():
                versions.sort(key=lambda row: (row["availability_time"] or "", _quality(row),
                                               row["ingest_seq"], row["accession_number"] or ""))
                latest = versions[-1]
                same_moment = [row for row in versions
                               if (row["availability_time"] or "") == (latest["availability_time"] or "")]
                if len({row["value_numeric"] for row in same_moment}) > 1:
                    contradictions.append({
                        "concept": concept,
                        "period_end": key[2],
                        "availability_time": latest["availability_time"],
                        "values": sorted({row["value_numeric"] for row in same_moment}),
                        "accessions": sorted({row["accession_number"] for row in same_moment
                                              if row["accession_number"]}),
                    })
                chosen = min((row for row in versions
                              if row["value_numeric"] == latest["value_numeric"]),
                             key=lambda row: (row["availability_time"] or "", row["ingest_seq"]))
                selected[concept] = chosen
        return {
            "cik": normalize_cik(cik),
            "period_end": target,
            "concepts": {name: value["value_numeric"] for name, value in selected.items()},
            "evidence": selected,
            "contradictions": contradictions,
            "selection_policy": "kernel_parity_v1",
            "scope": CONSOLIDATED_SCOPE,
        }

    def screen(self, *, concept: str, fiscal_year: int | None = None,
               minimum: float | str | None = None, limit: int = 100,
               period: str = "auto", currency: str | None = None,
               unit: str | None = None, scope: str = CONSOLIDATED_SCOPE,
               as_of: str | None = None, fiscal_period: str | None = None,
               spec: ScreenSpec | None = None) -> list[dict[str, Any]]:
        """Cross-company ranking of strictly comparable observations.

        Backwards-compatible shape (``cik``/``value`` rows). See :meth:`screen_report`
        for the refusals and exclusions behind the ranking.
        """
        resolved = spec or ScreenSpec(
            concept=concept, fiscal_year=fiscal_year, period=period, currency=currency,
            unit=unit, scope=scope, as_of=as_of, fiscal_period=fiscal_period,
        )
        report = self.screen_report(resolved, minimum=minimum, limit=limit)
        return report["selected"]

    def _candidates(self, spec: ScreenSpec) -> list[dict[str, Any]]:
        self._require_scope()
        sql = ("SELECT cik, concept, value_numeric, unit, unit_kind, currency, period_start, "
               "period_end, period_type, fiscal_year, fiscal_period, availability_time, "
               "availability_precision, availability_basis, accession_number, form_type, "
               "revision_kind, quality, ingest_seq FROM fact WHERE concept = ?")
        params: list[Any] = [spec.concept]
        if spec.fiscal_year is not None:
            sql += " AND fiscal_year = ?"
            params.append(spec.fiscal_year)
        if spec.scope != CONSOLIDATED_SCOPE:
            raise IncomparableScreen(
                f"scope {spec.scope!r} cannot be selected: this build stores consolidated "
                "entity facts only")
        sql += " AND consolidated_scope = ?"
        params.append(CONSOLIDATED_SCOPE)
        # The cutoff is applied per row while refusing, so an observation that was not yet
        # public is reported as excluded instead of silently disappearing from the count.
        rows = self._rows(sql, params)
        for row in rows:
            row["availability_class"] = availability_class(row)
            row["period_kind"] = _period_kind(row)
        return rows

    def _resolve_period(self, spec: ScreenSpec,
                        rows: Sequence[Mapping[str, Any]]) -> str:
        if spec.period != "auto":
            if spec.period not in {"annual", "quarter", "instant"}:
                raise IncomparableScreen(
                    f"period {spec.period!r} is not one of annual, quarter, instant or auto")
            return spec.period
        kinds = {row["period_kind"] for row in rows}
        usable = kinds - {"other"}
        if not usable:
            raise IncomparableScreen(
                "no observation has a comparable reporting duration; the screen needs an "
                "explicit annual, quarter or instant period")
        if len(usable) > 1:
            counts = {kind: sum(1 for row in rows if row["period_kind"] == kind) for kind in usable}
            raise IncomparableScreen(
                "observations mix instant and duration values, which are not comparable as "
                "one ranking; pass period='annual', 'quarter' or 'instant'",
                groups=[{"period": kind, "observations": counts[kind]} for kind in sorted(counts)])
        return usable.pop()

    def screen_report(self, spec: ScreenSpec, *, minimum: float | str | None = None,
                      limit: int = 100, max_refusals: int = 200) -> dict[str, Any]:
        """Rank one concept across issuers, refusing every incomparable observation.

        Rules, in order:

        * consolidated entity scope only;
        * one reporting duration (annual, quarter or instant), decided explicitly or, under
          ``auto``, only when every observation agrees;
        * one unit and one currency for the whole ranking, or the request is refused;
        * point-in-time cutoff on evidenced availability (observed or bounded);
        * restatement-aware selection: the latest available version of the period wins;
        * exact decimal comparison, deterministic order (value desc, then CIK asc).

        ``minimum`` is compared as an exact decimal. ``float`` is accepted for
        compatibility and converted through its shortest decimal representation.
        """
        from decimal import Decimal, InvalidOperation  # noqa: PLC0415

        def _decimal(text: Any) -> Decimal | None:
            if text is None:
                return None
            try:
                return Decimal(str(text))
            except (InvalidOperation, ValueError):
                return None

        candidates = self._candidates(spec)
        if not candidates:
            return {"request": spec.to_dict(), "comparable": None, "selected": [],
                    "refused": [], "excluded": {}, "notes": ["no observation matches the request"]}
        period = self._resolve_period(spec, candidates)
        refused: list[dict[str, Any]] = []
        comparable: list[dict[str, Any]] = []
        excluded = {"unknown_availability": 0, "estimated_availability": 0,
                    "not_available_at_cutoff": 0, "wrong_period": 0,
                    "wrong_scope": 0, "wrong_fiscal_period": 0,
                    "wrong_unit": 0, "wrong_currency": 0}
        for row in candidates:
            reason = None
            if row["period_kind"] != period:
                excluded["wrong_period"] += 1
                reason = f"reporting duration is {row['period_kind']}, not {period}"
            elif spec.unit and str(row.get("unit") or "") != spec.unit:
                excluded["wrong_unit"] += 1
                reason = f"unit {row.get('unit')!r} is not the requested {spec.unit!r}"
            elif spec.currency and str(row.get("currency") or "") != spec.currency:
                excluded["wrong_currency"] += 1
                reason = f"currency {row.get('currency')!r} is not the requested {spec.currency!r}"
            elif spec.fiscal_period and str(row.get("fiscal_period") or "").upper() != spec.fiscal_period.upper():
                excluded["wrong_fiscal_period"] += 1
                reason = f"fiscal period is {row.get('fiscal_period')!r}, not {spec.fiscal_period!r}"
            elif row["availability_class"] == AVAILABILITY_UNKNOWN:
                excluded["unknown_availability"] += 1
                reason = "public availability is unknown, so the observation cannot be placed in time"
            elif row["availability_class"] == AVAILABILITY_ESTIMATED:
                excluded["estimated_availability"] += 1
                reason = "public availability is a modelled estimate, not an observed release"
            elif spec.as_of and (row["availability_time"] or "") > spec.as_of:
                excluded["not_available_at_cutoff"] += 1
                reason = "observation was not publicly available at the requested cutoff"
            if reason is not None:
                if len(refused) < max_refusals:
                    refused.append({"cik": row["cik"], "reason": reason,
                                    "period_end": row.get("period_end"),
                                    "unit": row.get("unit"), "currency": row.get("currency")})
                continue
            comparable.append(row)

        if not comparable:
            return {"request": spec.to_dict(), "comparable": None, "selected": [],
                    "refused": refused, "excluded": excluded,
                    "notes": ["every candidate observation was refused; nothing was ranked"]}

        units = sorted({str(row.get("unit") or "") for row in comparable})
        currencies = sorted({str(row.get("currency") or "") for row in comparable})
        if len(units) > 1 or len(currencies) > 1:
            # Ranking across units or currencies compares unlike quantities. The caller
            # must choose one, and the choice is recorded in the result.
            counts = [{"unit": name, "currency": currency,
                       "observations": sum(1 for row in comparable
                                           if str(row.get("unit") or "") == name
                                           and str(row.get("currency") or "") == currency)}
                      for name in units for currency in currencies
                      if any(str(row.get("unit") or "") == name and str(row.get("currency") or "") == currency
                             for row in comparable)]
            raise IncomparableScreen(
                "observations span more than one unit or currency; a ranking needs one "
                "comparable quantity (and no source-backed conversion exists in this layer)",
                groups=counts)
        unit, currency = units[0], currencies[0]

        # Restatement-aware selection: one row per issuer, the latest available version.
        latest: dict[str, dict[str, Any]] = {}
        for row in comparable:
            current = latest.get(row["cik"])
            if current is None or (
                (row["availability_time"] or ""), row["ingest_seq"], row["accession_number"] or ""
            ) > (
                (current["availability_time"] or ""), current["ingest_seq"], current["accession_number"] or ""
            ):
                latest[row["cik"]] = row

        threshold = _decimal(minimum) if minimum is not None else None
        ranked: list[tuple[Decimal, str, dict[str, Any]]] = []
        for cik, row in latest.items():
            value = _decimal(row["value_numeric"])
            if value is None:
                refused.append({"cik": cik, "reason": "value is not a decimal number",
                                "period_end": row.get("period_end"),
                                "unit": row.get("unit"), "currency": row.get("currency")})
                continue
            if threshold is not None and value < threshold:
                continue
            ranked.append((value, cik, row))
        # Deterministic: value descending, then CIK ascending.
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = [{
            "cik": cik,
            "value": str(value),
            "unit": row.get("unit"),
            "currency": row.get("currency"),
            "period_end": row.get("period_end"),
            "period_start": row.get("period_start"),
            "fiscal_year": row.get("fiscal_year"),
            "fiscal_period": row.get("fiscal_period"),
            "availability_time": row.get("availability_time"),
            "availability_class": row.get("availability_class"),
            "accession_number": row.get("accession_number"),
            "form_type": row.get("form_type"),
            "scope": CONSOLIDATED_SCOPE,
        } for value, cik, row in ranked[: int(limit)]]

        return {
            "request": spec.to_dict(),
            "comparable": {
                "concept": spec.concept,
                "fiscal_year": spec.fiscal_year,
                "period": period,
                "unit": unit,
                "currency": currency,
                "scope": CONSOLIDATED_SCOPE,
                "as_of": spec.as_of,
                "minimum": None if threshold is None else str(threshold),
                "observations_considered": len(comparable),
            },
            "selected": selected,
            "ranked_total": len(ranked),
            "refused": refused,
            "excluded": excluded,
            "notes": [
                "values are exact decimals; no currency conversion is applied or implied",
                "the latest available version of each period is used; earlier versions stay in the store",
            ],
        }

    def point_in_time(self, cik: str, as_of: str, concept: str | None = None) -> list[dict[str, Any]]:
        return self.company(cik, as_of=as_of, concepts=[concept] if concept else None)

    def restatements(self, cik: str) -> list[dict[str, Any]]:
        """Value revisions, keyed by the full observation identity.

        Identity is concept, period start and end (and therefore duration), unit, currency
        and consolidated scope. Grouping on concept and period end alone conflated an
        annual figure with its fourth quarter, and a USD fact with the same concept in
        another currency. Re-reporting an unchanged value is a comparative, not a
        restatement, and is not returned here.
        """
        report = self.restatement_report(cik)
        return report["findings"]

    def restatement_report(self, cik: str) -> dict[str, Any]:
        """Every revision class for one issuer, including non-restatement repeats."""
        self._require_scope()
        rows = self.company(cik)
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in rows:
            key = (
                row["concept"],
                row.get("unit") or "",
                row.get("currency") or "",
                "consolidated",
                _period_kind(row),
                row.get("period_start") or "",
                row.get("period_end") or "",
                row.get("fiscal_year"),
                row.get("fiscal_period") or "",
            )
            grouped.setdefault(key, []).append(row)
        findings: list[dict[str, Any]] = []
        repeated: list[dict[str, Any]] = []
        taxonomy_changes: list[dict[str, Any]] = []
        for key, items in sorted(grouped.items(), key=lambda item: tuple(str(part) for part in item[0])):
            concept, unit, currency, scope, period_kind, period_start, period_end, _, _ = key
            items.sort(key=lambda row: (row["availability_time"] or "", row["ingest_seq"],
                                        row["accession_number"] or ""))
            values = sorted({row["value_numeric"] for row in items})
            accessions = sorted({row["accession_number"] for row in items if row["accession_number"]})
            amended = any(str(row["form_type"] or "").upper().endswith("/A") for row in items)
            source_concepts = {str(row.get("source_concept") or "") for row in items}
            identity = {
                "concept": concept, "unit": unit, "currency": currency, "scope": scope,
                "period_kind": period_kind, "period_start": period_start or None,
                "period_end": period_end or None,
            }
            if len(values) > 1:
                findings.append({
                    **identity,
                    "category": "amendment_revision" if amended else "value_revision",
                    "accessions": accessions,
                    "values": values,
                    "amended": amended,
                    "forms": sorted({str(row["form_type"] or "") for row in items}),
                    "observations": len(items),
                    "first_available": items[0]["availability_time"],
                    "last_available": items[-1]["availability_time"],
                })
            elif len(accessions) > 1 and len({row["value_numeric"] for row in items}) == 1:
                repeated.append({**identity, "accessions": accessions, "value": values[0],
                                 "observations": len(items)})
            if len(source_concepts) > 1 and len(values) == 1:
                taxonomy_changes.append({**identity, "source_concepts": sorted(source_concepts),
                                         "value": values[0]})
        return {
            "cik": normalize_cik(cik),
            "findings": findings,
            "repeated_comparatives": repeated,
            "taxonomy_changes": taxonomy_changes,
            "identity_policy": "concept+unit+currency+scope+duration+period+fiscal_period",
            "summary": {
                "revisions": len(findings),
                "repeated_comparatives": len(repeated),
                "taxonomy_changes": len(taxonomy_changes),
            },
        }

# ------------------------------------------------------------- materialisation
    def materialize(self, cik: str, atlas_db: str | Path, *, snapshot_id: str | None = None,
                    continue_on_error: bool = True, batch_size: int = 500) -> dict[str, Any]:
        """Import one company into the SQLite kernel from the exact archived bytes.

        This is the hybrid path: the archive answers the question, and only the company
        the researcher asked about is materialised, transactionally, in the kernel.
        """
        from ..entities.master import SecurityMaster  # noqa: PLC0415
        from ..evidence.kernel import EvidenceKernel  # noqa: PLC0415
        from ..storage.db import open_database  # noqa: PLC0415
        from ..storage.sources import SEC_EDGAR, SourceRegistry, ensure_default_sources  # noqa: PLC0415

        started = time.monotonic()
        extracted = extract_member(self.root, cik)
        payload = json.loads(extracted["content"])
        normalized = normalize_cik(cik)
        db = open_database(atlas_db)
        try:
            ensure_default_sources(db)
            SourceRegistry(db).ensure(SEC_EDGAR)
            master = SecurityMaster(db)
            issuer_id = master.register_issuer(
                legal_name=str(payload.get("entityName") or f"CIK {normalized}"),
                cik=normalized, source_id=SEC_EDGAR.source_id)
            parsed = parse_companyfacts(
                payload, issuer_id=issuer_id, source_id=SEC_EDGAR.source_id,
                source_url=(f"https://www.sec.gov/Archives/edgar/daily-index/xbrl/"
                            f"companyfacts.zip#member={extracted['member']}&cik={normalized}"
                            f"&zip_sha256={extracted['sha256']}"
                            f"&snapshot={snapshot_id or self.manifest['snapshot_id']}"),
                observed_at=(self.manifest.get("archive") or {}).get("retrieved_at"),
            )
            summary = EvidenceKernel(db).ingest_many(
                parsed.records, continue_on_error=continue_on_error, batch_size=batch_size)
            return {
                "cik": normalized,
                "source_member": extracted["member"],
                "source_sha256": extracted["sha256"],
                "records": len(parsed.records),
                "inserted": summary.inserted,
                "duplicates": summary.duplicates,
                "superseding": summary.superseding,
                "rejected": summary.rejected,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "database": str(atlas_db),
            }
        finally:
            db.close()

    # ------------------------------------------------------------------ integrity
    def verify_sources(self, sample: int | None = None) -> dict[str, Any]:
        """Reconstruct archived members and compare them with the recorded hashes."""
        entries = self.manifest["member_index"]
        if sample is not None:
            entries = entries[:: max(1, len(entries) // sample)][:sample]
        checked = []
        problems = []
        for entry in entries:
            outcome = extract_member(self.root, entry["cik"])
            ok = outcome["sha256"] == entry["sha256"]
            checked.append({"member": entry["member"], "ok": ok})
            if not ok:
                problems.append(entry["member"])
        return {"checked": len(checked), "ok": not problems, "problems": problems}


def totals(root: str | Path) -> dict[str, Any]:
    """Stored bytes, split into the authoritative archive and derived columns."""
    manifest = load_manifest(root)
    parquet = sum(path.stat().st_size for path in (Path(root) / "evidence").rglob("*.parquet"))
    manifest_bytes = (Path(root) / "manifest.json").stat().st_size
    return {
        "archive_bytes": int(manifest["archive"]["bytes"]),
        "parquet_bytes": parquet,
        "manifest_bytes": manifest_bytes,
        "derived_bytes": parquet + manifest_bytes,
        "records": int(manifest["records"]),
        "companies": int(manifest["companies"]),
        "files": len(list((Path(root) / "evidence").rglob("*.parquet"))),
    }
