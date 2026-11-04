"""SEC submissions history archives.

``submissions`` splits a registrant's filing history in two:

* ``filings.recent`` — the most recent ~1,000 filings, delivered as **parallel arrays**
  inside the main payload;
* ``filings.files[]`` — a list of archive descriptors (``name``, ``filingCount``,
  ``filingFrom``, ``filingTo``) whose documents hold everything older. Apple's payload
  lists two archives covering 1994-01-26 .. 2015-10-03.

Ingesting only ``recent`` is therefore an incomplete filing history, and that has a
direct correctness consequence: a fact whose accession is missing from the filing index
falls back to date-precision availability instead of the exact SEC acceptance
timestamp. Fetching the archives converts those to exact precision.

**The archive layout is not the same as ``recent``.** Measured against the live files
(CIK 0000789019, 0000104169, 0001652044, 0000320193), an archive document is a flat map
of **parallel arrays at the top level** — ``{"accessionNumber": [...], "filingDate":
[...], ...}`` — with no ``filings`` wrapper. Some older tooling and derivatives emit a
``filings`` wrapper holding a **list of objects** instead. Both shapes are parsed here,
and the detected shape is reported rather than assumed.

Sync is incremental by content hash: the archive bodies are stored as raw documents, and
an archive whose bytes are unchanged is not re-parsed. Filings upsert on accession
number, so re-parsing is idempotent anyway; skipping is an optimisation whose safety
comes from the hash, not from trusting the upstream file name.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.errors import ParseError
from ..core.ids import normalize_cik
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from .sec_submissions import FilingInfo, filing_from_record

ARCHIVE_FORMAT_PARALLEL = "parallel_arrays"
ARCHIVE_FORMAT_OBJECT_LIST = "object_list"


@dataclass(slots=True)
class HistoryDocument:
    """One archive payload plus the provenance needed to store it."""

    name: str
    payload: Any
    body: bytes | None = None
    doc_id: str | None = None
    advertised: Mapping[str, Any] | None = None
    url: str | None = None


@dataclass(slots=True)
class HistoryFileResult:
    name: str
    filings: list[FilingInfo] = field(default_factory=list)
    layout: str = ARCHIVE_FORMAT_PARALLEL
    advertised_count: int | None = None
    advertised_from: str | None = None
    advertised_to: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    duplicates_in_file: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layout": self.layout,
            "filings": len(self.filings),
            "advertised_count": self.advertised_count,
            "advertised_from": self.advertised_from,
            "advertised_to": self.advertised_to,
            "duplicates_in_file": self.duplicates_in_file,
            "issues": self.issues,
        }


def _records_from_payload(payload: Any) -> tuple[list[Mapping[str, Any]], str]:
    """Normalise an archive payload into records with ``recent``-style field names."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)], ARCHIVE_FORMAT_OBJECT_LIST
    if not isinstance(payload, Mapping):
        raise ParseError(
            "submissions history payload is neither an object nor a list",
            payload_type=type(payload).__name__,
        )

    node: Any = payload.get("filings", payload)
    if isinstance(node, list):
        return [item for item in node if isinstance(item, Mapping)], ARCHIVE_FORMAT_OBJECT_LIST
    if isinstance(node, Mapping):
        accessions = node.get("accessionNumber")
        if accessions is None:
            raise ParseError(
                "submissions history payload has no accession array",
                keys=sorted(str(k) for k in list(node)[:20]),
            )
        if not isinstance(accessions, list):
            raise ParseError("submissions history accession field is not an array")
        records: list[Mapping[str, Any]] = []
        for index in range(len(accessions)):
            record: dict[str, Any] = {}
            for key, values in node.items():
                if isinstance(values, list) and index < len(values):
                    record[str(key)] = values[index]
            records.append(record)
        return records, ARCHIVE_FORMAT_PARALLEL
    raise ParseError("unrecognised submissions history layout", keys=sorted(str(k) for k in payload))


def parse_history_payload(
    payload: Any,
    *,
    cik: str | int,
    name: str | None = None,
    advertised: Mapping[str, Any] | None = None,
) -> HistoryFileResult:
    """Parse one history archive into :class:`FilingInfo` rows."""
    normalized = normalize_cik(cik)
    records, layout = _records_from_payload(payload)
    result = HistoryFileResult(
        name=name or "",
        layout=layout,
        advertised_count=_as_int((advertised or {}).get("filingCount")),
        advertised_from=(advertised or {}).get("filingFrom"),
        advertised_to=(advertised or {}).get("filingTo"),
    )
    seen: set[str] = set()
    for record in records:
        filing = filing_from_record(record, cik=normalized, issues=result.issues)
        if filing is None:
            continue
        if filing.accession_number in seen:
            result.duplicates_in_file += 1
            continue
        seen.add(filing.accession_number)
        result.filings.append(filing)
    if result.advertised_count is not None and len(result.filings) != result.advertised_count:
        # A mismatch is reported, never silently reconciled: the archive is either
        # truncated or the advertised count is stale, and both matter.
        result.issues.append(
            {
                "code": "history_count_mismatch",
                "severity": "warning",
                "file": result.name,
                "detail": (
                    f"archive advertised {result.advertised_count} filing(s) but parsed "
                    f"{len(result.filings)}"
                ),
            }
        )
    return result


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def document_hash(document: HistoryDocument) -> str:
    """Content hash used to make history sync incremental.

    The raw bytes are hashed when available. When a caller supplies an already-parsed
    payload (fixtures, tests), a canonical JSON encoding is hashed instead; that is a
    weaker identity but still detects content changes between runs.
    """
    if document.body is not None:
        return hashlib.sha256(document.body).hexdigest()
    canonical = json.dumps(document.payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class HistoryCoverage:
    cik: str
    expected_files: list[str]
    recorded_files: list[str]
    missing_files: list[str]
    advertised_filings: int
    recorded_rows: int
    complete: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "expected_files": self.expected_files,
            "recorded_files": self.recorded_files,
            "missing_files": self.missing_files,
            "advertised_filings": self.advertised_filings,
            "recorded_rows": self.recorded_rows,
            "complete": self.complete,
        }


