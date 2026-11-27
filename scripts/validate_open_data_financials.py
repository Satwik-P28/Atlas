#!/usr/bin/env python3
"""Validate financial extraction and ratios against the raw XBRL source.

The corpus is a frozen, stratified sample of SEC companyfacts members. For each
issuer the script:

1. selects values *independently* of the Atlas normaliser, straight from the raw
   ``facts`` object, with an explicit tag priority and a latest-filed rule;
2. reads what the Atlas columnar evidence layer reports for the same period;
3. compares the decimal strings exactly and the derived ratios numerically;
4. tests the historical cutoff: an as-of instant before the filing availability must
   hide the observation, and a later instant must expose it;
5. records missing inputs, refusals and unsupported cases instead of counting a
   successful run as financial accuracy.

Price-dependent valuation methods are reported as unavailable: no legitimate market
price source is part of this phase, so they are not executed at all.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.concepts import CONCEPTS  # noqa: E402
from atlas.core.ids import normalize_cik  # noqa: E402
from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.open_data.columnar import ColumnarEvidence, build_from_archive  # noqa: E402

#: Tag priority is the published concept contract (`CONCEPTS[key].source_tags`), so a
#: disagreement is about extraction, not about which synonym was chosen. The selection
#: of period and filing below is written independently of the normaliser.
TAG_PRIORITY: dict[str, tuple[tuple[str, str], ...]] = {
    key: tuple((namespace, tag) for namespace, tag in CONCEPTS[key].source_tags)
    for key in ("revenue", "net_income", "assets", "liabilities", "equity",
                "gross_profit", "cost_of_revenue")
}

#: Marker tags used only to place an issuer in a reporting stratum.
STRATUM_TAGS = {
    "bank": ("Deposits", "InterestIncomeExpenseNet", "LoansAndLeasesReceivableNetReportedAmount"),
    "insurer": ("LiabilityForClaimsAndClaimsAdjustmentExpense", "PremiumsEarnedNet"),
    "retail": ("RetailRelatedInventory", "InventoryNet"),
    "energy": ("OilAndGasRevenue", "OilAndGasPropertySuccessfulEffortMethodNet"),
    "technology": ("ResearchAndDevelopmentExpense", "IntangibleAssetsNetExcludingGoodwill"),
}

RATIOS = ("net_margin", "gross_margin", "liabilities_to_assets", "return_on_equity")


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _annual(start: str | None, end: str) -> bool:
    if not start:
        return False
    try:
        return 300 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 430
    except ValueError:
        return False


def select_raw(payload: Mapping[str, Any], tags: Sequence[tuple[str, str]], *,
               annual: bool, reference_end: str | None = None) -> dict[str, Any] | None:
    """Select for the highest-priority tag that reports a usable observation.

    Within the tag the latest period wins (or ``reference_end`` when given), and within
    the period the latest-filed observation wins. Those rules are re-implemented here
    rather than reusing the normaliser, so agreement between the two is evidence.
    """
    namespaces = payload.get("facts") or {}
    for namespace, tag in tags:
        element = (namespaces.get(namespace) or {}).get(tag)
        if not isinstance(element, dict):
            continue
        candidates: list[dict[str, Any]] = []
        for unit, observations in (element.get("units") or {}).items():
            if unit not in {"USD", "USD/shares", "shares"}:
                continue
            for observation in observations or []:
                if not isinstance(observation, dict):
                    continue
                value = _decimal(observation.get("val"))
                observation_end = observation.get("end")
                if value is None or not isinstance(observation_end, str):
                    continue
                if reference_end is not None and reference_end != observation_end:
                    continue
                if annual and not _annual(observation.get("start"), observation_end):
                    continue
                if not annual and observation.get("start"):
                    continue
                candidates.append({
                    "value": value, "end": observation_end,
                    "start": observation.get("start"),
                    "filed": str(observation.get("filed") or ""),
                    "accession": str(observation.get("accn") or ""),
                    "form": str(observation.get("form") or ""),
                    "tag": f"{namespace}:{tag}",
                })
        if not candidates:
            continue
        latest_end = reference_end or max(item["end"] for item in candidates)
        same_period = [item for item in candidates if item["end"] == latest_end]
        same_period.sort(key=lambda item: (item["filed"], item["accession"]))
        return same_period[-1]
    return None


def _latest_annual_end(payload: Mapping[str, Any]) -> str | None:
    ends: list[str] = []
    for element in (payload.get("facts") or {}).get("us-gaap", {}).values():
        for observations in (element.get("units") or {}).values():
            for observation in observations or []:
                start, end = observation.get("start"), observation.get("end")
                if isinstance(start, str) and isinstance(end, str) and _annual(start, end):
                    ends.append(end)
    return max(ends) if ends else None


def _tag_variants(payload: Mapping[str, Any], tags: Sequence[tuple[str, str]], end: str | None, *,
                  annual: bool) -> dict[str, Decimal]:
    """Value per contract tag at the reference period, for tracing tag-choice divergences."""
    variants: dict[str, Decimal] = {}
    for namespace, tag in tags:
        item = select_raw(payload, [(namespace, tag)], annual=annual, reference_end=end)
        if item is not None:
            variants[f"{namespace}:{tag}"] = item["value"]
    return variants


def _ratios(values: Mapping[str, Decimal | None]) -> dict[str, float | None]:
    def ratio(numerator: str, denominator: str) -> float | None:
        top, bottom = values.get(numerator), values.get(denominator)
        if top is None or bottom in (None, 0):
            return None
        return float(top / bottom)

    revenue = values.get("revenue")
    gross = values.get("gross_profit")
    if gross is None and revenue is not None and values.get("cost_of_revenue") is not None:
        gross = revenue - values["cost_of_revenue"]
    augmented = dict(values)
    augmented["gross_profit"] = gross
    return {
        "net_margin": ratio("net_income", "revenue"),
        "gross_margin": ratio("gross_profit", "revenue"),
        "liabilities_to_assets": ratio("liabilities", "assets"),
        "return_on_equity": ratio("net_income", "equity"),
    }


def _strata(payload: Mapping[str, Any], *, restated: bool, non_december: bool,
            missing: bool, foreign: bool) -> list[str]:
    tags = set()
    for namespace, elements in (payload.get("facts") or {}).items():
        if isinstance(elements, dict):
            tags.update(elements)
    found = [name for name, markers in STRATUM_TAGS.items() if tags & set(markers)]
    if not found:
        found = ["industrial"]
    if foreign:
        found.append("foreign_issuer")
    if restated:
        found.append("restated")
    if non_december:
        found.append("non_december_fiscal_year")
    if missing:
        found.append("incomplete")
    return found


def _latest_filing_flags(payload: Mapping[str, Any]) -> tuple[bool, bool]:
    restated = False
    latest_month = 0
    for elements in (payload.get("facts") or {}).values():
        if not isinstance(elements, dict):
            continue
        for element in elements.values():
            if not isinstance(element, dict):
                continue
            for observations in (element.get("units") or {}).values():
                for observation in observations or []:
                    if not isinstance(observation, dict):
                        continue
                    if str(observation.get("form") or "").upper().endswith("/A"):
                        restated = True
                    end = observation.get("end")
                    if isinstance(end, str) and len(end) >= 7:
                        try:
                            latest_month = max(latest_month, int(end[5:7]))
                        except ValueError:
                            continue
    return restated, bool(latest_month and latest_month != 12)


def build_corpus(archive: Path, *, sample_size: int, corpus_size: int,
                 build_root: Path) -> tuple[dict, list[dict]]:
    """Freeze a stratified sample and build the columnar dataset over exactly it."""
    with zipfile.ZipFile(archive) as bundle:
        names = sorted(name for name in bundle.namelist() if name.endswith(".json"))
        step = max(1, len(names) // sample_size)
        sampled = names[::step][:sample_size]
        candidates: list[dict[str, Any]] = []
        for name in sampled:
            try:
                payload = json.loads(bundle.read(name))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            cik_value = payload.get("cik")
            if cik_value is None:
                continue
            cik = normalize_cik(str(cik_value))
            restated, non_december = _latest_filing_flags(payload)
            foreign = any(key in (payload.get("facts") or {}) for key in ("ifrs-full", "ifrs"))
            raw = {key: select_raw(payload, tags, annual=key not in {"assets", "liabilities", "equity"})
                   for key, tags in TAG_PRIORITY.items()}
            missing = raw["assets"] is None or raw["revenue"] is None
            candidates.append({
                "member": name, "cik": cik,
                "entity_name": str(payload.get("entityName") or f"CIK {cik}"),
                "strata": _strata(payload, restated=restated, non_december=non_december,
                                  missing=missing, foreign=foreign),
                "restated": restated, "non_december": non_december, "foreign": foreign,
                "missing_basic_inputs": missing,
            })
    # Round-robin by stratum so the corpus covers every category before it fills up.
    by_stratum: dict[str, list[dict]] = {}
    for item in candidates:
        for stratum in item["strata"]:
            by_stratum.setdefault(stratum, []).append(item)
    chosen: list[dict] = []
    seen: set[str] = set()
    while len(chosen) < min(corpus_size, len(candidates)):
        progress = False
        for stratum in sorted(by_stratum):
            for item in by_stratum[stratum]:
                if item["cik"] in seen:
                    continue
                chosen.append(item)
                seen.add(item["cik"])
                progress = True
                break
            if len(chosen) >= min(corpus_size, len(candidates)):
                break
        if not progress:
            break
    manifest = build_from_archive(archive, build_root, snapshot_id="validation-corpus",
                                  member_names=[item["member"] for item in chosen])
    corpus = {
        "schema": "atlas.open_data.financial_validation_corpus.v1",
        "generated_at": iso(utcnow()),
        "archive": {"path": str(archive), "bytes": archive.stat().st_size},
        "sampling": {"every_nth_member": step, "sampled": len(sampled),
                     "candidates": len(candidates), "selected": len(chosen),
                     "strata": dict(Counter(s for item in chosen for s in item["strata"]))},
        "columnar": {"root": str(build_root), "companies": manifest["companies"],
                     "records": manifest["records"]},
        "issuers": chosen,
    }
    return corpus, chosen


def validate(corpus: Mapping[str, Any], root: Path) -> dict[str, Any]:
    columnar = ColumnarEvidence(root)
    results: list[dict[str, Any]] = []
    bundle = zipfile.ZipFile(corpus["archive"]["path"])
    try:
        for issuer in corpus["issuers"]:
            cik = issuer["cik"]
            payload = json.loads(bundle.read(issuer["member"]))
            # The reference period is chosen once, from the source alone: the latest
            # fiscal-year end anywhere in the payload. Selecting a period per concept
            # (the earlier version of this script) compared a 10-Q balance sheet with a
            # 10-K income statement and produced false mismatches.
            period_end = _latest_annual_end(payload)
            raw = {key: select_raw(payload, tags, annual=key not in {"assets", "liabilities", "equity"},
                                   reference_end=period_end)
                   for key, tags in TAG_PRIORITY.items()}
            raw_values = {key: (item["value"] if item else None) for key, item in raw.items()}
            atlas = columnar.statement(cik, period_end=period_end) if period_end else {"concepts": {}}
            comparisons = {}
            for concept, value in raw_values.items():
                reported = atlas["concepts"].get(concept)
                if value is None and reported is None:
                    comparisons[concept] = {"status": "absent_both"}
                elif value is None:
                    comparisons[concept] = {"status": "atlas_only", "atlas": reported}
                elif reported is None:
                    comparisons[concept] = {"status": "source_only", "source": str(value)}
                elif Decimal(str(reported)) == value:
                    comparisons[concept] = {"status": "match", "value": str(value)}
                else:
                    variants = _tag_variants(payload, TAG_PRIORITY[concept], period_end,
                                             annual=concept not in {"assets", "liabilities", "equity"})
                    traced = [name for name, candidate in variants.items()
                              if Decimal(str(reported)) == candidate]
                    if traced:
                        comparisons[concept] = {"status": "tag_variant", "tag": traced[0],
                                                "source": str(value), "atlas": str(reported)}
                    else:
                        comparisons[concept] = {"status": "mismatch", "source": str(value),
                                                "atlas": str(reported)}
            raw_ratios = _ratios(raw_values)
            atlas_values = {key: (Decimal(str(atlas["concepts"][key]))
                                  if key in atlas["concepts"] else None)
                            for key in raw_values}
            atlas_ratios = _ratios(atlas_values)

            cutoff = {"tested": False}
            revenue = raw.get("revenue")
            if revenue:
                availability = (atlas["evidence"].get("revenue") or {}).get("availability_time")
                if availability:
                    day = date.fromisoformat(str(availability)[:10])
                    before = columnar.point_in_time(cik, f"{day.isoformat()}T00:00:00Z", "revenue")
                    after = columnar.point_in_time(cik, f"{(day + timedelta(days=2)).isoformat()}T00:00:00Z",
                                                   "revenue")
                    cutoff = {"tested": True, "availability": availability,
                              "before_count": len(before), "after_count": len(after),
                              "ok": len(after) > len(before)}

            matches = sum(1 for item in comparisons.values() if item["status"] == "match")
            mismatches = sum(1 for item in comparisons.values() if item["status"] == "mismatch")
            ratio_mismatches = [
                name for name in RATIOS
                if raw_ratios[name] is not None and atlas_ratios[name] is not None
                and abs(raw_ratios[name] - atlas_ratios[name]) > 1e-9
            ]
            results.append({
                "cik": cik, "entity_name": issuer["entity_name"], "strata": issuer["strata"],
                "period_end": period_end,
                "comparisons": comparisons,
                "ratios": {"source": raw_ratios, "atlas": atlas_ratios,
                           "mismatches": ratio_mismatches},
                "cutoff": cutoff,
            })
    finally:
        bundle.close()
        columnar.close()

    def count(status: str) -> int:
        return sum(1 for item in results for comparison in item["comparisons"].values()
                   if comparison["status"] == status)

    cutoff_tested = [item for item in results if item["cutoff"].get("tested")]
    return {
        "schema": "atlas.open_data.financial_validation.v1",
        "generated_at": iso(utcnow()),
        "issuers": len(results),
        "strata": dict(Counter(s for item in results for s in item["strata"])),
        "concept_comparisons": {
            "match": count("match"),
            "tag_variant": count("tag_variant"),
            "mismatch": count("mismatch"),
            "source_only": count("source_only"),
            "atlas_only": count("atlas_only"),
            "absent_both": count("absent_both"),
        },
        "ratio_comparisons": {
            "checked": sum(1 for item in results for name in RATIOS
                           if item["ratios"]["source"][name] is not None
                           and item["ratios"]["atlas"][name] is not None),
            "mismatches": sum(len(item["ratios"]["mismatches"]) for item in results),
        },
        "historical_cutoff": {
            "tested": len(cutoff_tested),
            "passed": sum(1 for item in cutoff_tested if item["cutoff"]["ok"]),
        },
        "valuation_methods": {
            "executed": [],
            "unavailable": ["dcf", "comparables", "residual_income", "reverse_dcf"],
            "reason": ("price-dependent methods require legitimate market prices; no such "
                       "source has been acquired, so success is not claimed for them"),
        },
        "limitations": [
            "The corpus is sampled across the archive, not the benchmark's first N members.",
            "Issuers whose facts lack the priority tags are compared only where both sides "
            "report the concept; source_only and atlas_only are recorded, not counted as matches.",
            "Extraction agreement is not a valuation-accuracy test.",
        ],
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive")
    parser.add_argument("--root", default="/tmp/atlas_p4")
    parser.add_argument("--sample-size", type=int, default=700)
    parser.add_argument("--corpus-size", type=int, default=120)
    parser.add_argument("--build-root", default="/tmp/atlas_p4/validation-corpus")
    parser.add_argument("--out", default=str(ROOT / "artifacts/open_data_financial_validation.json"))
    parser.add_argument("--corpus-out", default=str(ROOT / "artifacts/open_data_financial_corpus.json"))
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
    corpus, _ = build_corpus(archive, sample_size=args.sample_size,
                             corpus_size=args.corpus_size, build_root=Path(args.build_root))
    Path(args.corpus_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.corpus_out).write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")
    report = validate(corpus, Path(args.build_root))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "issuers", "concept_comparisons", "ratio_comparisons", "historical_cutoff",
        "strata")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
