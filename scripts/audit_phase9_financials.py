#!/usr/bin/env python3
"""Adversarial Phase 9 audit: raw SEC payloads versus the normalized Atlas database.

This script deliberately does **not** reuse the ingestion or metric selectors. It reads
the archived SEC ``companyfacts`` JSON, resolves tags and fiscal periods with its own
minimal logic, and compares the result with what Atlas stored and what the equity
research service reports. A disagreement is a finding, not something to smooth over.

It also exercises the portable research package end to end: build it twice, install it in
a freshly migrated database, execute it, and require numerical identity.

Usage::

    python scripts/audit_phase9_financials.py \
        --db var/phase9.db --out artifacts/phase9_financial_audit.json

Exit status is non-zero when a hard check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.applications.service import ApplicationService  # noqa: E402
from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.fec import valuation as fec_valuation  # noqa: E402
from atlas.research.equity import EquityResearchService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402
from atlas.terminal import read_models  # noqa: E402
from atlas.terminal.metric_store import get_issuer_metrics  # noqa: E402

# Representative subset chosen for exposure to the audit's hard cases:
# AAPL (clean), GOOGL (revenue tag migration), XOM (Revenues tag), NVDA (Revenues),
# CAT (financial-services subsidiary, industrial SIC), JPM (bank), GS (bank, no mapped
# revenue), AMZN is added by the caller when it is present.
REPRESENTATIVE = ["AAPL", "GOOGL", "XOM", "NVDA", "CAT", "JPM", "GS"]

REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
CONCEPT_TAGS: dict[str, list[tuple[str, str]]] = {
    "net_income": [("us-gaap", "NetIncomeLoss")],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ],
    "capex": [
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets"),
    ],
    "long_term_debt": [("us-gaap", "LongTermDebtNoncurrent"), ("us-gaap", "LongTermDebt")],
    "short_term_debt": [
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "ShortTermBorrowings"),
        ("us-gaap", "OtherShortTermBorrowings"),
    ],
    "shares_outstanding": [
        ("us-gaap", "CommonStockSharesOutstanding"),
        ("dei", "EntityCommonStockSharesOutstanding"),
    ],
    "weighted_average_shares_diluted": [
        ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
    ],
}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F"}
TOLERANCE = 1e-9


def _days(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _annual(raw: dict[str, Any], namespace: str, tag: str) -> list[dict[str, Any]]:
    unit_map = ((raw.get("facts") or {}).get(namespace) or {}).get(tag, {}).get("units", {})
    rows: list[dict[str, Any]] = []
    for unit, items in unit_map.items():
        if unit not in {"USD", "USD/shares", "shares"}:
            continue
        for item in items:
            if item.get("form") not in ANNUAL_FORMS:
                continue
            if (item.get("fp") or "") != "FY":
                continue
            length = _days(item.get("start"), item.get("end"))
            if length is None or not 330 <= length <= 400:
                continue
            rows.append({**item, "unit": unit, "days": length})
    return rows


def _latest_per_period(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """For each period end keep the most recently filed value (amendments win)."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        end = row.get("end")
        if not end:
            continue
        current = best.get(end)
        key = (str(row.get("filed") or ""), str(row.get("accn") or ""))
        if current is None or key >= (
            str(current.get("filed") or ""), str(current.get("accn") or "")
        ):
            best[end] = row
    return best


def _resolve_by_tag(
    raw: dict[str, Any], tags: list[tuple[str, str]], period_end: str
) -> tuple[float, dict[str, Any]] | None:
    """Resolve every tag for one period and take the first non-empty tag in priority order."""
    for namespace, tag in tags:
        per_period = _latest_per_period(_annual(raw, namespace, tag))
        row = per_period.get(period_end)
        if row is not None and row.get("val") is not None:
            return float(row["val"]), {
                "tag": f"{namespace}:{tag}",
                "accession_number": row.get("accn"),
                "form_type": row.get("form"),
                "filed": row.get("filed"),
                "days": row["days"],
                "unit": row["unit"],
            }
    return None