class SubmissionsHistoryStore:
    """Checkpoint store for fetched submission archives."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def is_current(self, cik: str, name: str, content_hash: str) -> bool:
        row = self.db.query_one(
            "SELECT content_hash FROM submissions_file WHERE cik = ? AND name = ?",
            (normalize_cik(cik), name),
        )
        return row is not None and row["content_hash"] == content_hash

    def record_file(
        self,
        cik: str,
        name: str,
        *,
        content_hash: str,
        doc_id: str | None,
        advertised: Mapping[str, Any] | None,
        filing_rows: int,
    ) -> None:
        advertised = advertised or {}
        self.db.execute(
            "INSERT INTO submissions_file (cik, name, advertised_count, advertised_from, advertised_to, "
            "filing_rows, content_hash, doc_id, fetched_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(cik, name) DO UPDATE SET advertised_count=excluded.advertised_count, "
            "advertised_from=excluded.advertised_from, advertised_to=excluded.advertised_to, "
            "filing_rows=excluded.filing_rows, content_hash=excluded.content_hash, "
            "doc_id=COALESCE(excluded.doc_id, submissions_file.doc_id), fetched_at=excluded.fetched_at",
            (
                normalize_cik(cik),
                name,
                _as_int(advertised.get("filingCount")),
                advertised.get("filingFrom"),
                advertised.get("filingTo"),
                filing_rows,
                content_hash,
                doc_id,
                iso(utcnow()),
            ),
        )

    def coverage(self, cik: str, expected: Sequence[Mapping[str, Any]]) -> HistoryCoverage:
        normalized = normalize_cik(cik)
        rows = self.db.query(
            "SELECT name, filing_rows FROM submissions_file WHERE cik = ? ORDER BY name", (normalized,)
        )
        recorded = {row["name"]: int(row["filing_rows"] or 0) for row in rows}
        expected_names = [str(entry.get("name")) for entry in expected if entry.get("name")]
        missing = [name for name in expected_names if name not in recorded]
        advertised = sum(_as_int(entry.get("filingCount")) or 0 for entry in expected)
        # Vacuously complete when SEC advertises no archives: there is nothing to miss.
        complete = not missing and all(recorded.get(name, 0) > 0 for name in expected_names)
        return HistoryCoverage(
            cik=normalized,
            expected_files=expected_names,
            recorded_files=sorted(recorded),
            missing_files=missing,
            advertised_filings=advertised,
            recorded_rows=sum(recorded.values()),
            complete=complete,
        )

    def state(self, cik: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT name, advertised_count, advertised_from, advertised_to, filing_rows, content_hash, "
            "doc_id, fetched_at FROM submissions_file WHERE cik = ? ORDER BY name",
            (normalize_cik(cik),),
        )
        return [{key: row[key] for key in row.keys()} for row in rows]


def load_fixture_history(directory: str | Path, cik: str | int) -> list[HistoryDocument]:
    """Load archived history documents from ``<fixture>/history/*.json``.

    The advertised descriptor (filing count and covered range) is read from the main
    submissions fixture, so offline coverage reporting uses the same expectations as a
    live run.
    """
    normalized = normalize_cik(cik)
    base = Path(directory)
    history_dir = base / "history"
    if not history_dir.exists():
        return []
    submissions_path = _locate_submissions(base, normalized)
    submissions = json.loads(submissions_path.read_bytes())
    descriptors = {
        str(entry.get("name")): entry
        for entry in ((submissions.get("filings") or {}).get("files") or [])
        if entry.get("name")
    }
    documents: list[HistoryDocument] = []
    for path in sorted(history_dir.glob("*.json")):
        body = path.read_bytes()
        documents.append(
            HistoryDocument(
                name=path.name,
                payload=json.loads(body),
                body=body,
                advertised=descriptors.get(path.name),
                url=f"fixture://{normalized}/history/{path.name}",
            )
        )
    return documents


def _locate_submissions(base: Path, cik: str) -> Path:
    for candidate in (
        base / f"submissions_CIK{cik}.json",
        base / "submissions.json",
        base / "submissions" / f"CIK{cik}.json",
    ):
        if candidate.exists():
            return candidate
    raise ParseError("submissions fixture not found", cik=cik, directory=str(base))
