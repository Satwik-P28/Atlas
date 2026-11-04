"""SEC ingestion orchestration.

The connector fetches, the parsers interpret, the kernel stores. Nothing here reads
values back out of the database to build new evidence: the pipeline is
``payload -> parsed records -> kernel``, one direction only, so a re-run is
deterministic and idempotent.

Order matters and is deliberate:

1. ``submissions`` first, because it supplies issuer metadata **and** the acceptance
   timestamps that give facts exact-precision availability.
2. ``companyfacts`` second, parsed with the filing index in hand.
3. Identity: tickers listed on the submissions cover page are attached to the issuer
   as provisional securities. SEC submissions do not map tickers to share classes, so
   multi-ticker issuers are recorded with low confidence rather than guessed.

Re-running sync is safe: filings upsert on accession number, evidence dedupes on
content hash, and a changed value becomes a new superseding record instead of
overwriting the original.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.errors import ParseError
from ..core.ids import normalize_cik
from ..core.temporal import iso, utcnow
from ..entities.master import STATUS_CONFIRMED, STATUS_PROBABLE, STATUS_UNVERIFIED, SecurityMaster
from ..evidence.kernel import EvidenceKernel, IngestSummary
from ..storage.db import Database
from ..storage.sources import SEC_EDGAR, SourceRegistry, store_raw_document
from .sec_client import SecClient
from .sec_companyfacts import SEC_COMPANYFACTS_URL, CompanyFactsResult, parse_companyfacts
from .sec_history import (
    HistoryDocument,
    SubmissionsHistoryStore,
    document_hash,
    load_fixture_history,
    parse_history_payload,
)
from .sec_submissions import FilingInfo, FilingRepository, SubmissionsResult, parse_submissions

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
#: Archive documents listed in ``filings.files[].name`` (older filing history).
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"

#: Venue inference from the exchange code on the submissions cover page. Kept tiny and
#: explicit: an unknown exchange is recorded as unknown, never assumed to be Nasdaq.
EXCHANGE_MIC_MAP: dict[str, str] = {
    "NYSE": "XNYS",
    "NASDAQ": "XNAS",
    "NYSE AMERICAN": "XASE",
    "NYSEARCA": "ARCX",
    "BATS": "BATS",
}


@dataclass(slots=True)
class SyncReport:
    cik: str
    issuer_id: str | None = None
    legal_name: str | None = None
    submissions: dict[str, Any] = field(default_factory=dict)
    companyfacts: dict[str, Any] = field(default_factory=dict)
    filings_written: int = 0
    history: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    securities: list[dict[str, Any]] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str | None = None
    source: str = SEC_EDGAR.source_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "issuer_id": self.issuer_id,
            "legal_name": self.legal_name,
            "source": self.source,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "filings_written": self.filings_written,
            "history": self.history,
            "documents": self.documents,
            "submissions": self.submissions,
            "companyfacts": self.companyfacts,
            "evidence": self.evidence,
            "securities": self.securities,
            "issues": self.issues,
        }


class SecIngestor:
    """Synchronise one registrant's SEC history into Atlas."""

    def __init__(
        self,
        db: Database,
        *,
        client: SecClient | None = None,
        kernel: EvidenceKernel | None = None,
        master: SecurityMaster | None = None,
    ) -> None:
        self.db = db
        self.sources = SourceRegistry(db)
        self.kernel = kernel or EvidenceKernel(db)
        self.master = master or SecurityMaster(db)
        self.client = client
        self.filings = FilingRepository(db)
        self.history = SubmissionsHistoryStore(db)

    # ------------------------------------------------------------------ public
    def sync(
        self,
        cik: str | int,
        *,
        fetch_history: bool = True,
        history_limit: int | None = None,
        observed_at: Any | None = None,
    ) -> SyncReport:
        """Fetch and ingest a company from live SEC endpoints.

        ``fetch_history`` follows every archive listed in ``filings.files`` so the filing
        list is complete rather than merely recent; without it, facts whose accession is
        older than ``recent`` keep date-precision availability. A failure on one archive
        is recorded as an issue and marks coverage incomplete instead of aborting the
        whole sync or pretending the history is whole.
        """
        normalized = normalize_cik(cik)
        if self.client is None:
            raise ParseError("no SEC client configured; pass a SecClient or use sync_payloads")
        report = SyncReport(cik=normalized, started_at=iso(utcnow()))

        submissions_url = SEC_SUBMISSIONS_URL.format(cik=normalized)
        submissions_payload, submissions_fetch = self.client.get_json(submissions_url)
        facts_url = SEC_COMPANYFACTS_URL.format(cik=normalized)
        facts_payload, facts_fetch = self.client.get_json(facts_url)

        documents: list[HistoryDocument] = []
        if fetch_history:
            described = ((submissions_payload.get("filings") or {}).get("files") or [])
            for entry in described:
                if history_limit is not None and len(documents) >= history_limit:
                    break
                name = entry.get("name")
                if not name:
                    continue
                url = SEC_SUBMISSIONS_FILE_URL.format(name=name)
                try:
                    payload, fetch = self.client.get_json(url)
                except Exception as exc:  # noqa: BLE001 - one archive failing must not lose the rest
                    report.issues.append(
                        {
                            "code": "history_archive_failed",
                            "severity": "warning",
                            "file": name,
                            "detail": str(exc),
                        }
                    )
                    continue
                documents.append(
                    HistoryDocument(
                        name=name,
                        payload=payload,
                        body=fetch.body,
                        doc_id=fetch.doc_id,
                        advertised=entry,
                        url=url,
                    )
                )

        return self.sync_payloads(
            normalized,
            submissions_payload=submissions_payload,
            companyfacts_payload=facts_payload,
            submissions_doc_id=submissions_fetch.doc_id,
            companyfacts_doc_id=facts_fetch.doc_id,
            submissions_url=submissions_url,
            companyfacts_url=facts_url,
            history_documents=documents,
            observed_at=observed_at,
            report=report,
        )

    def sync_payloads(
        self,
        cik: str | int,
        *,
        submissions_payload: Mapping[str, Any],
        companyfacts_payload: Mapping[str, Any],
        submissions_doc_id: str | None = None,
        companyfacts_doc_id: str | None = None,
        submissions_url: str | None = None,
        companyfacts_url: str | None = None,
        history_documents: Sequence[HistoryDocument] | None = None,
        observed_at: Any | None = None,
        report: SyncReport | None = None,
    ) -> SyncReport:
        """Ingest already-fetched payloads (the offline/fixture path)."""
        normalized = normalize_cik(cik)
        self.sources.ensure(SEC_EDGAR)
        report = report or SyncReport(cik=normalized, started_at=iso(utcnow()))
        report.source = SEC_EDGAR.source_id

        submissions: SubmissionsResult = parse_submissions(submissions_payload)
        report.legal_name = submissions.legal_name

        issuer_id = self.master.register_issuer(
            legal_name=submissions.legal_name,
            cik=submissions.cik,
            entity_type=submissions.entity_type or "corporation",
            sic=submissions.sic,
            fiscal_year_end=submissions.fiscal_year_end,
            source_id=SEC_EDGAR.source_id,
        )
        report.issuer_id = issuer_id
        report.filings_written = self.filings.upsert_many(
            submissions.filings, issuer_id=issuer_id, source_id=SEC_EDGAR.source_id, doc_id=submissions_doc_id
        )
        if submissions_doc_id:
            report.documents.append(submissions_doc_id)
        report.issues.extend(submissions.issues)
        report.securities = self._link_tickers(issuer_id, submissions)

        history_report = self._ingest_history(
            normalized, issuer_id, list(history_documents or ()), submissions
        )
        report.history = history_report
        report.filings_written += int(history_report.get("filings_written", 0))
        report.issues.extend(history_report.get("issues", []))

        facts_url = companyfacts_url or SEC_COMPANYFACTS_URL.format(cik=normalized)
        facts: CompanyFactsResult = parse_companyfacts(
            companyfacts_payload,
            issuer_id=issuer_id,
            source_id=SEC_EDGAR.source_id,
            source_url=facts_url,
            raw_doc_id=companyfacts_doc_id,
            # From storage, so archives skipped as unchanged still supply timestamps.
            filings=self.filings.filing_index(normalized),
            observed_at=observed_at,
        )
        if companyfacts_doc_id:
            report.documents.append(companyfacts_doc_id)

        with self.db.transaction():
            summary: IngestSummary = self.kernel.ingest_many(facts.records)
        report.evidence = summary.to_dict()
        report.submissions = submissions.to_dict()
        report.companyfacts = facts.to_dict()
        report.issues.extend(
            issue for issue in facts.issues if issue.get("severity") in {"error", "warning"}
        )
        report.finished_at = iso(utcnow())
        return report

    # ----------------------------------------------------------------- private
    def _ingest_history(
        self,
        cik: str,
        issuer_id: str,
        documents: list[HistoryDocument],
        submissions: SubmissionsResult,
    ) -> dict[str, Any]:
        """Ingest filing-history archives before facts depend on their timestamps."""
        written = 0
        skipped = 0
        parsed_rows = 0
        issues: list[dict[str, Any]] = []
        for document in documents:
            digest = document_hash(document)
            if self.history.is_current(cik, document.name, digest):
                skipped += 1
                continue
            parsed = parse_history_payload(
                document.payload, cik=cik, name=document.name, advertised=document.advertised
            )
            issues.extend(parsed.issues)
            parsed_rows += len(parsed.filings)
            written += self.filings.upsert_many(
                parsed.filings,
                issuer_id=issuer_id,
                source_id=SEC_EDGAR.source_id,
                doc_id=document.doc_id,
            )
            self.history.record_file(
                cik,
                document.name,
                content_hash=digest,
                doc_id=document.doc_id,
                advertised=document.advertised,
                filing_rows=len(parsed.filings),
            )

        coverage = self.history.coverage(cik, submissions.additional_files)
        if coverage.missing_files:
            issues.append(
                {
                    "code": "filing_history_incomplete",
                    "severity": "info",
                    "detail": (
                        f"{len(coverage.missing_files)} of {len(coverage.expected_files)} SEC filing "
                        "archive(s) are not ingested; facts from those filings keep date-precision "
                        "availability"
                    ),
                    "missing_files": coverage.missing_files,
                }
            )
        return {
            "files_expected": len(coverage.expected_files),
            "files_fetched": len(documents),
            "files_skipped_unchanged": skipped,
            "filings_written": written,
            "filings_parsed": parsed_rows,
            "coverage": coverage.to_dict(),
            "issues": issues,
        }

    def _link_tickers(self, issuer_id: str, submissions: SubmissionsResult) -> list[dict[str, Any]]:
        """Attach cover-page tickers to the issuer, honestly flagged.

        SEC submissions do not state which share class a ticker belongs to. With one
        ticker the inference "common stock" is reasonable but still an inference, so
        the assignment is stored with ``probable`` status. With several tickers Atlas
        cannot tell which is which, so each becomes a provisional security with
        ``unverified`` status and a note saying so.
        """
        if not submissions.tickers:
            return []
        results: list[dict[str, Any]] = []
        multi = len(submissions.tickers) > 1
        primary_exchange = submissions.exchanges[0] if submissions.exchanges else None
        mic = EXCHANGE_MIC_MAP.get((primary_exchange or "").upper())
        if mic is None and primary_exchange:
            results.append(
                {
                    "ticker": None,
                    "status": "unmapped_exchange",
                    "note": f"exchange {primary_exchange!r} has no MIC mapping; no listing created",
                }
            )
        for ticker, exchange in zip(submissions.tickers, submissions.exchanges or [None] * len(submissions.tickers)):
            venue = EXCHANGE_MIC_MAP.get((exchange or "").upper())
            if venue is None:
                continue
            self.master.ensure_venue(
                venue,
                {"XNYS": "New York Stock Exchange", "XNAS": "Nasdaq Global Select Market", "XASE": "NYSE American",
                 "ARCX": "NYSE Arca", "BATS": "Cboe BZX"}.get(venue, venue),
                country="US",
                timezone="America/New_York",
            )
            if multi:
                class_designation = f"unspecified class ({ticker})"
                status = STATUS_UNVERIFIED
                confidence = 0.3
                note = (
                    "SEC submissions lists multiple tickers but does not map them to share classes; "
                    "this provisional security requires a share-class source before it can be confirmed"
                )
            else:
                class_designation = "common stock"
                status = STATUS_PROBABLE
                confidence = 0.6
                note = "single ticker on the SEC cover page; share class inferred as common stock"
            security_id = self.master.ensure_security(
                issuer_id,
                class_designation=class_designation,
                security_type="common_stock",
                currency="USD",
                source_id=SEC_EDGAR.source_id,
                note=note,
            )
            listing_id = self.master.ensure_listing(
                security_id, venue, valid_from=None, currency="USD", is_primary=True, source_id=SEC_EDGAR.source_id
            )
            self.master.assign_ticker(
                listing_id,
                ticker,
                valid_from=None,
                confidence=confidence,
                status=status,
                source_id=SEC_EDGAR.source_id,
                evidence_note=note,
            )
            results.append(
                {
                    "security_id": security_id,
                    "listing_id": listing_id,
                    "ticker": ticker,
                    "mic": venue,
                    "status": status,
                    "confidence": confidence,
                    "note": note,
                }
            )
        return results


