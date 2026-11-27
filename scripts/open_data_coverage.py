#!/usr/bin/env python3
"""Measure what the SEC companyfacts archive actually contains.

A zip member is a *source file*, not an investable company. This script counts each
distinct fact once and reports the distinctions the Phase IV brief asks for:

* source files, unique CIKs and duplicate CIKs;
* companies with usable evidence (at least one recognised canonical concept);
* companies with a complete basic statement set (assets, revenue, net income);
* companies with a current listed security in the SEC ticker mapping;
* companies whose inputs could support an equity valuation method, with the methods
  that still require market prices marked separately;
* foreign issuers (IFRS facts), restated filings and non-December fiscal years.

No network: it reads an acquired archive and the acquired ticker mapping. Every count
is derived from the archive bytes, so the result is reproducible from the snapshot.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.concepts import CONCEPTS  # noqa: E402
from atlas.core.ids import normalize_cik  # noqa: E402
from atlas.core.temporal import iso, utcnow  # noqa: E402

TAG_TO_CONCEPTS: dict[tuple[str, str], set[str]] = {}
for _key, _concept in CONCEPTS.items():
    for _namespace, _tag in _concept.source_tags:
        TAG_TO_CONCEPTS.setdefault((_namespace, _tag), set()).add(_key)

MAJOR_EXCHANGES = {"NYSE", "NASDAQ", "NYSE AMERICAN", "NYSE MKT", "NYSE ARCA", "CBOE",
                   "CBOE BZX", "NASDAQ GLOBAL SELECT MARKET", "NASDAQ GLOBAL MARKET",
                   "NASDAQ CAPITAL MARKET"}

COMPLETE_CONCEPTS = {"assets", "revenue", "net_income"}
VALUATION_INPUT_CONCEPTS = {"revenue", "equity"}


def _tags_for(payload: dict) -> set[str]:
    """Canonical concepts this payload actually carries observations for."""
    found: set[str] = set()
    for namespace, elements in (payload.get("facts") or {}).items():
        if not isinstance(elements, dict):
            continue
        for tag, element in elements.items():
            if not isinstance(element, dict):
                continue
            units = element.get("units")
            if not isinstance(units, dict):
                continue
            if not any(observation.get("end") is not None and observation.get("val") is not None
                       for observations in units.values() if isinstance(observations, list)
                       for observation in observations if isinstance(observation, dict)):
                continue
            found.update(TAG_TO_CONCEPTS.get((namespace, tag), ()))
    return found


def _ticker_index(store_root: Path) -> dict[str, dict[str, str]]:
    from atlas.open_data.store import SnapshotStore

    store = SnapshotStore(store_root)
    snapshot = store.latest("sec.company_tickers")
    if snapshot is None:
        return {}
    entry = next((item for item in snapshot.files if item["name"].endswith(".json")), None)
    if entry is None:
        return {}
    payload = json.loads((snapshot.path / "files" / entry["path"]).read_text(encoding="utf-8"))
    fields = payload.get("fields") or []
    try:
        cik_at, ticker_at, exchange_at = fields.index("cik"), fields.index("ticker"), fields.index("exchange")
    except ValueError:
        return {}
    mapping: dict[str, dict[str, str]] = {}
    for row in payload.get("data") or []:
        cik = normalize_cik(str(row[cik_at]))
        mapping[cik] = {"ticker": str(row[ticker_at] or "").strip(),
                        "exchange": str(row[exchange_at] or "").strip()}
    return mapping


def measure(archive: Path, tickers: dict[str, dict[str, str]], *,
            limit: int | None = None, progress: bool = False) -> dict:
    started = time.monotonic()
    files = 0
    ciks: set[str] = set()
    duplicates = 0
    rejcted = 0
    usable = 0
    complete = 0
    ifrs = 0
    restated = 0
    non_december = 0
    with_ticker = 0
    listed = 0
    valuation_inputs = 0
    per_concept = Counter()
    years: Counter[int] = Counter()
    latest_ends: Counter[int] = Counter()
    unusable_examples: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        names = sorted(name for name in bundle.namelist() if name.endswith(".json"))
        if limit is not None:
            names = names[:limit]
        for name in names:
            files += 1
            try:
                payload = json.loads(bundle.read(name))
            except (json.JSONDecodeError, UnicodeDecodeError):
                rejcted += 1
                continue
            cik_value = payload.get("cik")
            if cik_value is None:
                rejcted += 1
                continue
            cik = normalize_cik(str(cik_value))
            if cik in ciks:
                duplicates += 1
            ciks.add(cik)
            concepts = _tags_for(payload)
            if not concepts:
                if len(unusable_examples) < 20:
                    unusable_examples.append(name)
                continue
            usable += 1
            per_concept.update(concepts)
            if COMPLETE_CONCEPTS <= concepts:
                complete += 1
            namespaces = payload.get("facts") or {}
            if "ifrs-full" in namespaces or "ifrs" in namespaces:
                ifrs += 1
            has_amendment = False
            latest_month = 0
            if isinstance(namespaces, dict):
                for elements in namespaces.values():
                    if not isinstance(elements, dict):
                        continue
                    for element in elements.values():
                        if not isinstance(element, dict):
                            continue
                        for observations in (element.get("units") or {}).values():
                            if not isinstance(observations, list):
                                continue
                            for observation in observations:
                                if not isinstance(observation, dict):
                                    continue
                                if str(observation.get("form") or "").upper().endswith("/A"):
                                    has_amendment = True
                                year = observation.get("fy")
                                if isinstance(year, int):
                                    years[year] += 1
                                end = observation.get("end")
                                if isinstance(end, str) and len(end) >= 7:
                                    try:
                                        latest_month = max(latest_month, int(end[5:7]))
                                        latest_ends[end[:4]] += 1
                                    except ValueError:
                                        continue
            if has_amendment:
                restated += 1
            if latest_month and latest_month != 12:
                non_december += 1
            entry = tickers.get(cik)
            if entry and entry.get("ticker"):
                with_ticker += 1
                if entry.get("exchange").upper() in MAJOR_EXCHANGES:
                    listed += 1
            if VALUATION_INPUT_CONCEPTS <= concepts:
                valuation_inputs += 1
            if progress and files % 2000 == 0:
                print(json.dumps({"files": files, "usable": usable,
                                  "elapsed_seconds": round(time.monotonic() - started, 1)}),
                      flush=True)
    return {
        "schema": "atlas.open_data.coverage.v1",
        "generated_at": iso(utcnow()),
        "archive": {"path": str(archive), "bytes": archive.stat().st_size},
        "source_files": files,
        "unique_ciks": len(ciks),
        "duplicate_cik_files": duplicates,
        "rejected_files": rejcted,
        "companies_with_usable_evidence": usable,
        "companies_with_complete_basic_statements": complete,
        "companies_with_ifrs_facts": ifrs,
        "companies_with_amended_filings": restated,
        "companies_with_non_december_fiscal_year_end": non_december,
        "companies_in_sec_ticker_mapping": with_ticker,
        "companies_with_major_exchange_listing": listed,
        "companies_with_revenue_and_equity": valuation_inputs,
        "valuation_methods": {
            "price_independent_inputs_present": valuation_inputs,
            "dcf_available": False,
            "comparables_available": False,
            "residual_income_available": False,
            "reason": ("No legitimate market-price source has been acquired, so every "
                       "price-dependent valuation method remains unavailable in this phase."),
        },
        "concepts": dict(per_concept.most_common()),
        "filing_years": {str(year): count for year, count in sorted(years.items())},
        "observation_end_years": {str(year): count for year, count in sorted(latest_ends.items())},
        "unusable_examples": unusable_examples,
        "definitions": {
            "usable_evidence": "at least one observation under a source tag that maps to an Atlas canonical concept",
            "complete_basic_statements": "usable evidence for total_assets, revenue and net_income",
            "listed": "SEC ticker mapping with a major-exchange code (not OTC)",
        },
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive")
    parser.add_argument("--root", default="/tmp/atlas_p4",
                        help="open-data root with store/ (used to find the archive and tickers)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=str(ROOT / "artifacts/open_data_coverage.json"))
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args(argv)
    if args.archive:
        archive = Path(args.archive)
    else:
        from atlas.open_data.store import SnapshotStore

        snapshot = SnapshotStore(Path(args.root) / "store").latest("sec.companyfacts")
        if snapshot is None:
            raise SystemExit("no acquired sec.companyfacts snapshot")
        archive = next(snapshot.path / "files" / entry["path"] for entry in snapshot.files
                       if entry["name"].endswith("companyfacts.zip"))
    payload = measure(archive, _ticker_index(Path(args.root) / "store"),
                      limit=args.limit, progress=args.progress)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "source_files", "unique_ciks", "companies_with_usable_evidence",
        "companies_with_complete_basic_statements", "companies_with_major_exchange_listing",
        "elapsed_seconds")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
