"""Phase 9.5 ingestion driver: SEC filings → Financial Knowledge Engine.

Usage:
    python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000320193 --forms 10-K,10-Q --limit 2

The driver is deliberately thin: discovery comes from the SEC submissions API, bytes come
from the primary document URL, and all storage/validation lives in
``atlas.research.knowledge.KnowledgeEngine``. It never writes a passage that was not in
the retrieved document.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.knowledge import (  # noqa: E402
    KnowledgeEngine, absolute_document_url, fetch_sec_document, sec_filing_index,
)
from atlas.storage.db import Database  # noqa: E402

SOURCE_ID = "sec-edgar"


def ensure_source(db: Database) -> None:
    if db.query_one("SELECT 1 FROM source WHERE source_id = ?", (SOURCE_ID,)):
        return
    db.execute(
        "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (SOURCE_ID, "SEC EDGAR", "sec_edgar", "https://www.sec.gov",
         "US public record (SEC filing); exhibits may carry third-party rights",
         "public_domain",
         "Primary filings retrieved from EDGAR. Only primary documents are archived; exhibits are not.",
         iso(utcnow())),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument("--cik", required=True)
    parser.add_argument("--forms", default="10-K,10-Q")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = Database(args.db)
    db.migrate()
    ensure_source(db)
    issuer = db.query_one("SELECT issuer_id, legal_name FROM issuer WHERE cik = ?",
                          (str(args.cik).lstrip("0").zfill(10),))
    if issuer is None:
        issuer = db.query_one("SELECT issuer_id, legal_name FROM issuer WHERE cik = ?", (args.cik,))
    if issuer is None:
        print(json.dumps({"error": "issuer not found for cik", "cik": args.cik}))
        return 2
    engine = KnowledgeEngine(db)
    forms = [form.strip().upper() for form in args.forms.split(",") if form.strip()]
    filings = sec_filing_index(args.cik, forms, limit=args.limit * len(forms))
    report: dict[str, object] = {
        "issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"], "forms": forms,
        "dry_run": args.dry_run, "documents": [], "skipped": [],
    }
    for filing in filings[: args.limit * len(forms)]:
        accession = filing["accession"]
        existing = db.query_one("SELECT document_id FROM knowledge_document WHERE accession = ?",
                                (accession,))
        if existing:
            report["skipped"].append({"accession": accession, "reason": "already_ingested"})
            continue
        if args.dry_run:
            report["documents"].append({**filing, "status": "would_ingest"})
            continue
        started = time.perf_counter()
        try:
            html = fetch_sec_document(args.cik, accession, filing["primary_document"])
            amends = None
            if filing["is_amendment"]:
                prior = db.query_one(
                    "SELECT accession FROM knowledge_document WHERE issuer_id = ? "
                    "AND is_amendment = 0 ORDER BY availability_time DESC LIMIT 1",
                    (issuer["issuer_id"],),
                )
                amends = prior["accession"] if prior else None
            document = engine.ingest_document(
                issuer_id=issuer["issuer_id"], accession=accession, form_type=filing["form_type"],
                html=html, filed_date=filing["filed_date"],
                acceptance_time=filing.get("acceptance_time"),
                period_of_report=filing.get("period_of_report"),
                primary_document_url=absolute_document_url(
                    args.cik, accession, filing["primary_document"]),
                amends_accession=amends,
            )
            report["documents"].append({
                "accession": accession, "form_type": filing["form_type"],
                "document_id": document["document_id"], "units": document["unit_count"],
                "tables": document["table_count"], "sections": document["section_count"],
                "bytes": document["byte_size"], "availability_time": document["availability_time"],
                "availability_precision": document["availability_precision"],
                "seconds": round(time.perf_counter() - started, 2),
            })
        except Exception as exc:  # noqa: BLE001 - the driver reports, the engine validates
            report["documents"].append({"accession": accession, "status": "failed",
                                        "error": f"{type(exc).__name__}: {exc}"})
    report["engine_stats"] = engine.stats()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
