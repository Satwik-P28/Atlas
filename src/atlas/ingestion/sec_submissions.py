"""SEC submissions (filing metadata) parsing.

``submissions`` is the authoritative Phase 1 source for **when information became
public**: each recent filing carries ``acceptanceDateTime``. That timestamp upgrades
fact availability from date-precision to exact-precision, which is what makes
intraday point-in-time queries meaningful.

The API splits history across ``filings.recent`` (parallel arrays) and additional
per-company files listed in ``filings.files``. Phase 1 ingests ``recent`` and reports
the additional files it did not fetch, instead of pretending the filing list is
complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..core.errors import ParseError
from ..core.ids import filing_id as make_filing_id
from ..core.temporal import iso, iso_date, parse_iso, utcnow
from ..core.ids import normalize_cik
from ..storage.db import Database

#: Form types whose acceptance timestamps matter most for point-in-time research.
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F", "8-K", "6-K", "S-1", "DEF 14A"})


@dataclass(slots=True)
class FilingInfo:
    accession_number: str
    cik: str
    form_type: str
    filed_date: str
    acceptance_datetime: str | None = None
    period_of_report: str | None = None
    primary_document: str | None = None
    is_amendment: bool = False
    is_xbrl: bool = False
    is_inline_xbrl: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "accession_number": self.accession_number,
            "cik": self.cik,
            "form_type": self.form_type,
            "filed_date": self.filed_date,
            "acceptance_datetime": self.acceptance_datetime,
            "period_of_report": self.period_of_report,
            "primary_document": self.primary_document,
            "is_amendment": self.is_amendment,
            "is_xbrl": self.is_xbrl,
            "is_inline_xbrl": self.is_inline_xbrl,
        }


def filing_from_record(
    record: Mapping[str, Any],
    *,
    cik: str,
    issues: list[dict[str, Any]] | None = None,
) -> FilingInfo | None:
    """Build a :class:`FilingInfo` from one record in any SEC submissions shape.

    The ``recent`` block uses parallel arrays and history archives use (most often) a
    flat map of parallel arrays at the top level, so both callers normalise to a single
    mapping before reaching this function. A record without an accession or filing date
    cannot be placed in time and is reported rather than guessed.
    """
    accession = record.get("accessionNumber") or record.get("accession_number")
    if not accession:
        return None
    filed = record.get("filingDate") or record.get("filing_date")
    if not filed:
        if issues is not None:
            issues.append(
                {"code": "filing_without_filing_date", "severity": "warning", "accession": str(accession)}
            )
        return None
    acceptance_iso = None
    acceptance = record.get("acceptanceDateTime") or record.get("acceptance_datetime")
    if acceptance:
        try:
            acceptance_iso = iso(parse_iso(str(acceptance)))
        except Exception:  # noqa: BLE001 - missing precision is reported, not invented
            if issues is not None:
                issues.append(
                    {
                        "code": "unparsable_acceptance_datetime",
                        "severity": "warning",
                        "accession": str(accession),
                        "value": str(acceptance),
                    }
                )
    form = str(record.get("form") or "")
    report_date = record.get("reportDate") or record.get("report_date")
    return FilingInfo(
        accession_number=str(accession),
        cik=cik,
        form_type=form,
        filed_date=iso_date(filed),
        acceptance_datetime=acceptance_iso,
        period_of_report=iso_date(report_date) if report_date else None,
        primary_document=(record.get("primaryDocument") or record.get("primary_document")),
        is_amendment=form.strip().upper().endswith("/A"),
        is_xbrl=bool(record.get("isXBRL")) if record.get("isXBRL") is not None else False,
        is_inline_xbrl=bool(record.get("isInlineXBRL")) if record.get("isInlineXBRL") is not None else False,
    )


@dataclass(slots=True)
class SubmissionsResult:
    cik: str
    legal_name: str
    filings: list[FilingInfo] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    exchanges: list[str] = field(default_factory=list)
    sic: str | None = None
    sic_description: str | None = None
    fiscal_year_end: str | None = None
    entity_type: str | None = None
    former_names: list[dict[str, str]] = field(default_factory=list)
    additional_files: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def filing_index(self) -> dict[str, FilingInfo]:
        return {filing.accession_number: filing for filing in self.filings}

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "legal_name": self.legal_name,
            "tickers": self.tickers,
            "exchanges": self.exchanges,
            "sic": self.sic,
            "sic_description": self.sic_description,
            "fiscal_year_end": self.fiscal_year_end,
            "entity_type": self.entity_type,
            "filings": len(self.filings),
            "additional_files_not_fetched": self.additional_files,
            "issues": self.issues,
        }


def parse_submissions(payload: Mapping[str, Any]) -> SubmissionsResult:
    """Parse a ``submissions`` payload into issuer metadata and filing rows."""
    cik_raw = payload.get("cik")
    if cik_raw is None:
        raise ParseError("submissions payload has no cik")
    cik = normalize_cik(cik_raw)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ParseError("submissions payload has no entity name", cik=cik)

    result = SubmissionsResult(
        cik=cik,
        legal_name=name,
        tickers=[str(t) for t in (payload.get("tickers") or []) if t],
        exchanges=[str(e) for e in (payload.get("exchanges") or []) if e],
        sic=str(payload.get("sic")) if payload.get("sic") else None,
        sic_description=payload.get("sicDescription"),
        fiscal_year_end=payload.get("fiscalYearEnd"),
        entity_type=payload.get("entityType"),
        former_names=[
            {"name": str(item.get("name")), "from": str(item.get("from")), "to": str(item.get("to"))}
            for item in (payload.get("formerNames") or [])
            if item.get("name")
        ],
    )

    filings = payload.get("filings") or {}
    recent = filings.get("recent") or {}
    accessions = recent.get("accessionNumber") or []
    for index, accession in enumerate(accessions):
        if not accession:
            continue
        record = {
            key: (values[index] if isinstance(values, list) and index < len(values) else None)
            for key, values in recent.items()
        }
        filing = filing_from_record(record, cik=cik, issues=result.issues)
        if filing is not None:
            result.filings.append(filing)

    for entry in filings.get("files") or []:
        result.additional_files.append(
            {
                "name": entry.get("name"),
                "filing_count": entry.get("filingCount"),
                "filing_from": entry.get("filingFrom"),
                "filing_to": entry.get("filingTo"),
                "note": (
                    "history archive; fetched by 'atlas sec sync' (and reported as missing when "
                    "it has not been ingested), never assumed to be present"
                ),
            }
        )
    return result


class FilingRepository:
    """Persistence for filing metadata."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_many(
        self,
        filings: Sequence[FilingInfo],
        *,
        issuer_id: str | None,
        source_id: str,
        doc_id: str | None = None,
    ) -> int:
        written = 0
        for filing in filings:
            identifier = make_filing_id(filing.accession_number)
            self.db.execute(
                "INSERT INTO filing (filing_id, issuer_id, cik, accession_number, form_type, filed_date, "
                "acceptance_datetime, period_of_report, primary_document, is_amendment, amends_accession, "
                "is_xbrl, is_inline_xbrl, doc_id, source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(accession_number) DO UPDATE SET form_type=excluded.form_type, "
                "filed_date=excluded.filed_date, acceptance_datetime=excluded.acceptance_datetime, "
                "period_of_report=excluded.period_of_report, primary_document=excluded.primary_document, "
                "is_amendment=excluded.is_amendment, issuer_id=COALESCE(excluded.issuer_id, filing.issuer_id), "
                "doc_id=COALESCE(excluded.doc_id, filing.doc_id)",
                (
                    identifier,
                    issuer_id,
                    filing.cik,
                    filing.accession_number,
                    filing.form_type,
                    filing.filed_date,
                    filing.acceptance_datetime,
                    filing.period_of_report,
                    filing.primary_document,
                    int(filing.is_amendment),
                    None,
                    int(filing.is_xbrl),
                    int(filing.is_inline_xbrl),
                    doc_id,
                    source_id,
                ),
            )
            written += 1
        return written

    def get(self, accession_number: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM filing WHERE accession_number = ?", (accession_number,))
        return {k: row[k] for k in row.keys()} if row is not None else None

    def for_cik(self, cik: str, *, form_types: Sequence[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM filing WHERE cik = ?"
        params: list[Any] = [normalize_cik(cik)]
        if form_types:
            sql += f" AND form_type IN ({', '.join('?' for _ in form_types)})"
            params.extend(form_types)
        sql += " ORDER BY filed_date DESC, accession_number DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [{k: row[k] for k in row.keys()} for row in self.db.query(sql, params)]

    def filing_index(self, cik: str) -> dict[str, FilingInfo]:
        """Filing metadata for a CIK as ``FilingInfo``, for availability resolution.

        Reading the index from storage rather than from one payload matters for
        incremental sync: archives skipped as unchanged in a later run must still
        contribute their acceptance timestamps, otherwise availability would silently
        regress from ``exact`` to ``date`` precision.
        """
        rows = self.db.query(
            "SELECT accession_number, cik, form_type, filed_date, acceptance_datetime, period_of_report, "
            "primary_document, is_amendment, is_xbrl, is_inline_xbrl FROM filing WHERE cik = ?",
            (normalize_cik(cik),),
        )
        return {
            row["accession_number"]: FilingInfo(
                accession_number=row["accession_number"],
                cik=row["cik"],
                form_type=row["form_type"],
                filed_date=row["filed_date"],
                acceptance_datetime=row["acceptance_datetime"],
                period_of_report=row["period_of_report"],
                primary_document=row["primary_document"],
                is_amendment=bool(row["is_amendment"]),
                is_xbrl=bool(row["is_xbrl"]),
                is_inline_xbrl=bool(row["is_inline_xbrl"]),
            )
            for row in rows
        }

    def amendments(self, cik: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM filing WHERE cik = ? AND is_amendment = 1 ORDER BY filed_date", (normalize_cik(cik),)
        )
        return [{k: row[k] for k in row.keys()} for row in rows]
