"""Build the held-out answer-semantics corpus from real SEC EDGAR 10-K filings.

This is the network step. It is deliberately separate from evaluation:

1. read the declared corpus (``fixtures/answer_semantics/corpus.json``);
2. fetch each filing's primary document as exact bytes and archive them under
   ``var/answer_semantics/snapshots/`` so later scoring is offline and reproducible;
3. ingest the same bytes through the normal knowledge engine, so the *baseline* resolver
   is measured on exactly the path production uses (flattened tables included);
4. fetch SEC XBRL company facts for each CIK and keep only the fact rows for 10-K filings
   in the evaluation window, with their provenance (tag, accession, period, unit, value);
5. write a manifest of document digests, availability times and fact digests.

Nothing here decides whether an answer is correct. The manifest records what was fetched;
correctness is established against XBRL plus reviewed filing geometry in
``fixtures/answer_semantics/questions.json``.

Requires ``ATLAS_SEC_USER_AGENT`` (a declared identity with a working contact, as SEC's
fair-access policy requires).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.knowledge import (  # noqa: E402
    KnowledgeEngine,
    absolute_document_url,
    sec_filings,
    sec_user_agent,
)
from atlas.storage.db import Database  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "answer_semantics" / "corpus.json"
DEFAULT_DB = ROOT / "var" / "answer_semantics" / "semantics.db"
DEFAULT_SNAPSHOTS = ROOT / "var" / "answer_semantics" / "snapshots"
DEFAULT_MANIFEST = ROOT / "artifacts" / "answer_semantics" / "corpus_manifest.json"

_MAX_DOCUMENT_BYTES = 45 * 1024 * 1024
#: XBRL tags an answer can be checked against. A fact is only evidence if the tag exists
#: in the filing; a missing tag is recorded as unavailable, never substituted.
FACT_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "NetIncomeLoss",
    "OperatingIncomeLoss",
    "Assets",
    "Liabilities",
    "NetCashProvidedByUsedInOperatingActivities",
    "GrossProfit",
)
#: The XBRL window. Company facts keep one row per accession that reports a fact, which is
#: what makes restatements visible: the same fiscal year can carry two different values.
FACT_YEARS = (2015, 2024)


def load_corpus(path: Path = CORPUS) -> dict[str, Any]:
    return json.loads(path.read_text())


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "identity"})
    with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed sec.gov host
        payload = response.read(_MAX_DOCUMENT_BYTES + 1)
    if len(payload) > _MAX_DOCUMENT_BYTES:
        raise SystemExit(f"document exceeds the ingestion limit: {url}")
    return payload


def _submissions(cik: str) -> dict[str, Any]:
    url = f"https://data.sec.gov/submissions/CIK{str(cik).lstrip('0').zfill(10)}.json"
    request = Request(url, headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "identity"})
    with urlopen(request, timeout=90) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _companyfacts(cik: str) -> dict[str, Any]:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).lstrip('0').zfill(10)}.json"
    request = Request(url, headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "identity"})
    with urlopen(request, timeout=120) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def trimmed_facts(payload: dict[str, Any], cik: str) -> list[dict[str, Any]]:
    """Keep only 10-K USD fact rows for the declared tag allowlist and year window."""
    out: list[dict[str, Any]] = []
    for namespace, tags in (payload.get("facts") or {}).items():
        for tag, entry in tags.items():
            if tag not in FACT_TAGS:
                continue
            for unit, rows in (entry.get("units") or {}).items():
                if unit != "USD":
                    continue
                for row in rows:
                    if str(row.get("form", "")).upper() not in {"10-K", "10-K/A"}:
                        continue
                    end = str(row.get("end") or "")
                    if not end[:4].isdigit() or not (FACT_YEARS[0] <= int(end[:4]) <= FACT_YEARS[1]):
                        continue
                    out.append({
                        "cik": str(cik).lstrip("0").zfill(10),
                        "namespace": namespace,
                        "tag": tag,
                        "unit": unit,
                        "start": row.get("start"),
                        "end": end,
                        "fy": row.get("fy"),
                        "fp": row.get("fp"),
                        "form": row.get("form"),
                        "accn": row.get("accn"),
                        "filed": row.get("filed"),
                        "frame": row.get("frame"),
                        "val": row.get("val"),
                    })
    out.sort(key=lambda item: (item["tag"], item["end"], str(item["accn"])))
    return out


def _ensure_source(db: Database) -> None:
    """Register EDGAR with a precise, non-authorship rights statement.

    EDGAR filings are prepared and filed by issuers. They are not works of federal employees,
    so 17 U.S.C. 105 (public-domain status for federal works) does not apply and this code must
    not label them ``public_domain``. What is true is narrower: SEC web-access policy permits
    access and reuse subject to fair access, no fee and no implied SEC endorsement. The
    registry's ``redistribution`` field is a local assertion of a redistribution right, and
    Atlas asserts none: the existing ``user_responsibility`` value is used so the obligation
    stays with whoever redistributes, and the licence text carries the precise position.
    """
    licence = ("Issuer-prepared SEC filing; access and reuse permitted under SEC web-site policy "
               "(fair access, no fee); not a work of U.S. federal employees, so 17 U.S.C. 105 "
               "does not apply and no public-domain status is asserted")
    if db.query_one("SELECT 1 FROM source WHERE source_id='sec-edgar'") is None:
        db.execute(
            "INSERT INTO source (source_id,name,kind,homepage,licence,redistribution,notes,created_at)"
            " VALUES ('sec-edgar','SEC EDGAR','sec_edgar','https://www.sec.gov',?,"
            "'user_responsibility','issuer-prepared filings; SEC access-and-reuse terms, not "
            "federal authorship',?)", (licence, iso(utcnow())))


def _ensure_issuer(db: Database, cik: str, legal_name: str) -> str:
    existing = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
    if existing:
        return existing["issuer_id"]
    issuer_id = f"ISS-CIK{cik}"
    now = iso(utcnow())
    db.execute(
        "INSERT INTO issuer (issuer_id,cik,legal_name,entity_type,is_active,"
        "provenance_source,created_at,updated_at) VALUES (?,?,?,'company',1,'sec',?,?)",
        (issuer_id, cik, legal_name, now, now))
    return issuer_id


def build(*, corpus_path: Path, db_path: Path, snapshots: Path, manifest_path: Path,
          only: list[str] | None = None) -> dict[str, Any]:
    corpus = load_corpus(corpus_path)
    filings = [item for item in corpus["filings"] if not only or item["key"] in only]
    if not filings:
        raise SystemExit("no filings selected")
    snapshots.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(str(db_path))
    database.migrate()
    _ensure_source(database)
    engine = KnowledgeEngine(database)

    # SEC metadata once per CIK (submissions and XBRL are per-company resources).
    submissions: dict[str, dict[str, Any]] = {}
    facts: dict[str, list[dict[str, Any]]] = {}
    for cik in sorted({item["cik"] for item in filings}):
        submissions[cik] = _submissions(cik)
        facts[cik] = trimmed_facts(_companyfacts(cik), cik)
        print(f"facts {cik}: {len(facts[cik])} 10-K rows in window")

    records: list[dict[str, Any]] = []
    for filing in filings:
        cik = filing["cik"]
        listed = next((row for row in sec_filings(cik, forms=["10-K", "10-K/A"])
                       if row["accession"] == filing["accession"]), None)
        if listed is None:
            raise SystemExit(f"accession not in the SEC submissions archive: {filing['accession']}")
        legal_name = submissions[cik].get("name") or filing["issuer"]
        issuer_id = _ensure_issuer(database, cik, legal_name)
        # Some filers put the financial statements in an Item 8 exhibit rather than the primary
        # document. The declared corpus names the document that actually holds the statements.
        document_name = filing.get("document_name") or listed["primary_document"]
        url = absolute_document_url(cik, filing["accession"], document_name)
        started = time.time()
        payload = _fetch_bytes(url)
        snapshot = snapshots / f"{filing['accession']}.html"
        snapshot.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        existing = database.query_one(
            "SELECT document_id, sha256 FROM knowledge_document WHERE accession = ?",
            (filing["accession"],))
        if existing:
            if existing["sha256"] != digest:
                raise SystemExit(f"archived bytes differ from the ingested document: "
                                 f"{filing['accession']}")
            document = engine.document(existing["document_id"])
        else:
            document = engine.ingest_document(
                issuer_id=issuer_id, accession=filing["accession"], form_type="10-K",
                html=payload, filed_date=listed["filed_date"],
                acceptance_time=listed["acceptance_time"],
                period_of_report=listed.get("period_of_report") or filing["period_of_report"],
                rights="user_responsibility", primary_document_url=url)
        records.append({
            **filing,
            "document_name": document_name,
            "document_role": filing.get("document_role", "primary_document"),
            "issuer_sec_name": legal_name,
            "issuer_id": issuer_id,
            "document_id": document["document_id"],
            "document_sha256": digest,
            "snapshot": str(snapshot.relative_to(ROOT)),
            "primary_document_url": url,
            "filed_date": listed["filed_date"],
            "acceptance_time": listed["acceptance_time"],
            "availability_time": document["availability_time"],
            "availability_precision": document["availability_precision"],
            "bytes": len(payload),
            "units": document["unit_count"],
            "tables": document["table_count"],
            "seconds": round(time.time() - started, 2),
        })
        print(f"ingested {filing['key']} → {document['document_id']} "
              f"({records[-1]['seconds']}s, {document['table_count']} tables)")

    manifest = {
        "schema": "atlas.answer_semantics.corpus_manifest.v1",
        "built_at": iso(utcnow()),
        "database": str(db_path.relative_to(ROOT)),
        "snapshots": str(snapshots.relative_to(ROOT)),
        "filings": records,
        "xbrl": {
            "source": "https://data.sec.gov/api/xbrl/companyfacts/",
            "tags": list(FACT_TAGS),
            "years": list(FACT_YEARS),
            "counts": {cik: len(rows) for cik, rows in facts.items()},
            "digest": hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
        },
                    "rights": corpus["rights"],
            "source_registry": {"redistribution": "user_responsibility",
                                "note": "issuer-prepared filings; SEC access-and-reuse terms, "
                                        "no federal-authorship claim"},
        "limitations": [
            "Filings are fetched at build time; the repository never stores filing bodies.",
            "XBRL facts are the independent check for value, unit and period; they are not a "
            "substitute for statement geometry when a fact is absent or restated.",
            "A rebuild requires network access to data.sec.gov / www.sec.gov and "
            "ATLAS_SEC_USER_AGENT.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    # Facts are committed beside the corpus: they are small, factual and auditable. Filing
    # bodies are not committed, so a clone can inspect ground truth but cannot re-parse.
    facts_path = corpus_path.parent / "xbrl_facts.json"
    facts_path.write_text(json.dumps({
        "schema": "atlas.answer_semantics.xbrl_facts.v1",
        "source": "https://data.sec.gov/api/xbrl/companyfacts/",
        "tags": list(FACT_TAGS),
        "count": sum(len(rows) for rows in facts.values()),
        "facts": facts,
    }, indent=1, sort_keys=True) + "\n")
    return {"manifest": str(manifest_path), "facts": str(facts_path), "filings": len(records)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(CORPUS))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--snapshots", default=str(DEFAULT_SNAPSHOTS))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--only", nargs="*", help="filing keys to build")
    args = parser.parse_args(argv)
    result = build(corpus_path=Path(args.corpus), db_path=Path(args.db),
                   snapshots=Path(args.snapshots), manifest_path=Path(args.manifest),
                   only=args.only)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
