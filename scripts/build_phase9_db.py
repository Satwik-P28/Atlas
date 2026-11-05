#!/usr/bin/env python
"""Build a real-data Phase 9 research database from the compact SEC fixture.

No prices are generated. The resulting database contains SEC-reported fundamentals only;
market-dependent screens and valuations that require a price will report the missing input.

Usage:
    python scripts/build_phase9_db.py --db var/phase9.db --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.entities.master import (  # noqa: E402
    STATUS_PROBABLE,
    SecurityMaster,
)
from atlas.ingestion.sec_sync import (  # noqa: E402
    SecIngestor,
    load_fixture_payloads,
    register_fixture_documents,
)
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import SourceRegistry, ensure_default_sources  # noqa: E402

FIXTURE = ROOT / "fixtures" / "phase9"
MANIFEST = FIXTURE / "sec_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tickers", default="", help="comma-separated subset (default: all)")
    args = parser.parse_args()
    path = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    if path.exists() and not args.force:
        raise SystemExit(f"{path} exists; pass --force to replace it")
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    requested = {item.strip().upper() for item in args.tickers.split(",") if item.strip()}
    documents = [item for item in manifest["documents"] if not requested or item["ticker"] in requested]
    if not documents:
        raise SystemExit("no companies selected")

    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    identity_source = SourceRegistry(db).ensure_custom(
        "Atlas Phase 9 coverage manifest",
        kind="catalog",
        licence="Apache-2.0 (selection metadata)",
        redistribution="public_domain",
        notes=(
            "Curated CIK-to-ticker/exchange mapping for the 20-company research fixture. "
            "It is not a market feed; SEC submissions remain the financial-fact source."
        ),
        source_id="phase9-coverage",
    )
    ingestor = SecIngestor(db)
    master = SecurityMaster(db)
    rows = []
    for item in documents:
        folder = FIXTURE / "sec" / item["ticker"]
        submissions, facts, _, _ = load_fixture_payloads(folder, item["cik"])
        submissions_doc, facts_doc = register_fixture_documents(db, folder, item["cik"])
        report = ingestor.sync_payloads(
            item["cik"],
            submissions_payload=submissions,
            companyfacts_payload=facts,
            submissions_doc_id=submissions_doc,
            companyfacts_doc_id=facts_doc,
            observed_at=manifest["retrieved_at"],
        )
        # The SEC submissions cover page omitted a ticker for at least one issuer. The
        # coverage manifest supplies a disclosed CIK-to-listing identity; it is never
        # presented as an SEC-reported ticker.
        existing_tickers = {
            ticker["ticker"]
            for security in master.securities_for_issuer(report.issuer_id)
            for ticker in ([master.current_ticker(security["security_id"])] if master.current_ticker(security["security_id"]) else [])
        }
        identity_note = None
        if item["ticker"] not in existing_tickers:
            securities = master.securities_for_issuer(report.issuer_id)
            if securities:
                security_id = securities[0]["security_id"]
            else:
                security_id = master.ensure_security(
                    report.issuer_id,
                    class_designation="common stock",
                    security_type="common_stock",
                    currency="USD",
                    source_id=identity_source,
                    note="identity supplied by the curated Phase 9 coverage manifest",
                )
            mic = item["exchange_mic"]
            master.ensure_venue(mic, mic, country="US", timezone="America/New_York")
            listing_id = master.ensure_listing(
                security_id, mic, valid_from=None, currency="USD", is_primary=True,
                source_id=identity_source,
            )
            master.assign_ticker(
                listing_id, item["ticker"], valid_from=None, confidence=0.5,
                status=STATUS_PROBABLE, source_id=identity_source,
                evidence_note=(
                    "curated CIK-to-ticker mapping in the Phase 9 coverage manifest; "
                    "not reported by the SEC submissions payload"
                ),
            )
            identity_note = "ticker/exchange supplied by disclosed coverage manifest"
        else:
            # SEC submissions lists every instrument the registrant files under, including
            # unaffiliated notes and preferred series, without mapping them to share classes.
            # The coverage manifest declares the primary ticker for this universe; record that
            # choice explicitly so ticker selection is never an alphabetical accident.
            db.execute(
                "UPDATE ticker_assignment SET confidence = MAX(confidence, 0.6), "
                "evidence_note = ? WHERE ticker = ? AND valid_to IS NULL AND listing_id IN ("
                "SELECT listing_id FROM listing WHERE security_id IN ("
                "SELECT security_id FROM security WHERE issuer_id = ?))",
                (
                    "primary ticker declared by the Phase 9 coverage manifest; SEC submissions "
                    "lists multiple unaffiliated instruments and does not map share classes",
                    item["ticker"],
                    report.issuer_id,
                ),
            )
            identity_note = "primary ticker declared by coverage manifest (SEC lists multiple instruments)"
        rows.append({
            "ticker": item["ticker"],
            "cik": item["cik"],
            "issuer_id": report.issuer_id,
            "legal_name": report.legal_name,
            "filings": report.filings_written,
            "evidence": int(report.evidence.get("inserted", 0)),
            "concepts": len(report.companyfacts.get("stats", {}).get("concepts_covered", [])),
            "identity_note": identity_note,
        })
        print(
            f"{item['ticker']:5s} {report.legal_name[:38]:38s} "
            f"{report.filings_written:4d} filings {report.evidence.get('inserted', 0):5d} facts",
            flush=True,
        )
    payload = {
        "schema": "atlas.phase9.coverage_build.v1",
        "source": "SEC EDGAR public domain",
        "price_coverage": "none",
        "companies": rows,
        "issuers": db.scalar("SELECT COUNT(*) FROM issuer", default=0),
        "filings": db.scalar("SELECT COUNT(*) FROM filing", default=0),
        "evidence": db.scalar("SELECT COUNT(*) FROM evidence", default=0),
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "coverage_note": manifest["coverage_note"],
    }
    output = ROOT / "artifacts" / "phase9_coverage_build.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("issuers", "filings", "evidence")}, indent=2))
    print(f"database: {path}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