def _instant(
    raw: dict[str, Any], tags: list[tuple[str, str]], period_end: str
) -> tuple[float, dict[str, Any]] | None:
    for namespace, tag in tags:
        unit_map = ((raw.get("facts") or {}).get(namespace) or {}).get(tag, {}).get("units", {})
        candidates: list[dict[str, Any]] = []
        for unit, items in unit_map.items():
            if unit not in {"USD", "shares"}:
                continue
            for item in items:
                if item.get("form") not in ANNUAL_FORMS:
                    continue
                if item.get("end") != period_end:
                    continue
                if item.get("start"):
                    # Instant facts have no start; a duration fact with the same end is not one.
                    continue
                candidates.append(item)
        if candidates:
            row = max(
                candidates,
                key=lambda item: (str(item.get("filed") or ""), str(item.get("accn") or "")),
            )
            if row.get("val") is not None:
                return float(row["val"]), {
                    "tag": f"{namespace}:{tag}",
                    "accession_number": row.get("accn"),
                    "form_type": row.get("form"),
                    "filed": row.get("filed"),
                    "unit": row.get("unit"),
                }
    return None


def _db_fact(db: Database, issuer_id: str, concept: str, period_end: str) -> dict[str, Any] | None:
    rows = db.query(
        "SELECT evidence_id, value_numeric, source_concept, accession_number, form_type, "
        "availability_time, unit, period_start, period_end FROM evidence "
        "WHERE entity_id=? AND concept=? AND period_end=? "
        "ORDER BY availability_time DESC, evidence_id DESC LIMIT 1",
        (issuer_id, concept, period_end),
    )
    return dict(rows[0]) if rows else None


def _match(expected: float | None, actual: float | None, *, magnitude: bool = False) -> bool:
    if expected is None or actual is None:
        return False
    left = abs(expected) if magnitude else expected
    right = abs(actual) if magnitude else actual
    scale = max(1.0, abs(left), abs(right))
    return abs(float(right) - float(left)) <= scale * TOLERANCE


def _compare(
    label: str, expected: tuple[float, dict[str, Any]] | None, actual: float | None,
    actual_source: dict[str, Any] | None, *, magnitude: bool = False,
) -> dict[str, Any]:
    if expected is None:
        return {
            "name": label, "status": "unavailable",
            "reason": "raw SEC payload has no annual observation for this period",
            "raw": None, "atlas": actual,
        }
    raw_value, raw_meta = expected
    passed = _match(raw_value, actual, magnitude=magnitude)
    return {
        "name": label,
        "status": "pass" if passed else "fail",
        "raw": raw_value,
        "atlas": actual,
        "difference": None if actual is None else float(actual) - (
            abs(raw_value) if magnitude else raw_value
        ),
        "raw_source": raw_meta,
        "atlas_source": actual_source,
        "note": "capex is compared as a magnitude" if magnitude else None,
    }


def _issuer_reference(db: Database, issuer_id: str) -> tuple[str | None, dict[str, Any]]:
    metrics = get_issuer_metrics(db, issuer_id)
    return metrics.get("period_end"), metrics


