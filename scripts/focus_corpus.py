#!/usr/bin/env python
"""Build the FOCUS corpus from real SEC EDGAR 10-K filings.

This script is the only part of the FOCUS demonstration that needs the network. It fetches the
primary document bytes with the declared contact User-Agent that SEC fair-access policy requires,
ingests them, and archives the exact bytes to ``var/focus/snapshots/<accession>.html`` so that
later verification can authenticate the original source without the network.

The archived snapshot is what makes strict source verification possible: it is the document the
hashes were computed over. It is written under ``var/`` because it is a multi-megabyte copy of a
public record, not something a repository should carry.

    ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com' \
        python scripts/focus_corpus.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.knowledge import (  # noqa: E402
    KnowledgeEngine,
    absolute_document_url,
    sec_filings,
    sec_user_agent,
)
from atlas.storage.db import Database  # noqa: E402

DEFAULT_DB = ROOT / "var" / "phase9_6.db"
DEFAULT_SNAPSHOTS = ROOT / "var" / "focus" / "snapshots"

#: (SEC legal name, CIK, fiscal years of the 10-K to ingest)
PINNED: dict[str, tuple[str, tuple[int, ...]]] = {
    "COCA COLA CO": ("0000021344", (2022,)),
    "JPMORGAN CHASE & CO": ("0000019617", (2022,)),
    # FY2018 is ingested deliberately: the case set asks for 3M's 2018 revenue, and refusing it
    # because the document was never fetched would be a capability gap, not an unanswerable
    # question. Fetching it lets the case be judged on evidence.
    "3M CO": ("0000066740", (2022, 2018)),
}

MAX_BYTES = 40 * 1024 * 1024
_MIN_INTERVAL = 0.2  # SEC fair access: at most 10 requests per second
_last_request = [0.0]


def _throttle() -> None:
    elapsed = time.monotonic() - _last_request[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request[0] = time.monotonic()


def fetch_bytes(url: str) -> bytes:
    _throttle()
    request = Request(url, headers={"User-Agent": sec_user_agent(),
                                    "Accept-Encoding": "identity"})
    with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed sec.gov host
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise SystemExit(f"document exceeds the ingestion limit: {url}")
    return payload


def ensure_issuer(db: Database, cik: str, legal_name: str) -> str:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
    if row is not None:
        return row["issuer_id"]
    issuer_id = f"ISS-CIK{cik}"
    now = iso(utcnow())
    db.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active,"
        " provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'sec',?,?)",
        (issuer_id, cik, legal_name, now, now))
    return issuer_id


def select_filings(cik: str, years: tuple[int, ...]) -> list[dict[str, object]]:
    """One 10-K per requested fiscal year. An ambiguous year is reported, never guessed."""
    filings = sec_filings(cik, forms=["10-K"])
    chosen: list[dict[str, object]] = []
    for year in years:
        matches = [
            filing for filing in filings
            if str(filing.get("period_of_report") or "").startswith(str(year))
            and not str(filing.get("form_type", "")).endswith("/A")
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"CIK {cik} fiscal {year}: expected exactly one 10-K, found {len(matches)} "
                f"({[m['accession'] for m in matches][:6]})")
        chosen.append(matches[0])
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--snapshots", default=str(DEFAULT_SNAPSHOTS))
    parser.add_argument("--force", action="store_true",
                        help="discard the existing corpus database and re-ingest from SEC")
    parser.add_argument("--manifest", default=str(ROOT / "artifacts" / "focus_corpus.json"))
    args = parser.parse_args()

    user_agent = sec_user_agent()  # raises with a clear message when unset
    db_path = Path(args.db)
    if args.force and db_path.exists():
        db_path.unlink()
    snapshots = Path(args.snapshots)
    snapshots.mkdir(parents=True, exist_ok=True)

    db = Database(db_path)
    db.migrate()
    if db.query_one("SELECT 1 FROM source WHERE source_id='sec-edgar'") is None:
        db.execute(
            "INSERT INTO source (source_id,name,kind,homepage,licence,redistribution,notes,"
            "created_at) VALUES ('sec-edgar','SEC EDGAR','sec_edgar','https://www.sec.gov',"
            "'US public record','public_domain','primary documents only',?)",
            (iso(utcnow()),))

    engine = KnowledgeEngine(db)
    record: dict[str, object] = {
        "schema": "atlas.focus.corpus.v1",
        "generated_at": iso(utcnow()),
        "sec_user_agent": user_agent,
        "database": str(db_path.relative_to(ROOT)) if db_path.is_relative_to(ROOT) else str(db_path),
        "snapshot_directory": (str(snapshots.relative_to(ROOT))
                               if snapshots.is_relative_to(ROOT) else str(snapshots)),
        "documents": [],
        "limitations": [
            "Documents are fetched live from SEC EDGAR; the snapshot directory is the only copy "
            "of the authenticated bytes and is not committed.",
            "Availability times are modelled conservatively as EDGAR acceptance plus a fixed "
            "publication lag, with precision recorded as 'unknown'.",
        ],
    }

    for legal_name, (cik, years) in PINNED.items():
        issuer_id = ensure_issuer(db, cik, legal_name)
        for filing in select_filings(cik, years):
            accession = str(filing["accession"])
            primary = str(filing["primary_document"] or "")
            if not primary:
                raise SystemExit(f"{accession}: the filing lists no primary document")
            url = absolute_document_url(cik, accession, primary)
            existing = db.query_one(
                "SELECT document_id, sha256 FROM knowledge_document WHERE accession = ?",
                (accession,))
            if existing is not None and not args.force:
                snapshot = snapshots / f"{accession}.html"
                if not snapshot.exists():
                    snapshot.write_bytes(fetch_bytes(url))
                record["documents"].append({
                    "issuer": legal_name, "cik": cik, "accession": accession,
                    "status": "already_ingested", "document_id": existing["document_id"],
                    "document_sha256": existing["sha256"], "primary_document_url": url,
                })
                continue
            payload = fetch_bytes(url)
            digest = hashlib.sha256(payload).hexdigest()
            document = engine.ingest_document(
                issuer_id=issuer_id, accession=accession, form_type=str(filing["form_type"]),
                html=payload, filed_date=str(filing["filed_date"]),
                acceptance_time=filing.get("acceptance_time"),
                period_of_report=filing.get("period_of_report"), primary_document_url=url)
            snapshot = snapshots / f"{accession}.html"
            snapshot.write_bytes(payload)
            stored_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            if stored_digest != digest:
                raise SystemExit(f"{accession}: archived snapshot does not match ingested bytes")
            record["documents"].append({
                "issuer": legal_name, "cik": cik, "accession": accession, "status": "ingested",
                "document_id": document["document_id"], "document_sha256": digest,
                "bytes": len(payload), "tables": document["table_count"],
                "units": document["unit_count"],
                "availability_time": document["availability_time"],
                "availability_precision": document["availability_precision"],
                "primary_document_url": url,
            })
            print(json.dumps({"ingested": accession, "bytes": len(payload),
                              "tables": document["table_count"]}), flush=True)

    record["engine"] = engine.stats()
    record["document_count"] = len(record["documents"])
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
    db.close()
    print(json.dumps({"documents": record["document_count"], "engine": record["engine"]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
