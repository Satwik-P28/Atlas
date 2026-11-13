"""Phase 9.6 corpus builder: FinanceBench OPEN_SOURCE questions → real EDGAR filings.

Company→CIK mapping is explicit and verified against the SEC's own issuer name. Fuzzy name
matching was rejected after it mapped Amazon→AAON and Verizon→Veritone; a wrong issuer would
poison every downstream metric.

Only 10-K questions are ingested: one 10-K exists per fiscal year, so the target document is
unambiguous. 10-Q/8-K/earnings questions are recorded as excluded with a reason rather than
guessing which of several filings the annotator used.

No question text, answer, or source document is written into the repository. The manifest holds
metadata only.

    python scripts/phase9_6_corpus.py --questions /tmp/financebench_rows.json --db var/phase9_6.db
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.knowledge import (  # noqa: E402
    KnowledgeEngine, SEC_PUBLICATION_LAG_SECONDS, SEC_USER_AGENT, _get_json,
    absolute_document_url, fetch_sec_document, sec_filings,
)
from atlas.storage.db import Database  # noqa: E402

#: company (as named by FinanceBench) -> (CIK, tokens that must appear in the SEC issuer name)
ISSUERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "3M": ("0000066740", ("3m",)),
    "AES Corporation": ("0000874761", ("aes",)),
    "AMD": ("0000002488", ("advanced", "micro")),
    "Activision Blizzard": ("0000718877", ("activision",)),
    "Adobe": ("0000796343", ("adobe",)),
    "Amazon": ("0001018724", ("amazon",)),
    "Amcor": ("0001748790", ("amcor",)),
    "American Express": ("0000004962", ("american", "express")),
    "American Water Works": ("0001410636", ("american", "water")),
    "Best Buy": ("0000764478", ("best", "buy")),
    "Block": ("0001512673", ("block",)),
    "Boeing": ("0000012927", ("boeing",)),
    "CVS Health": ("0000064803", ("cvs",)),
    "Coca-Cola": ("0000021344", ("coca", "cola")),
    "Corning": ("0000024741", ("corning",)),
    "Costco": ("0000909832", ("costco",)),
    "Foot Locker": ("0000850209", ("foot", "locker")),
    "General Mills": ("0000040704", ("general", "mills")),
    "JPMorgan": ("0000019617", ("jpmorgan",)),
    "Johnson & Johnson": ("0000200406", ("johnson",)),
    "Kraft Heinz": ("0001637459", ("kraft", "heinz")),
    "Lockheed Martin": ("0000936468", ("lockheed",)),
    "MGM Resorts": ("0000789570", ("mgm",)),
    "Microsoft": ("0000789019", ("microsoft",)),
    "Netflix": ("0001065280", ("netflix",)),
    "Nike": ("0000320187", ("nike",)),
    "Paypal": ("0001633917", ("paypal",)),
    "PepsiCo": ("0000077476", ("pepsico",)),
    "Pfizer": ("0000078003", ("pfizer",)),
    "Ulta Beauty": ("0001403568", ("ulta",)),
    "Verizon": ("0000732712", ("verizon",)),
    "Walmart": ("0000104169", ("walmart",)),
}

FORM_FOR_DOC = {"10k": "10-K", "10q": "10-Q", "8k": "8-K", "Earnings": "8-K"}


def verify_issuer(cik: str, tokens: tuple[str, ...]) -> tuple[bool, str]:
    try:
        payload = _get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    except Exception as exc:  # noqa: BLE001 - reported in the manifest
        return False, f"lookup_failed: {type(exc).__name__}"
    name = str(payload.get("name", "")).lower()
    missing = [token for token in tokens if token not in name]
    return (not missing), payload.get("name", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="/tmp/financebench_rows.json")
    parser.add_argument("--db", default="var/phase9_6.db")
    parser.add_argument("--manifest", default="artifacts/phase9_6_corpus_manifest.json")
    parser.add_argument("--max-targets", type=int, default=0)
    args = parser.parse_args()

    rows = json.loads(Path(args.questions).read_text())
    open_rows = [row for row in rows if row.get("dataset_subset_label") == "OPEN_SOURCE"]
    targets: dict[tuple[str, str, str], list[dict]] = {}
    for row in open_rows:
        key = (row["company"], str(row["doc_type"]), str(row["doc_period"]))
        targets.setdefault(key, []).append(row)

    db = Database(args.db)
    db.migrate()
    engine = KnowledgeEngine(db)
    if db.query_one("SELECT 1 FROM source WHERE source_id='sec-edgar'") is None:
        db.execute(
            "INSERT INTO source (source_id,name,kind,homepage,licence,redistribution,notes,created_at)"
            " VALUES ('sec-edgar','SEC EDGAR','sec_edgar','https://www.sec.gov','US public record',"
            "'public_domain','primary documents only',?)", (iso(utcnow()),),
        )
    manifest: dict[str, object] = {
        "schema": "atlas.phase9_6.corpus.v1",
        "dataset": "PatronusAI/financebench (OPEN_SOURCE, cc-by-nc-4.0) — evaluation only, "
                   "no text stored in the repository",
        "sec_user_agent": SEC_USER_AGENT,
        "publication_lag_seconds": SEC_PUBLICATION_LAG_SECONDS,
        "questions_total": len(open_rows),
        "targets": [],
        "issuer_verification": {},
    }
    verified: dict[str, str] = {}
    for company, (cik, tokens) in ISSUERS.items():
        if company not in {key[0] for key in targets}:
            continue
        ok, detail = verify_issuer(cik, tokens)
        manifest["issuer_verification"][company] = {"cik": cik, "verified": ok, "sec_name": detail}
        if ok:
            creditor = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
            if creditor is None:
                issuer_id = f"ISS-CIK{cik}"
                now = iso(utcnow())
                db.execute(
                    "INSERT INTO issuer (issuer_id,cik,legal_name,entity_type,is_active,"
                    "provenance_source,created_at,updated_at) VALUES (?,?,?,'company',1,'sec',?,?)",
                    (issuer_id, cik, str(detail) or company, now, now),
                )
            else:
                issuer_id = creditor["issuer_id"]
            verified[company] = issuer_id

    processed = 0
    for (company, doc_type, period), group in sorted(targets.items()):
        entry: dict[str, object] = {
            "company": company, "doc_type": doc_type, "period": period,
            "questions": len(group),
        }
        if doc_type != "10k":
            entry.update(status="excluded", reason="document_type_outside_ingested_scope")
            manifest["targets"].append(entry)
            continue
        if company not in verified:
            entry.update(status="excluded", reason="issuer_not_verified")
            manifest["targets"].append(entry)
            continue
        form = FORM_FOR_DOC[doc_type]
        try:
            filings = sec_filings(ISSUERS[company][0], forms=[form])
        except Exception as exc:  # noqa: BLE001
            entry.update(status="failed", reason=f"listing_failed: {type(exc).__name__}")
            manifest["targets"].append(entry)
            continue
        matches = [f for f in filings
                   if f["period_of_report"] and str(f["period_of_report"]).startswith(str(period))]
        if len(matches) != 1:
            entry.update(status="excluded",
                         reason="ambiguous_or_missing_annual_report" if matches else "no_matching_filing",
                         candidates=[f["accession"] for f in matches][:6])
            manifest["targets"].append(entry)
            continue
        filing = matches[0]
        primary = filing.get("primary_document") or ""
        if not primary or not primary.lower().endswith((".htm", ".html", ".txt")):
            entry.update(status="excluded", reason="primary_document_not_html",
                         primary_document=primary)
            manifest["targets"].append(entry)
            continue
        existing = db.query_one("SELECT document_id, unit_count, table_count FROM knowledge_document "
                                "WHERE accession = ?", (filing["accession"],))
        if existing:
            entry.update(status="already_ingested", accession=filing["accession"],
                         document_id=existing["document_id"], units=existing["unit_count"])
            manifest["targets"].append(entry)
            continue
        if args.max_targets and processed >= args.max_targets:
            entry.update(status="deferred", reason="max_targets_reached")
            manifest["targets"].append(entry)
            continue
        started = time.perf_counter()
        try:
            html = fetch_sec_document(ISSUERS[company][0], filing["accession"], primary)
            document = engine.ingest_document(
                issuer_id=verified[company], accession=filing["accession"],
                form_type=filing["form_type"], html=html, filed_date=filing["filed_date"],
                acceptance_time=filing.get("acceptance_time"),
                period_of_report=filing.get("period_of_report"),
                primary_document_url=absolute_document_url(
                    ISSUERS[company][0], filing["accession"], primary),
            )
            entry.update(status="ingested", accession=filing["accession"],
                         document_id=document["document_id"], units=document["unit_count"],
                         tables=document["table_count"], bytes=document["byte_size"],
                         availability_time=document["availability_time"],
                         availability_basis=document["availability_basis"],
                         seconds=round(time.perf_counter() - started, 2))
            processed += 1
        except Exception as exc:  # noqa: BLE001
            entry.update(status="failed", reason=f"{type(exc).__name__}: {exc}"[:200])
        manifest["targets"].append(entry)

    counts = Counter(item["status"] for item in manifest["targets"])
    manifest["status_counts"] = dict(counts)
    manifest["engine_stats"] = engine.stats()
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status_counts": dict(counts), "engine": engine.stats()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