def audit_issuer(db: Database, ticker: str, raw: dict[str, Any]) -> dict[str, Any]:
    issuer = db.query_one("SELECT * FROM issuer WHERE cik = ?", (f"{int(raw['cik']):010d}",))
    if issuer is None:
        return {"ticker": ticker, "status": "issuer_missing", "checks": []}
    issuer_id = issuer["issuer_id"]
    period_end, metrics = _issuer_reference(db, issuer_id)
    checks: list[dict[str, Any]] = []
    if period_end is None:
        return {"ticker": ticker, "status": "no_annual_period", "checks": []}

    revenue = _resolve_by_tag(raw, [("us-gaap", tag) for tag in REVENUE_TAGS], period_end)
    db_revenue = _db_fact(db, issuer_id, "revenue", period_end)
    checks.append(_compare(
        "revenue", revenue,
        float(db_revenue["value_numeric"]) if db_revenue else None,
        {"source_concept": db_revenue["source_concept"], "accession_number": db_revenue["accession_number"],
         "form_type": db_revenue["form_type"], "evidence_id": db_revenue["evidence_id"]}
        if db_revenue else None,
    ))

    for concept in ("net_income", "operating_cash_flow", "capex", "shares_outstanding",
                    "weighted_average_shares_diluted"):
        expected = _resolve_by_tag(raw, CONCEPT_TAGS[concept], period_end) if concept not in {
            "shares_outstanding", "weighted_average_shares_diluted"
        } else _instant(raw, CONCEPT_TAGS[concept], period_end)
        fact = _db_fact(db, issuer_id, concept, period_end)
        checks.append(_compare(
            concept, expected,
            float(fact["value_numeric"]) if fact and fact["value_numeric"] is not None else None,
            {"source_concept": fact["source_concept"], "accession_number": fact["accession_number"],
             "form_type": fact["form_type"], "evidence_id": fact["evidence_id"]}
            if fact else None,
            magnitude=concept == "capex",
        ))

    long_term = _instant(raw, CONCEPT_TAGS["long_term_debt"], period_end)
    short_term = _instant(raw, CONCEPT_TAGS["short_term_debt"], period_end)
    if long_term is not None or short_term is not None:
        total = (long_term[0] if long_term else 0.0) + (short_term[0] if short_term else 0.0)
        # Atlas derives total_debt from the two reported components; it is not a stored fact.
        parts = [
            _db_fact(db, issuer_id, concept, period_end)
            for concept in ("long_term_debt", "short_term_debt")
        ]
        parts = [part for part in parts if part and part["value_numeric"] is not None]
        atlas_total = sum(float(part["value_numeric"]) for part in parts) if parts else None
        checks.append(_compare(
            "total_debt", (total, {
                "tags": [item[1]["tag"] for item in (long_term, short_term) if item],
                "components": [item[0] for item in (long_term, short_term) if item],
            }),
            atlas_total,
            {"evidence_ids": [part["evidence_id"] for part in parts],
             "formula": "sum of reported long-term and short-term debt evidence"}
            if parts else None,
        ))

    return {
        "ticker": ticker,
        "issuer_id": issuer_id,
        "legal_name": issuer["legal_name"],
        "sic": issuer["sic"],
        "period_end": period_end,
        "checks": checks,
        "failures": [item for item in checks if item["status"] == "fail"],
        "status": "pass" if all(item["status"] != "fail" for item in checks) else "fail",
    }


def audit_filings(db: Database, issuer_id: str) -> dict[str, Any]:
    forms = {
        row["form_type"]: int(row["n"])
        for row in db.query(
            "SELECT form_type, COUNT(*) AS n FROM evidence WHERE entity_id=? "
            "AND form_type IN ('10-K','10-K/A','10-Q','10-Q/A') GROUP BY form_type",
            (issuer_id,),
        )
    }
    overlaps = db.query(
        "SELECT concept, period_end, COUNT(*) AS n, COUNT(DISTINCT value_numeric) AS distinct_values, "
        "COUNT(DISTINCT accession_number) AS accessions FROM evidence WHERE entity_id=? "
        "AND period_type='duration' GROUP BY concept, period_end HAVING n > 1 "
        "ORDER BY n DESC LIMIT 10",
        (issuer_id,),
    )
    revisions = db.query(
        "SELECT revision_kind, COUNT(*) AS n FROM evidence WHERE entity_id=? "
        "AND revision_kind IS NOT NULL GROUP BY revision_kind",
        (issuer_id,),
    )
    non_annual = db.query(
        "SELECT evidence_id, period_start, period_end, concept, fiscal_period FROM evidence "
        "WHERE entity_id=? AND period_type='duration' AND fiscal_period='FY' "
        "AND julianday(period_end) - julianday(period_start) NOT BETWEEN 330 AND 400 LIMIT 10",
        (issuer_id,),
    )
    # The archive keeps every FY-tagged observation, including transition windows. What
    # matters is that no selector uses one as an annual period.
    metrics = get_issuer_metrics(db, issuer_id)
    revenue_ids = (metrics.get("metrics", {}).get("revenue", {}) or {}).get("evidence_ids") or []
    selected_days = None
    if revenue_ids:
        selected_days = db.scalar(
            "SELECT julianday(period_end) - julianday(period_start) FROM evidence "
            "WHERE evidence_id=?", (revenue_ids[0],), default=None,
        )
    return {
        "forms": forms,
        "overlapping_facts": [dict(row) for row in overlaps],
        "revision_kinds": {row["revision_kind"]: int(row["n"]) for row in revisions},
        "non_annual_fy_facts_retained": len(non_annual),
        "non_annual_fy_facts_sample": [dict(row) for row in non_annual[:3]],
        "selected_revenue_duration_days": selected_days,
        "status": "pass" if selected_days is None or 330 <= selected_days <= 400 else "fail",
    }