def load_fixture_payloads(directory: str | Path, cik: str | int) -> tuple[dict[str, Any], dict[str, Any], str | None, str | None]:
    """Load archived SEC payloads from a fixture directory.

    Expected files: ``companyfacts_CIK<digits>.json`` and ``submissions_CIK<digits>.json``
    (or unsuffixed ``companyfacts.json`` / ``submissions.json``). The raw bytes are
    registered as raw documents so offline runs have the same provenance shape as live
    runs.
    """
    import json

    normalized = normalize_cik(cik)
    base = Path(directory)
    if not base.exists():
        raise ParseError("fixture directory does not exist", directory=str(base))
    submissions_path = _locate(base, "submissions", normalized)
    facts_path = _locate(base, "companyfacts", normalized)
    submissions_bytes = submissions_path.read_bytes()
    facts_bytes = facts_path.read_bytes()
    try:
        submissions_payload = json.loads(submissions_bytes)
        facts_payload = json.loads(facts_bytes)
    except json.JSONDecodeError as exc:
        raise ParseError("fixture payload is not valid JSON", error=str(exc)) from exc
    return submissions_payload, facts_payload, None, None


def _locate(base: Path, stem: str, cik: str) -> Path:
    candidates = [
        base / f"{stem}_CIK{cik}.json",
        base / f"{stem}.json",
        base / stem / f"CIK{cik}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ParseError("fixture file not found", stem=stem, cik=cik, searched=[str(c) for c in candidates])


def register_fixture_documents(
    db: Database, directory: str | Path, cik: str | int
) -> tuple[str | None, str | None]:
    """Store fixture payload bytes as raw documents for provenance."""
    normalized = normalize_cik(cik)
    base = Path(directory)
    source_id = SourceRegistry(db).ensure(SEC_EDGAR)
    submissions_doc = store_raw_document(
        db,
        source_id=source_id,
        url=f"fixture://{normalized}/submissions.json",
        body=_locate(base, "submissions", normalized).read_bytes(),
        media_type="application/json",
    )
    facts_doc = store_raw_document(
        db,
        source_id=source_id,
        url=f"fixture://{normalized}/companyfacts.json",
        body=_locate(base, "companyfacts", normalized).read_bytes(),
        media_type="application/json",
    )
    return submissions_doc, facts_doc
