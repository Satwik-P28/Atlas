#!/usr/bin/env python
"""Fetch a compact, reproducible 20-company SEC research coverage fixture.

Only facts mapped by the explicit Atlas concept registry are retained. Every retained
observation keeps its accession, filing date, form and reported value. Prices are not
fetched: Atlas will show that licensed market observations are unavailable rather than
substitute synthetic quotes into a real-company valuation.

Raw responses are written under ``var/phase9-sec-raw`` (ignored). The compact fixture under
``fixtures/phase9/sec`` and its manifest are intended to be committed.

Usage:
    python scripts/fetch_phase9_sec_coverage.py
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.concepts import CONCEPTS, resolve_tag  # noqa: E402

COMPANIES = (
    ("AAPL", "0000320193", "Technology", "XNAS"),
    ("MSFT", "0000789019", "Technology", "XNAS"),
    ("GOOGL", "0001652044", "Communication services", "XNAS"),
    ("AMZN", "0001018724", "Consumer discretionary", "XNAS"),
    ("META", "0001326801", "Communication services", "XNAS"),
    ("NVDA", "0001045810", "Technology", "XNAS"),
    ("IBM", "0000051143", "Technology", "XNYS"),
    ("JPM", "0000019617", "Financials", "XNYS"),
    ("GS", "0000886982", "Financials", "XNYS"),
    ("JNJ", "0000200406", "Health care", "XNYS"),
    ("PFE", "0000078003", "Health care", "XNYS"),
    ("UNH", "0000731766", "Health care", "XNYS"),
    ("XOM", "0000034088", "Energy", "XNYS"),
    ("CVX", "0000093410", "Energy", "XNYS"),
    ("CAT", "0000018230", "Industrials", "XNYS"),
    ("DE", "0000315189", "Industrials", "XNYS"),
    ("KO", "0000021344", "Consumer staples", "XNYS"),
    ("PEP", "0000077476", "Consumer staples", "XNAS"),
    ("WMT", "0000104169", "Consumer staples", "XNAS"),
    ("COST", "0000909832", "Consumer staples", "XNAS"),
)
USER_AGENT = "AtlasQuant/0.3 phase9@example.com"
KEEP_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
MIN_END = "2018-01-01"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read()
        if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
            body = gzip.decompress(body)
        return body


def _compact_facts(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    source_facts = payload.get("facts") or {}
    available: set[tuple[str, str]] = set()
    for namespace, elements in source_facts.items():
        if isinstance(elements, dict):
            available.update((str(namespace), str(tag)) for tag in elements)

    def is_annual(item: dict[str, Any]) -> bool:
        start, end = item.get("start"), item.get("end")
        if not start or not end:
            return str(item.get("form") or "").startswith("10-K")
        try:
            days = (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
        except ValueError:
            return False
        return days >= 330 or str(item.get("form") or "").startswith("10-K")

    mapped: dict[str, dict[str, Any]] = {}
    concepts: list[str] = []
    for key, concept in CONCEPTS.items():
        # Preserve every source element the registry accepts, not only the current
        # highest-priority tag. Issuers migrate XBRL tags over time; the parser resolves
        # a tag per period, so both historical and current years must remain available.
        selected_tags = [
            (namespace, tag)
            for namespace, tag in concept.source_tags
            if (namespace, tag) in available
        ]
        if not selected_tags:
            continue
        concepts.append(key)
        for namespace, tag in selected_tags:
            element = source_facts.get(namespace, {}).get(tag, {})
            units = element.get("units") or {}
            kept_units: dict[str, list[dict[str, Any]]] = {}
            for unit, observations in units.items():
                kept = []
                for item in observations or []:
                    end = str(item.get("end") or "")
                    form = str(item.get("form") or "")
                    if end < MIN_END or (form and form not in KEEP_FORMS):
                        continue
                    if item.get("val") is None:
                        continue
                    kept.append({
                        key_: item.get(key_)
                        for key_ in ("start", "end", "val", "accn", "fy", "fp", "form", "filed")
                        if item.get(key_) is not None
                    })
                if not kept:
                    continue
                kept.sort(key=lambda item: (str(item.get("end") or ""), str(item.get("accn") or "")))
                yearly = [item for item in kept if is_annual(item)]
                subannual = [item for item in kept if not is_annual(item)]
                retained = yearly + subannual[-24:]
                retained.sort(key=lambda item: (str(item.get("end") or ""), str(item.get("accn") or "")))
                kept_units[unit] = retained[-120:]
            if kept_units:
                mapped.setdefault(namespace, {})[tag] = {"units": kept_units}
    compact = {
        "cik": payload.get("cik"),
        "entityName": payload.get("entityName"),
        "facts": mapped,
        "_atlas_filter": {
            "concepts": concepts,
            "forms": sorted(KEEP_FORMS),
            "minimum_period_end": MIN_END,
            "maximum_observations_per_unit": 120,
            "note": "All annual/10-K observations plus the 24 most recent sub-annual observations; values and accessions are unchanged.",
        },
    }
    return compact, concepts


def _compact_submissions(payload: dict[str, Any], accessions: set[str]) -> dict[str, Any]:
    """Keep issuer metadata and only the recent filings that support retained facts.

    The full submissions payload can contain tens of thousands of ownership filings. Those
    rows add bulk without adding a filing in which a retained financial fact was reported.
    The archival ``filings.files`` indexes are deliberately omitted because this compact
    fixture does not contain those archives; the coverage note states the resulting gap.
    """
    copy = {key: value for key, value in payload.items() if key != "filings"}
    recent = (payload.get("filings") or {}).get("recent")
    filings: dict[str, Any] = {}
    if isinstance(recent, dict):
        rows = len(recent.get("accessionNumber") or [])
        keep_indices = [
            index
            for index, accession in enumerate(recent.get("accessionNumber") or [])
            if accession in accessions
        ]
        filtered = {
            column: [values[index] for index in keep_indices]
            for column, values in recent.items()
            if isinstance(values, list) and len(values) == rows
        }
        filings["recent"] = filtered
        filings["_atlas_filter"] = {
            "source_recent_rows": rows,
            "retained_rows": len(keep_indices),
            "retained_accessions_only": True,
            "archive_files_omitted": len((payload.get("filings") or {}).get("files") or []),
            "note": "Recent filing metadata is retained only where its accession supports a retained XBRL fact.",
        }
    copy["filings"] = filings
    return copy


def main() -> int:
    raw_root = ROOT / "var" / "phase9-sec-raw"
    target = ROOT / "fixtures" / "phase9" / "sec"
    raw_root.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    documents = []
    for ticker, cik, sector, exchange in COMPANIES:
        folder = target / ticker
        folder.mkdir(parents=True, exist_ok=True)
        urls = {
            "submissions": f"https://data.sec.gov/submissions/CIK{cik}.json",
            "companyfacts": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        }
        raw: dict[str, bytes] = {}
        raw_paths: dict[str, Path] = {}
        for name, url in urls.items():
            cache = raw_root / f"{ticker}_{name}.json"
            raw_paths[name] = cache
            if cache.exists() and cache.stat().st_size:
                body = cache.read_bytes()
            else:
                body = _fetch(url)
                cache.write_bytes(body)
                time.sleep(0.16)
            raw[name] = body
        submissions = json.loads(raw["submissions"])
        facts = json.loads(raw["companyfacts"])
        compact_facts, concepts = _compact_facts(facts)
        accessions = {
            str(observation.get("accn"))
            for namespaces in compact_facts["facts"].values()
            for element in namespaces.values()
            for observations in element["units"].values()
            for observation in observations
            if observation.get("accn")
        }
        compact_submissions = _compact_submissions(submissions, accessions)
        (folder / "submissions.json").write_text(
            json.dumps(compact_submissions, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        (folder / "companyfacts.json").write_text(
            json.dumps(compact_facts, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        documents.append({
            "ticker": ticker,
            "cik": cik,
            "sector": sector,
            "exchange_mic": exchange,
            "legal_name": submissions.get("name"),
            "source_urls": urls,
            "source_sha256": {name: hashlib.sha256(body).hexdigest() for name, body in raw.items()},
            "source_bytes": {name: len(body) for name, body in raw.items()},
            "raw_retrieved_at": min(
                datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
                for path in raw_paths.values()
            ),
            "fixture_sha256": {
                "submissions": hashlib.sha256((folder / "submissions.json").read_bytes()).hexdigest(),
                "companyfacts": hashlib.sha256((folder / "companyfacts.json").read_bytes()).hexdigest(),
            },
            "fact_concepts": concepts,
        })
        print(f"{ticker}: {len(concepts)} concepts, {len(raw['companyfacts']):,} raw bytes", flush=True)
    manifest = {
        "schema": "atlas.phase9.sec_coverage.v1",
        "retrieved_at": retrieved_at,
        "user_agent": USER_AGENT,
        "license": "U.S. Government public domain (SEC EDGAR)",
        "company_count": len(documents),
        "price_coverage": "none; no market-price source is bundled or fabricated",
        "filter": {
            "concepts": sorted(CONCEPTS),
            "forms": sorted(KEEP_FORMS),
            "minimum_period_end": MIN_END,
            "maximum_observations_per_unit": 120,
            "retention_rule": "all annual/10-K observations and the 24 most recent sub-annual observations",
        },
        "coverage_note": (
            "Retained SEC facts begin in 2018; all annual/10-K observations and the 24 most recent "
            "sub-annual observations per unit are kept. Filing metadata is retained only for accessions "
            "that support those facts; pre-2018 filing archive files are not included. Market prices are "
            "absent. Ticker/exchange metadata in this manifest is a curated CIK-to-listing map; it is not "
            "a market feed, and SEC submissions remain the financial-fact source. This is a documented "
            "research window, not a claim of complete SEC history."
        ),
        "documents": documents,
    }
    path = ROOT / "fixtures" / "phase9" / "sec_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(path), "companies": len(documents)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