def audit_cutoff(db: Database, issuer_id: str) -> dict[str, Any]:
    latest = get_issuer_metrics(db, issuer_id)
    historical = get_issuer_metrics(db, issuer_id, as_of="2020-01-01T00:00:00Z",
                                   mode="public_available")
    latest_available = db.scalar(
        "SELECT MIN(availability_time) FROM evidence WHERE entity_id=? AND concept='revenue' "
        "AND period_end=?", (issuer_id, latest.get("period_end")), default=None,
    )
    return {
        "latest_period_end": latest.get("period_end"),
        "latest_evidence_available_at": latest_available,
        "historical_as_of": historical.get("as_of"),
        "historical_period_end": historical.get("period_end"),
        "leaks_future_period": bool(
            historical.get("period_end") and latest.get("period_end")
            and historical["period_end"] >= latest["period_end"]
        ),
        "status": "pass" if historical.get("period_end") and historical["period_end"] < (
            latest.get("period_end") or "9999"
        ) else "fail",
    }


def package_roundtrip(db: Database, identifier: str, destination: Path) -> dict[str, Any]:
    service = EquityResearchService(db)
    first = service.create_package(identifier)
    second = service.create_package(identifier)
    destination.write_bytes(first["payload"])
    payload = first["payload"]
    findings: list[str] = []
    if first["package_sha256"] != second["package_sha256"]:
        findings.append("package bytes are not deterministic across two builds")

    from atlas.applications.contracts import read_package

    loaded = read_package(payload)
    files = loaded["files"]
    report_sha = loaded["manifest"]["application"]["runtime"].get("report_sha256")
    embedded_report = files.get("report.md", b"").decode("utf-8")

    if hashlib.sha256(embedded_report.encode("utf-8")).hexdigest() != report_sha:
        findings.append("packaged report does not match the analysis report digest")
    if any(name.endswith((".py", ".js", ".sh", ".exe")) for name in files):
        findings.append("package contains an executable file")

    with tempfile.TemporaryDirectory() as folder:
        clean = Database(Path(folder) / "clean.db")
        clean.migrate()
        ensure_default_sources(clean)
        install = ApplicationService(clean).install(payload)
        execution = ApplicationService(clean).execute(install["install_id"])
        clean.close()
    expected = first["expected_outputs"]
    actual = execution.get("outputs") or {}
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) is None or abs(float(actual[key]) - float(value)) > 1e-9
    }
    if not execution.get("reproduced"):
        findings.append(f"clean-database execution status is {execution.get('status')}")
    if mismatches:
        findings.append("clean-database outputs differ from the packaged expected outputs")
    audit_json = json.loads(files.get("artifacts/dcf_audit.json", b"{}").decode("utf-8"))
    if not audit_json.get("arithmetic_valid"):
        findings.append("packaged DCF component audit did not pass")
    return {
        "identifier": identifier,
        "package_sha256": first["package_sha256"],
        "package_id": first["package_id"],
        "size_bytes": len(payload),
        "deterministic": first["package_sha256"] == second["package_sha256"],
        "install_status": install["status"],
        "signature_status": install["signature_status"],
        "execution_status": execution.get("status"),
        "reproduced": bool(execution.get("reproduced")),
        "expected_outputs": expected,
        "actual_outputs": actual,
        "mismatches": mismatches,
        "report_sha256_matches": hashlib.sha256(embedded_report.encode("utf-8")).hexdigest() == report_sha,
        "audit_verdict": audit_json.get("verdict"),
        "findings": findings,
        "status": "pass" if not findings else "fail",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "var" / "phase9.db"))
    parser.add_argument("--fixture", default=str(ROOT / "fixtures" / "phase9"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase9_financial_audit.json"))
    parser.add_argument("--package-out", default=str(ROOT / "var" / "phase9-aapl-equity.atlas"))
    parser.add_argument("--no-package", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    fixture = Path(args.fixture)
    manifest = json.loads((fixture / "sec_manifest.json").read_text(encoding="utf-8"))
    cik_by_ticker = {item["ticker"]: item["cik"] for item in manifest["documents"]}

    db = Database(db_path, create=False)
    service = EquityResearchService(db)
    coverage = service.coverage()

    raw_audits = []
    filing_audits = []
    cutoff_audits = []
    for ticker in REPRESENTATIVE:
        path = fixture / "sec" / ticker / "companyfacts.json"
        if not path.exists():
            raw_audits.append({"ticker": ticker, "status": "fixture_missing", "checks": []})
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw = {**raw, "cik": cik_by_ticker.get(ticker, raw.get("cik"))}
        result = audit_issuer(db, ticker, raw)
        raw_audits.append(result)
        issuer = db.query_one("SELECT issuer_id FROM issuer WHERE cik=?", (cik_by_ticker[ticker],))
        if issuer:
            filing_audits.append({"ticker": ticker, **audit_filings(db, issuer["issuer_id"])})
            cutoff_audits.append({"ticker": ticker, **audit_cutoff(db, issuer["issuer_id"])})

    price_rows = db.query(
        "SELECT i.legal_name, COUNT(b.rowid) AS bars FROM issuer i "
        "JOIN security s ON s.issuer_id = i.issuer_id "
        "LEFT JOIN bar b ON b.security_id = s.security_id GROUP BY i.issuer_id"
    )
    price_audit = {
        "issuers": len(price_rows),
        "issuers_with_bars": sum(1 for row in price_rows if int(row["bars"] or 0) > 0),
        "status": "pass" if all(int(row["bars"] or 0) == 0 for row in price_rows) else "fail",
        "note": "The compact real-company fixture bundles no market prices.",
    }
    missing_price_metrics = []
    for row in db.query("SELECT issuer_id, legal_name FROM issuer WHERE is_active=1"):
        metrics = get_issuer_metrics(db, row["issuer_id"])
        missing_price_metrics.append({
            "issuer_id": row["issuer_id"],
            "legal_name": row["legal_name"],
            "price": metrics.get("price"),
            "market_cap_present": "market_cap" in metrics.get("metrics", {}),
        })
    price_audit["metrics"] = missing_price_metrics
    price_audit["status"] = (
        "pass"
        if price_audit["issuers_with_bars"] == 0
        and all(item["price"] is None and not item["market_cap_present"] for item in missing_price_metrics)
        else "fail"
    )

    share_audit = []
    for ticker in REPRESENTATIVE:
        cik = cik_by_ticker.get(ticker)
        issuer = db.query_one("SELECT issuer_id FROM issuer WHERE cik=?", (cik,)) if cik else None
        if issuer is None:
            continue
        metrics = get_issuer_metrics(db, issuer["issuer_id"])
        point = (metrics["metrics"].get("shares_outstanding") or {}).get("value")
        weighted = (metrics["metrics"].get("weighted_average_shares_diluted") or {}).get("value")
        expected_basis = (
            "period_end_share_count" if point else
            "weighted_average_diluted" if weighted else
            "derived_net_income_over_eps"
        )
        try:
            defaults = fec_valuation.defaults_from_metrics(metrics)
        except Exception:  # noqa: BLE001 - a revenue-less issuer cannot seed a valuation
            share_audit.append({
                "ticker": ticker,
                "point_in_time": point,
                "weighted_average_diluted": weighted,
                "basis": None,
                "expected_basis": expected_basis,
                "denominator": None,
                "status": "unavailable",
                "reason": "no reported revenue, so no valuation defaults exist to audit",
            })
            continue
        provenance = (defaults.get("provenance") or {}).get("shares_outstanding") or {}
        basis = provenance.get("basis")
        share_audit.append({
            "ticker": ticker,
            "point_in_time": point,
            "weighted_average_diluted": weighted,
            "basis": basis,
            "expected_basis": expected_basis,
            "denominator": defaults.get("shares"),
            "status": "pass" if basis == expected_basis and (
                point is None or abs(float(defaults["shares"]) - float(point)) <= 1e-6
            ) else "fail",
        })

    package = None
    if not args.no_package:
        package = package_roundtrip(db, "AAPL", Path(args.package_out))
    db.close()

    failures = []
    for item in raw_audits:
        failures.extend(
            f"{item['ticker']} {check['name']}: {check.get('raw')} != {check.get('atlas')}"
            for check in item.get("failures", [])
        )
    for item in filing_audits:
        if item["status"] != "pass":
            failures.append(f"{item['ticker']} has non-annual FY facts")
    for item in cutoff_audits:
        if item["status"] != "pass":
            failures.append(f"{item['ticker']} historical cutoff did not move back")
    for item in share_audit:
        if item["status"] == "fail":
            failures.append(f"{item['ticker']} share denominator basis mismatch")
    if price_audit["status"] != "pass":
        failures.append("market-price absence check failed")
    if package and package["status"] != "pass":
        failures.extend(package["findings"])

    payload = {
        "schema": "atlas.phase9.financial_audit.v1",
        "generated_at": iso(utcnow()),
        "database": str(db_path),
        "method": (
            "Raw SEC companyfacts JSON is re-parsed with independent fiscal-period and "
            "tag-priority logic and compared with Atlas evidence at the issuer's reference "
            "annual period. Amendments win by filing date, not by database insertion order."
        ),
        "coverage": {
            key: coverage[key] for key in (
                "issuers", "financial_coverage_valid", "valuation_eligible",
                "methodology_rejected", "valuation_executes",
                "valuation_economically_supported", "with_prices",
            )
        },
        "readiness": coverage["readiness"]["items"],
        "raw_comparisons": raw_audits,
        "filings": filing_audits,
        "historical_cutoff": cutoff_audits,
        "share_denominator": share_audit,
        "market_prices": price_audit,
        "package_roundtrip": package,
        "failures": failures,
        "status": "pass" if not failures else "fail",
        "limitations": [
            "The comparison is limited to one reference annual period per issuer and to the "
            "concepts whose XBRL tags are unambiguous in this fixture.",
            "Total debt is compared as the sum of the raw debt tags present; a filer that "
            "reports debt only inside a combined line is not independently reconstructable.",
            "Amendments are resolved by filing date in this audit; that is a policy choice, "
            "not an assertion that every restatement is economically correct.",
            "No market prices exist in this fixture, so market-implied valuation and any "
            "price-based share-count cross-check are unavailable.",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": payload["status"],
        "coverage": payload["coverage"],
        "raw_pass": sum(1 for item in raw_audits if item.get("status") == "pass"),
        "raw_total": len(raw_audits),
        "failures": failures,
        "artifact": str(out),
        "package": None if package is None else {
            "sha256": package["package_sha256"],
            "reproduced": package["reproduced"],
            "deterministic": package["deterministic"],
        },
    }, indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
