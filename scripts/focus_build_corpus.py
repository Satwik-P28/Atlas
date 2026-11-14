"""Build a minimal FOCUS demo corpus from real SEC EDGAR 10-K filings.

Fetches only the Coca-Cola, JPMorgan and 3M accessions used by the Priority 0 case studies.
No FinanceBench rows and no synthetic flagship filings.

Requires ``ATLAS_SEC_USER_AGENT`` (declared identity with contact).
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
    KnowledgeEngine,
    absolute_document_url,
    fetch_sec_document,
    sec_filings,
)
from atlas.storage.db import Database  # noqa: E402

# Exact accessions previously ingested for the 9.6.4 case studies (see corpus manifest).
FOCUS_FILINGS = (
    {
        "label": "Coca-Cola FY2022 10-K",
        "cik": "0000021344",
        "legal_name": "COCA COLA CO",
        "accession": "0000021344-23-000011",
        "period_of_report": "2022-12-31",
    },
    {
        "label": "JPMorgan FY2022 10-K",
        "cik": "0000019617",
        "legal_name": "JPMORGAN CHASE & CO",
        "accession": "0000019617-23-000231",
        "period_of_report": "2022-12-31",
    },
    {
        "label": "3M FY2022 10-K",
        "cik": "0000066740",
        "legal_name": "3M CO",
        "accession": "0000066740-23-000014",
        "period_of_report": "2022-12-31",
    },
    {
        "label": "3M FY2018 10-K (historical ambiguity case)",
        "cik": "0000066740",
        "legal_name": "3M CO",
        "accession": "0001558370-19-000470",
        "period_of_report": "2018-12-31",
    },
)


def _primary_document(cik: str, accession: str) -> dict:
    # Use the full submissions archive (not only ``recent``) so FY2022 filings remain findable.
    for filing in sec_filings(cik, forms=["10-K", "10-K/A"]):
        if filing["accession"] == accession:
            return filing
    raise SystemExit(f"accession not found in SEC submissions archive: {accession}")


def _ensure_issuer(db: Database, cik: str, legal_name: str) -> str:
    existing = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
    if existing:
        return existing["issuer_id"]
    issuer_id = f"ISS-CIK{cik}"
    now = iso(utcnow())
    db.execute(
        "INSERT INTO issuer (issuer_id,cik,legal_name,entity_type,is_active,"
        "provenance_source,created_at,updated_at) VALUES (?,?,?,'company',1,'sec',?,?)",
        (issuer_id, cik, legal_name, now, now),
    )
    return issuer_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="var/focus_demo.db")
    parser.add_argument("--manifest", default="artifacts/focus_corpus_manifest.json")
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    database = Database(str(db_path))
    database.migrate()
    if database.query_one("SELECT 1 FROM source WHERE source_id='sec-edgar'") is None:
        database.execute(
            "INSERT INTO source (source_id,name,kind,homepage,licence,redistribution,notes,created_at)"
            " VALUES ('sec-edgar','SEC EDGAR','sec_edgar','https://www.sec.gov','US public record',"
            "'public_domain','primary documents only',?)", (iso(utcnow()),),
        )
    engine = KnowledgeEngine(database)

    records = []
    for filing in FOCUS_FILINGS:
        meta = _primary_document(filing["cik"], filing["accession"])
        issuer_id = _ensure_issuer(database, filing["cik"], filing["legal_name"])
        started = time.time()
        html = fetch_sec_document(filing["cik"], filing["accession"], meta["primary_document"])
        document = engine.ingest_document(
            issuer_id=issuer_id,
            accession=filing["accession"],
            form_type="10-K",
            html=html,
            filed_date=meta["filed_date"],
            acceptance_time=meta["acceptance_time"],
            period_of_report=meta.get("period_of_report") or filing["period_of_report"],
            rights="public_domain",
            primary_document_url=absolute_document_url(
                filing["cik"], filing["accession"], meta["primary_document"]),
        )
        elapsed = round(time.time() - started, 2)
        records.append({
            **filing,
            "issuer_id": issuer_id,
            "document_id": document["document_id"],
            "filed_date": meta["filed_date"],
            "acceptance_time": meta["acceptance_time"],
            "primary_document": meta["primary_document"],
            "bytes": document["byte_size"],
            "units": document["unit_count"],
            "tables": document["table_count"],
            "availability_time": document["availability_time"],
            "seconds": elapsed,
            "status": "ingested",
        })
        print(f"ingested {filing['label']} → {document['document_id']} ({elapsed}s)")

    payload = {
        "schema": "atlas.focus.corpus.v1",
        "database": str(db_path),
        "filings": records,
        "rights": "SEC EDGAR public filings fetched at build time; not redistributed in git",
        "limitations": [
            "Corpus is a FOCUS demo subset, not the full FinanceBench evaluation population.",
            "Rebuild requires network access to data.sec.gov / www.sec.gov and ATLAS_SEC_USER_AGENT.",
        ],
    }
    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"database": str(db_path), "filings": len(records), "manifest": str(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
