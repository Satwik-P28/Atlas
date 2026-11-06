"""Integrated, source-grounded equity research over existing Atlas engines.

This module is deliberately an orchestration layer. It does not reconstruct financial
statements, calculate metrics or value a company with new mathematics: it composes the
point-in-time read models, the existing DCF/FEC runtime and the portable application
contract. The report is deterministic and works without an LLM. Every numeric value keeps
its evidence ids, and missing inputs are reported instead of filled with synthetic data.
"""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from typing import Any, Iterable

from ..applications.contracts import (
    APPLICATION_SCHEMA,
    RUNTIME_VERSION,
    build_package,
    pretty,
)
from ..applications.rights import DataRightsEngine
from ..core.concepts import CONCEPTS
from ..core.errors import MissingDataError, ValidationError
from ..core.temporal import AsOfMode, iso, utcnow
from ..entities.master import SecurityMaster
from ..fec import valuation as fec_valuation
from ..fec.compiler import COMPILER_VERSION
from . import institutions, prices
from .eligibility import (
    DCF,
    JUSTIFIED_EARNINGS,
    RESIDUAL_INCOME,
    build_contract,
    classify_business_model,
    missing_inputs,
)
from ..storage.db import Database
from ..terminal import read_models
from ..terminal.metric_store import get_issuer_metrics
from ..research import validation as research_validation

EQUITY_SCHEMA = "atlas.equity_research.v1"
REPORT_SCHEMA = "atlas.equity_research.report.v1"
APPLICATION_ID_PREFIX = "atlas.firstparty.equity-research"
REPORT_VERSION = "1.0.0"
CORE_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capex",
    "assets",
    "liabilities",
    "equity",
    "cash_and_equivalents",
    "eps_diluted",
)
_DATA_ROLES = {
    "approved_source_snapshot",
    "analysis_result",
    "model_artifact",
    "scenario_result",
}


def _value(metrics: dict[str, Any], key: str) -> float | None:
    item = metrics.get("metrics", {}).get(key)
    if not isinstance(item, dict) or item.get("value") is None:
        return None
    try:
        return float(item["value"])
    except (TypeError, ValueError):
        return None


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{Decimal(str(value)):,.2f}"


def _pct(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


def _excerpt(value: Any, limit: int = 240) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# SIC divisions H (finance, insurance and real estate) and the adjacent broker/insurer
# codes. The guard is deliberately explicit: an unlevered FCFF DCF is not a valid model
# for a bank or insurer, so Atlas refuses rather than dressing a generic DCF as research.
FINANCIAL_INSTITUTION_SIC = (6000, 6799)
VALUATION_METHOD = "unlevered_fcff_dcf"
CORE_VALUATION_CONCEPTS = (
    "revenue",
    "net_income",
    "operating_cash_flow",
    "assets",
    "liabilities",
    "equity",
)
_ARITHMETIC_TOLERANCE = 1e-9


def _sic_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip().split("-")[0])
    except (TypeError, ValueError):
        return None


def _valuation_eligibility(
    issuer: dict[str, Any],
    missing: Iterable[str],
    available: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Decide which methodology is admissible and whether its inputs are present.

    The industrial DCF guard is unchanged: a financial institution still returns
    ``unsupported_methodology`` for that method. What changed is that a second, valid
    method is now named and evaluated instead of leaving the issuer with no analysis.
    """
    classification = classify_business_model(issuer.get("sic"))
    sic = classification["sic"]
    missing = sorted(set(missing))
    if classification["method"] in (RESIDUAL_INCOME, JUSTIFIED_EARNINGS):
        method_missing = (
            missing_inputs(classification["method"], available)
            if available is not None else []
        )
        status = "unsupported_methodology" if not method_missing else "insufficient_data"
        return {
            "status": status,
            "method": classification["method"],
            "rejected_method": VALUATION_METHOD,
            "financial_institution": True,
            "business_model": classification["business_model"],
            "method_basis": classification["basis"],
            "sic": sic,
            "missing_inputs": method_missing,
            "reasons": [
                f"SIC {sic} identifies a {classification['business_model']}; an unlevered "
                "free-cash-flow-to-firm DCF is not an economically valid model here because debt "
                "and deposits are operating inputs and interest expense is an operating cost.",
                "Atlas applies "
                + (
                    "residual income on book value"
                    if classification["method"] == RESIDUAL_INCOME
                    else "justified earnings on diluted EPS"
                )
                + f" (`{classification['method']}`) instead: "
                + (
                    institutions.BANK_MODEL_VERSION
                    if classification["method"] == RESIDUAL_INCOME
                    else institutions.INSURER_MODEL_VERSION
                )
                + ".",
                (
                    "Required inputs for this method are missing: " + ", ".join(method_missing) + "."
                    if method_missing else
                    "All required inputs for this method are present in the evidence store."
                ),
            ],
            "required_remedy": (
                "additional reported facts before this method can execute" if method_missing else None
            ),
        }
    reasons = []
    if missing:
        reasons.append("Required valuation inputs are missing: " + ", ".join(missing) + ".")
    return {
        "status": "eligible" if not missing else "insufficient_data",
        "method": DCF,
        "rejected_method": None,
        "financial_institution": False,
        "business_model": classification["business_model"],
        "method_basis": classification["basis"],
        "sic": sic,
        "reasons": reasons,
        "required_remedy": None if not missing else "additional reported facts before valuation",
    }


def _without_timings(value: Any) -> Any:
    """Remove runtime timing fields before packaging.

    Execution traces record how long each node took. That is operational metadata, not
    research content, and including it makes two otherwise identical packages differ byte
    for byte. Timings are dropped here; every economic value and input is retained.
    """
    if isinstance(value, dict):
        return {
            key: _without_timings(item) for key, item in value.items()
            if key not in {"duration_ms", "elapsed_ms", "started_at", "finished_at"}
        }
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


_TRACE_RUNTIME_KEYS = {
    "duration_ms", "elapsed_ms", "started_at", "finished_at", "status", "cache_hit", "cached",
}


def _stable_trace(trace: Any) -> Any:
    """Drop runtime-only trace state so a package does not depend on a warm cache."""
    if isinstance(trace, dict):
        return {
            key: _stable_trace(item) for key, item in trace.items()
            if key not in _TRACE_RUNTIME_KEYS
        }
    if isinstance(trace, list):
        return [_stable_trace(item) for item in trace]
    return trace


def _series_value(value: Any) -> list[float]:
    if isinstance(value, dict):
        for key in ("values", "series", "items"):
            if key in value:
                return _series_value(value[key])
        return []
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value if item is not None]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)]
    return []


class EquityResearchService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.master = SecurityMaster(db)
        self.rights = DataRightsEngine(db)

    # ------------------------------------------------------------------ coverage
    def _ticker(self, issuer_id: str) -> str | None:
        """Resolve the issuer's common-stock ticker, not an affiliated ETN or note.

        A large bank can be the registrant for several listed instruments. At least one
        issuer in this universe is the registrant for an ETN, so picking the first security
        would label JPMorgan Chase with a note ticker. Unless a share-class source is
        available, the ranking below is a heuristic: the highest-confidence assignment (the
        coverage manifest declares one primary ticker per issuer), then stored bars, then the
        shortest un-suffixed ticker. `ticker_status` records that the identity is provisional.
        """
        best: str | None = None
        best_score: tuple[float, int, int, int, str] | None = None
        for security in self.master.securities_for_issuer(issuer_id):
            current = self.master.current_ticker(security["security_id"])
            if not current or not current.get("ticker"):
                continue
            rows = int(self.db.scalar(
                "SELECT COUNT(*) FROM bar WHERE security_id=?", (security["security_id"],), 0
            ) or 0)
            ticker = str(current["ticker"])
            score = (
                -float(current.get("confidence") or 0.0),
                -rows,
                1 if "-" in ticker else 0,
                len(ticker),
                ticker,
            )
            if best_score is None or score < best_score:
                best, best_score = ticker, score
        return best

    def _ticker_status(self, issuer_id: str) -> dict[str, Any]:
        selected = self._ticker(issuer_id)
        if selected is None:
            return {"ticker": None, "status": "missing", "candidates": [], "confidence": None}
        for security in self.master.securities_for_issuer(issuer_id):
            current = self.master.current_ticker(security["security_id"])
            if current and current.get("ticker") == selected:
                return {
                    "ticker": selected,
                    "status": current.get("status") or "unknown",
                    "confidence": current.get("confidence"),
                    "candidates": sorted({
                        str(item["ticker"])
                        for item in (
                            self.master.current_ticker(s["security_id"])
                            for s in self.master.securities_for_issuer(issuer_id)
                        )
                        if item and item.get("ticker")
                    }),
                    "note": current.get("evidence_note"),
                }
        return {"ticker": selected, "status": "unknown", "candidates": [], "confidence": None}

    def _issuer_coverage(self, issuer: dict[str, Any]) -> dict[str, Any]:
        issuer = dict(issuer)
        row = self.db.query_one(
            "SELECT COUNT(*) AS evidence, COUNT(DISTINCT concept) AS concepts, "
            "MIN(CASE WHEN period_type='duration' AND fiscal_period='FY' THEN period_end END) AS first_period, "
            "MAX(CASE WHEN period_type='duration' AND fiscal_period='FY' THEN period_end END) AS last_period, "
            "COUNT(DISTINCT CASE WHEN period_type='duration' AND fiscal_period='FY' THEN period_end END) AS annual_periods "
            "FROM evidence WHERE entity_id = ?",
            (issuer["issuer_id"],),
        )
        concepts = {
            item["concept"]
            for item in self.db.query(
                "SELECT DISTINCT concept FROM evidence WHERE entity_id = ?", (issuer["issuer_id"],)
            )
        }
        security = (self.master.securities_for_issuer(issuer["issuer_id"]) or [None])[0]
        bars = 0
        price_source = None
        if security:
            bars = int(self.db.scalar(
                "SELECT COUNT(*) FROM bar WHERE security_id = ?", (security["security_id"],), 0
            ) or 0)
            latest = self.db.query_one(
                "SELECT b.source_id, s.kind FROM bar b JOIN source s ON s.source_id=b.source_id "
                "WHERE b.security_id=? ORDER BY b.ts_utc DESC LIMIT 1",
                (security["security_id"],),
            )
            if latest:
                price_source = latest["kind"]
        missing = [key for key in CORE_METRICS if key not in concepts]
        coverage_missing = [key for key in CORE_VALUATION_CONCEPTS if key not in concepts]
        share_concepts = [
            key for key in ("shares_outstanding", "weighted_average_shares_diluted")
            if key in concepts
        ]
        if not share_concepts:
            coverage_missing.append("shares_outstanding")
        annual_periods = int(row["annual_periods"] or 0)
        financial_coverage_valid = not coverage_missing and annual_periods >= 3
        # A DCF consumes revenue, a share denominator and the reported cash/debt bridge.
        # It does not consume total liabilities, so a filer that never tags
        # us-gaap:Liabilities can still have a complete valuation input set while its
        # statement coverage remains explicitly incomplete.
        valuation_missing = [] if "revenue" in concepts else ["revenue"]
        if not share_concepts:
            valuation_missing.append("shares_outstanding")
        eligibility = _valuation_eligibility(issuer, valuation_missing, available=concepts)
        return {
            "issuer_id": issuer["issuer_id"],
            "cik": issuer.get("cik"),
            "legal_name": issuer["legal_name"],
            "ticker": self._ticker(issuer["issuer_id"]),
            "ticker_identity": self._ticker_status(issuer["issuer_id"]),
            "sector": None,
            "sic": issuer.get("sic"),
            "fiscal_year_end": issuer.get("fiscal_year_end"),
            "financial_institution": eligibility["status"] == "unsupported_methodology",
            "evidence_records": int(row["evidence"] or 0),
            "concepts": int(row["concepts"] or 0),
            "annual_periods": annual_periods,
            "first_period": row["first_period"],
            "last_period": row["last_period"],
            "filings": int(self.db.scalar(
                "SELECT COUNT(*) FROM filing WHERE issuer_id=?", (issuer["issuer_id"],), 0
            ) or 0),
            "market_observations": bars,
            "price_source": price_source,
            "missing_core_concepts": missing,
            "financial_coverage_missing": coverage_missing,
            "financial_coverage_valid": financial_coverage_valid,
            "valuation_missing": valuation_missing,
            "share_concepts": share_concepts,
            "share_basis": (
                "period_end_share_count" if "shares_outstanding" in concepts
                else "weighted_average_diluted" if "weighted_average_shares_diluted" in concepts
                else "unavailable"
            ),
            "valuation_eligibility": eligibility,
            "valuation_method": eligibility.get("method"),
            "business_model": eligibility.get("business_model"),
            "coverage_status": (
                "fundamentals_and_prices" if bars else
                "sec_fundamentals_only" if not missing else
                "partial_sec_fundamentals"
            ),
        }

    def coverage(self) -> dict[str, Any]:
        issuers = [
            dict(row) for row in self.db.query(
                "SELECT * FROM issuer WHERE is_active=1 ORDER BY legal_name COLLATE NOCASE"
            )
        ]
        rows = [self._issuer_coverage(issuer) for issuer in issuers]
        readiness = self.readiness(rows=rows)
        source = self.db.query_one("SELECT * FROM source WHERE source_id='sec-edgar'")
        return {
            "schema": "atlas.equity_research.coverage.v1",
            "generated_at": iso(utcnow()),
            "issuers": len(rows),
            "with_revenue": sum(1 for row in rows if "revenue" not in row["financial_coverage_missing"]),
            "with_prices": sum(1 for row in rows if row["market_observations"] > 0),
            "total_evidence": sum(row["evidence_records"] for row in rows),
            "total_filings": sum(row["filings"] for row in rows),
            "financial_coverage_valid": sum(1 for row in rows if row["financial_coverage_valid"]),
            "valuation_eligible": sum(
                1 for row in rows if row["valuation_eligibility"]["status"] == "eligible"
            ),
            "institution_methods_available": sum(
                1 for row in rows
                if row["valuation_eligibility"].get("method") in (RESIDUAL_INCOME, JUSTIFIED_EARNINGS)
            ),
            "dcf_executes": readiness.get("dcf_executes", 0),
            "institution_models_execute": readiness.get("institution_models_execute", 0),
            "methodology_rejected": sum(
                1 for row in rows
                if row["valuation_eligibility"]["status"] == "unsupported_methodology"
            ),
            "valuation_executes": readiness["valuation_executes"],
            "valuation_economically_supported": readiness["valuation_economically_supported"],
            "contract_states": readiness.get("contract_states", {}),
            "readiness": readiness,
            "items": rows,
            "source": {
                "source_id": source["source_id"],
                "name": source["name"],
                "license": source["licence"],
                "redistribution": source["redistribution"],
                "homepage": source["homepage"],
            } if source else None,
            "coverage_note": (
                "Financial facts come from SEC XBRL filings. This fixture retains 2018+ annual "
                "and recent sub-annual observations. No market prices are bundled for this "
                "universe; Atlas does not substitute synthetic quotes into real-company research."
            ),
            "limitations": [
                "The universe is 20 large US issuers, not the full listed market.",
                "SIC codes are broad and are not treated as curated peer groups.",
                "Pre-2018 filing archives and full raw companyfacts payloads are not in the compact fixture.",
                "Goldman Sachs currently has no mapped revenue element; its DCF is unsupported rather than estimated.",
            ],
        }

    # ---------------------------------------------------------------- readiness
    def readiness(self, *, rows: list[dict[str, Any]] | None = None,
                  as_of: str | None = None, mode: str | None = None) -> dict[str, Any]:
        """Run the valuation core for each issuer without stress grids.

        Coverage and valuation are reported as separate facts: an issuer can have valid
        financial coverage (reported statements and a share denominator) and still be
        rejected as a DCF subject, or execute the model and still fail the independent
        component audit.
        """
        if rows is None:
            issuers = [
                dict(row) for row in self.db.query(
                    "SELECT * FROM issuer WHERE is_active=1 ORDER BY legal_name COLLATE NOCASE"
                )
            ]
            rows = [self._issuer_coverage(issuer) for issuer in issuers]
        items = []
        for row in rows:
            eligibility = row["valuation_eligibility"]
            summary = {
                "issuer_id": row["issuer_id"],
                "ticker": row["ticker"],
                "legal_name": row["legal_name"],
                "sic": row["sic"],
                "financial_coverage_valid": row["financial_coverage_valid"],
                "financial_coverage_missing": row["financial_coverage_missing"],
                "eligibility": eligibility["status"],
                "financial_institution": row["financial_institution"],
                "valuation_executes": False,
                "economically_supported": False,
                "method": eligibility.get("method"),
                "contract_state": None,
                "status": eligibility["status"],
                "value_per_share": None,
                "audit_verdict": None,
                "flags": [],
                "reason": " ".join(eligibility["reasons"]) or None,
            }
            if eligibility["status"] == "eligible" or eligibility.get("method") in (
                RESIDUAL_INCOME, JUSTIFIED_EARNINGS
            ):
                valuation = self._valuation(
                    row["issuer_id"], assumptions=None, as_of=as_of, mode=mode,
                    target_price=None, stress=False,
                )
                institution = valuation.get("institution") or {}
                summary.update({
                    "valuation_executes": bool(valuation.get("executes")),
                    "economically_supported": bool(valuation.get("economically_supported")),
                    "method": valuation.get("method") or eligibility.get("method"),
                    "contract_state": (valuation.get("contract") or {}).get("state"),
                    "status": valuation["status"],
                    "value_per_share": (
                        valuation["dcf"]["outputs"].get("value_per_share")
                        if valuation.get("dcf") else
                        (institution.get("outputs") or {}).get("value_per_share")
                    ),
                    "audit_verdict": (
                        valuation.get("audit", {}).get("verdict")
                        if valuation.get("audit") else None
                    ),
                    "flags": [flag["code"] for flag in valuation.get("findings", [])],
                    "reason": valuation.get("reason"),
                })
            items.append(summary)
        states: dict[str, int] = {}
        for item in items:
            key = item.get("contract_state") or "not_evaluated"
            states[key] = states.get(key, 0) + 1
        return {
            "schema": "atlas.equity_research.readiness.v1",
            "issuers": len(items),
            "financial_coverage_valid": sum(1 for item in items if item["financial_coverage_valid"]),
            "valuation_executes": sum(1 for item in items if item["valuation_executes"]),
            "dcf_executes": sum(
                1 for item in items if item["valuation_executes"] and item.get("method") == DCF
            ),
            "institution_models_execute": sum(
                1 for item in items if item["valuation_executes"]
                and item.get("method") in (RESIDUAL_INCOME, JUSTIFIED_EARNINGS)
            ),
            "contract_states": states,
            "valuation_economically_supported": sum(
                1 for item in items if item["economically_supported"]
            ),
            "methodology_rejected": sum(
                1 for item in items if item["eligibility"] == "unsupported_methodology"
            ),
            "items": items,
            "note": (
                "Executing the DCF is not an economic validation. Coverage counts statement "
                "availability; valuation counts model eligibility, execution and the independent "
                "component audit separately."
            ),
        }

    # ----------------------------------------------------------------- workspace
    def _evidence_details(self, metrics: dict[str, Any], limit: int = 24) -> list[dict[str, Any]]:
        ids = sorted({
            evidence_id
            for metric in metrics.get("metrics", {}).values()
            if isinstance(metric, dict)
            for evidence_id in metric.get("evidence_ids", [])
        })
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = self.db.query(
            f"SELECT evidence_id, concept, period_start, period_end, fiscal_period, value_numeric, "
            f"unit, source_concept, accession_number, form_type, availability_time, quality, "
            f"derivation_kind, derivation_rule FROM evidence WHERE evidence_id IN ({marks}) "
            f"ORDER BY concept, period_end DESC, availability_time DESC",
            ids,
        )
        return [dict(row) for row in rows[:limit]]

    def _quality_checks(self, metrics: dict[str, Any], history: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        def add(name: str, formula: str, expected: Any, actual: Any, tolerance: str,
                status: str, evidence_ids: Iterable[str] = (), note: str = "") -> None:
            checks.append({
                "name": name,
                "formula": formula,
                "expected": expected,
                "actual": actual,
                "tolerance": tolerance,
                "status": status,
                "evidence_ids": sorted(set(evidence_ids)),
                "note": note,
            })

        assets = _value(metrics, "assets")
        liabilities = _value(metrics, "liabilities")
        equity = _value(metrics, "equity")
        if assets is not None and liabilities is not None and equity is not None:
            residual = assets - liabilities - equity
            relative = abs(residual) / abs(assets) if assets else None
            status = "reconciled" if relative is not None and relative <= 0.005 else "difference"
            add(
                "Balance sheet identity",
                "assets - liabilities - equity",
                "0.00",
                _money(residual),
                "0.5% of assets",
                status,
                metrics["metrics"].get("assets", {}).get("evidence_ids", [])
                + metrics["metrics"].get("liabilities", {}).get("evidence_ids", [])
                + metrics["metrics"].get("equity", {}).get("evidence_ids", []),
                (
                    "A non-zero residual is reported, not forced to zero; non-controlling interests "
                    "or a different equity tag can explain it."
                ),
            )
        else:
            add("Balance sheet identity", "assets - liabilities - equity", "0.00", "missing",
                "0.5% of assets", "unavailable", note="One or more balance-sheet inputs are absent.")

        ocf = _value(metrics, "operating_cash_flow")
        capex = _value(metrics, "capex")
        fcf = _value(metrics, "free_cash_flow")
        if ocf is not None and capex is not None and fcf is not None:
            expected = ocf - abs(capex)
            add("Free cash flow", "operating cash flow - |capex|", _money(expected), _money(fcf),
                "0.01 USD", "pass" if abs(expected - fcf) < 0.01 else "fail",
                metrics["metrics"].get("operating_cash_flow", {}).get("evidence_ids", [])
                + metrics["metrics"].get("capex", {}).get("evidence_ids", []))
        else:
            add("Free cash flow", "operating cash flow - |capex|", "computed", "missing",
                "0.01 USD", "unavailable")

        revenue = _value(metrics, "revenue")
        gross = _value(metrics, "gross_profit")
        operating = _value(metrics, "operating_income")
        for key, label, top in (("gross_margin", "Gross margin", gross),
                                ("operating_margin", "Operating margin", operating)):
            actual = _value(metrics, key)
            if revenue and top is not None and actual is not None:
                expected = top / revenue
                add(label, f"{label.lower().split()[0]} / revenue", f"{expected:.12f}",
                    f"{actual:.12f}", "1e-9", "pass" if abs(expected - actual) <= 1e-9 else "fail",
                    metrics["metrics"].get(key, {}).get("evidence_ids", []))
            else:
                add(label, "reported input / revenue", "computed", "missing", "1e-9", "unavailable")

        growth = _value(metrics, "revenue_growth")
        if growth is not None and revenue is not None:
            add("Revenue growth", "revenue_t / revenue_t-1 - 1",
                metrics["metrics"].get("revenue_growth", {}).get("text", "—"),
                _pct(growth), "reported formula",
                "reported", metrics["metrics"].get("revenue_growth", {}).get("evidence_ids", []),
                f"Comparison period {metrics.get('comparison_period_end')}.")

        if fcf is not None and _value(metrics, "net_income"):
            conversion = fcf / float(_value(metrics, "net_income") or 1)
            add("Cash conversion", "free cash flow / net income", "descriptive", _pct(conversion),
                "none", "warning" if conversion < 0 else "info",
                metrics["metrics"].get("free_cash_flow", {}).get("evidence_ids", []),
                "Negative conversion is flagged, not adjusted.")

        shares = _value(metrics, "shares_outstanding") or _value(metrics, "weighted_average_shares_diluted")
        if shares:
            add("Share denominator", "reported shares used for per-share value",
                "reported", f"{shares:,.0f}", "shares", "info",
                (metrics["metrics"].get("shares_outstanding")
                 or metrics["metrics"].get("weighted_average_shares_diluted", {})).get("evidence_ids", []),
                "A weighted diluted count is used only when a point-in-time count is unavailable.")
        else:
            add("Share denominator", "reported shares used for per-share value",
                "positive count", "missing", "shares", "unavailable")

        for key in metrics.get("missing", []):
            add(f"Missing {key.replace('_', ' ')}", "reported fact required", "present", "missing",
                "n/a", "unavailable", note="Atlas does not insert a zero or an estimate.")
        return checks

    def _limitations(self, coverage: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
        limitations = [
            "SEC XBRL is the financial source; no qualitative business narrative, guidance or news is generated.",
            "The compact fixture keeps 2018+ annual observations and recent sub-annual observations, not the complete filing archive.",
            "No licensed market prices are bundled for this universe, so market multiples and market-implied reverse DCF are unavailable.",
            "DCF inputs for WACC, tax, D&A, working capital and forecast growth are analyst assumptions unless labelled reported.",
            "SIC codes are not treated as a validated industry peer taxonomy.",
        ]
        if coverage["missing_core_concepts"]:
            limitations.append(
                "Missing core concepts: " + ", ".join(coverage["missing_core_concepts"])
            )
        if _value(metrics, "free_cash_flow") is not None and _value(metrics, "free_cash_flow") < 0:
            limitations.append("Reported trailing free cash flow is negative; the DCF may produce negative equity value.")
        return limitations

    def workspace(self, identifier: str, *, as_of: str | None = None,
                  mode: str | None = None) -> dict[str, Any]:
        issuer = read_models.resolve_company(self.db, identifier)
        resolved_mode = mode or AsOfMode.PUBLIC_AVAILABLE.value
        metrics = get_issuer_metrics(self.db, issuer["issuer_id"], as_of=as_of, mode=resolved_mode)
        coverage = self._issuer_coverage(issuer)
        statements = {
            name: read_models.statements(
                self.db, issuer["issuer_id"], statement=name, period="FY",
                as_of=metrics["as_of"], mode=metrics["mode"], limit=6,
            )
            for name in ("income", "balance", "cashflow")
        }
        history = read_models.financial_history(
            self.db, issuer["issuer_id"], limit=8, as_of=metrics["as_of"], mode=metrics["mode"]
        )
        filings = read_models.filings(
            self.db, issuer["issuer_id"], limit=12, forms=("10-K", "10-K/A", "10-Q", "10-Q/A")
        )
        peers = read_models.peers(
            self.db, issuer["issuer_id"], as_of=metrics["as_of"], mode=metrics["mode"]
        )
        try:
            validation = research_validation.run(
                self.db, issuer["issuer_id"], as_of=metrics["as_of"], mode=metrics["mode"]
            )
        except Exception as exc:  # noqa: BLE001 - validation failure is reported, not hidden
            validation = {
                "status": "unavailable",
                "checks": [],
                "passed": 0,
                "failed": 0,
                "total": 0,
                "reason": str(exc),
            }
        quality = self._quality_checks(metrics, history)
        sources = [
            dict(row) for row in self.db.query(
                "SELECT source_id, name, kind, homepage, licence, redistribution, notes "
                "FROM source WHERE kind != 'catalog' ORDER BY source_id"
            )
        ]
        precision = {
            row["precision"]: int(row["n"])
            for row in self.db.query(
                "SELECT availability_precision AS precision, COUNT(*) AS n FROM evidence "
                "WHERE entity_id=? GROUP BY availability_precision", (issuer["issuer_id"],)
            )
        }
        limitations = self._limitations(coverage, metrics)
        return {
            "schema": EQUITY_SCHEMA,
            "as_of": metrics["as_of"],
            "mode": metrics["mode"],
            "company": read_models.company_detail(self.db, issuer["issuer_id"]),
            "coverage": coverage,
            "metrics": metrics,
            "statements": statements,
            "history": history,
            "filings": filings,
            "peer_comparison": peers,
            "validation": validation,
            "quality_checks": quality,
            "provenance": {
                "sources": sources,
                "availability_precision": precision,
                "evidence_details": self._evidence_details(metrics),
                "selection_policy": metrics.get("policy"),
            },
            "limitations": limitations,
            "market_price": self._market_price(issuer["issuer_id"]),
        }

    def _market_price(self, issuer_id: str) -> dict[str, Any]:
        """Return the first authorised price series for the issuer, or an explicit gap."""
        securities = self.master.securities_for_issuer(issuer_id)
        if not securities:
            return prices.price_summary(self.db, "")
        summaries = [prices.price_summary(self.db, row["security_id"]) for row in securities]
        for summary in summaries:
            if summary["status"] == "available":
                return summary
        return summaries[0]

    # --------------------------------------------------------------------- report
    def _valuation(self, identifier: str, *, assumptions: dict[str, Any] | None,
                   as_of: str | None, mode: str | None,
                   target_price: float | None, stress: bool = True) -> dict[str, Any]:
        issuer = read_models.resolve_company(self.db, identifier)
        metrics = get_issuer_metrics(self.db, issuer["issuer_id"], as_of=as_of, mode=mode)
        coverage = self._issuer_coverage(issuer)
        available = [
            key for key, item in (metrics.get("metrics") or {}).items()
            if isinstance(item, dict) and item.get("value") is not None
        ]
        eligibility = _valuation_eligibility(
            issuer, coverage["valuation_missing"], available=available
        )
        base: dict[str, Any] = {
            "eligibility": eligibility,
            "method": eligibility.get("method"),
            "contract": None,
            "institution": None,
            "defaults": None,
            "dcf": None,
            "scenarios": None,
            "sensitivity": None,
            "reverse": None,
            "audit": None,
            "findings": [],
            "executes": False,
            "economically_supported": False,
        }
        if eligibility.get("method") in (RESIDUAL_INCOME, JUSTIFIED_EARNINGS):
            model = institutions.build_institution_valuation(
                issuer=issuer, metrics=metrics, coverage=coverage, assumptions=assumptions
            )
            contract = model.get("contract") or {}
            return {
                **base,
                "status": model["status"],
                "reason": model.get("reason"),
                "institution": model,
                "contract": model.get("contract"),
                "audit": model.get("audit"),
                "executes": bool(model.get("executes")),
                "economically_supported": bool(model.get("economically_supported")),
                "findings": model.get("findings", []),
                "eligibility": {
                    **eligibility,
                    "contract_state": contract.get("state"),
                },
            }
        if eligibility["status"] != "eligible":
            return {
                **base,
                "status": eligibility["status"],
                "reason": " ".join(eligibility["reasons"]),
                "context": {"eligibility": eligibility},
            }
        try:
            defaults = fec_valuation.defaults_from_metrics(metrics)
            merged = dict(defaults)
            merged.update(assumptions or {})
            dcf = fec_valuation.run_dcf(
                self.db, issuer["issuer_id"], merged, as_of=as_of, mode=mode, persist=False
            )
        except (MissingDataError, ValidationError) as exc:
            return {
                **base,
                "status": "unsupported_data",
                "reason": str(exc),
                "context": getattr(exc, "context", {}),
            }
        audit = self._dcf_audit(dcf, metrics, eligibility)
        contract = build_contract(
            issuer=issuer,
            metrics=metrics,
            coverage=coverage,
            available=available,
            assumptions={
                key: merged.get(key) for key in (
                    "revenue_growth", "operating_margin", "tax_rate", "wacc",
                    "terminal_growth", "horizon",
                )
            },
            arithmetic={
                "passed": bool(audit.get("arithmetic_valid")),
                "verdict": audit.get("verdict"),
                "checks": len(audit.get("checks") or []),
                "version": "atlas.dcf.component_audit.v1",
            },
        )
        result = {
            **base,
            "status": "supported",
            "executes": True,
            "defaults": defaults,
            "dcf": dcf,
            "audit": audit,
            "contract": contract,
            "economically_supported": audit["economically_supported"],
            "findings": audit["findings"],
        }
        if stress:
            result["scenarios"] = fec_valuation.scenarios(
                self.db, issuer["issuer_id"], merged, as_of=as_of, mode=mode
            )
            result["sensitivity"] = fec_valuation.sensitivity(
                self.db, issuer["issuer_id"], assumptions=merged, as_of=as_of, mode=mode
            )
            if target_price is not None:
                result["reverse"] = fec_valuation.reverse_dcf(
                    self.db, issuer["issuer_id"], target_price,
                    variable="terminal_growth", assumptions=merged,
                    as_of=as_of, mode=mode,
                )
        return result

    # ------------------------------------------------------------ DCF audit
    def _dcf_audit(self, dcf: dict[str, Any], metrics: dict[str, Any],
                   eligibility: dict[str, Any]) -> dict[str, Any]:
        """Recompute every DCF component from the recorded assumptions.

        This is an independent arithmetic reconstruction, not a re-run of the compiled
        graph: it uses plain Python floats in a different order from the operator graph.
        A mismatch is a real finding; the valuation is not silently accepted because the
        engine returned a number.
        """
        a = dcf["assumptions"]
        out = dcf.get("outputs", {})
        horizon = int(a["horizon"])
        growth = [float(rate) for rate in a["revenue_growth"]]
        margin = float(a["operating_margin"])
        tax_rate = float(a["tax_rate"])
        da_pct = float(a["da_pct_revenue"])
        capex_pct = float(a["capex_pct_revenue"])
        nwc_pct = float(a["nwc_pct_revenue"])
        wacc = float(a["wacc"])
        terminal_growth = float(a["terminal_growth"])
        cash = float(a["cash"])
        debt = float(a["debt"])
        shares = float(a["shares"])
        mid_year = a["convention"] == "mid_year"
        base_revenue = float(a["revenue"])

        revenue_path: list[float] = []
        level = base_revenue
        for rate in growth:
            level = level * (1 + rate)
            revenue_path.append(level)
        ebit = [value * margin for value in revenue_path]
        taxes = [value * tax_rate for value in ebit]
        nopat = [value - tax for value, tax in zip(ebit, taxes)]
        da = [value * da_pct for value in revenue_path]
        capex = [value * capex_pct for value in revenue_path]
        nwc = [value * nwc_pct for value in revenue_path]
        previous_nwc = base_revenue * nwc_pct
        nwc_change = []
        for target in nwc:
            nwc_change.append(target - previous_nwc)
            previous_nwc = target
        fcff = [
            profit + depreciation - investment - change
            for profit, depreciation, investment, change in zip(nopat, da, capex, nwc_change)
        ]
        periods = [index - 0.5 if mid_year else float(index) for index in range(1, horizon + 1)]
        discounted = [flow / (1 + wacc) ** period for flow, period in zip(fcff, periods)]
        pv_explicit = sum(discounted)
        if a["terminal_method"] == "exit_multiple":
            terminal_value = fcff[-1] * float(a["exit_multiple"])
        else:
            terminal_value = fcff[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_terminal = terminal_value / (1 + wacc) ** periods[-1]
        enterprise_value = pv_explicit + pv_terminal
        equity_value = enterprise_value + cash - debt
        value_per_share = equity_value / shares

        checks: list[dict[str, Any]] = []

        def check(name: str, formula: str, expected: Any, actual: Any,
                  unit: str = "USD", note: str = "") -> None:
            difference: Any = None
            status = "unavailable"
            if isinstance(expected, list) and isinstance(actual, list):
                if expected and len(expected) == len(actual):
                    differences = [abs(left - right) for left, right in zip(expected, actual)]
                    difference = max(differences)
                    scale = max(1.0, max(abs(item) for item in expected))
                    status = "pass" if difference <= max(1e-6, scale * _ARITHMETIC_TOLERANCE) else "fail"
                else:
                    difference = None
                    status = "fail"
            elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                difference = float(actual) - float(expected)
                scale = max(1.0, abs(float(expected)))
                status = "pass" if abs(difference) <= max(1e-6, scale * _ARITHMETIC_TOLERANCE) else "fail"
            checks.append({
                "name": name,
                "formula": formula,
                "expected": expected,
                "actual": actual,
                "difference": difference,
                "status": status,
                "unit": unit,
                "note": note,
            })

        check("Revenue forecast path", "revenue_t = revenue_t-1 × (1 + growth_t)",
              revenue_path, _series_value(out.get("revenue_forecast")))
        check("FCFF path", "NOPAT + D&A − capex − ΔNWC", fcff, _series_value(out.get("fcff")))
        check("PV of explicit forecast", "Σ FCFF_t / (1 + WACC)^t", pv_explicit, out.get("pv_explicit"))
        check("Terminal value", (
            "FCFF_T × (1 + g) / (WACC − g)" if a["terminal_method"] == "gordon_growth"
            else "FCFF_T × exit multiple"
        ), terminal_value, out.get("terminal_value"))
        check("PV of terminal value", "TV / (1 + WACC)^T", pv_terminal, out.get("pv_terminal"))
        check("Enterprise value", "PV explicit + PV terminal", enterprise_value, out.get("enterprise_value"))
        check("Equity value bridge", "EV + cash − debt", equity_value, out.get("equity_value"))
        check("Value per share", "equity value / shares", value_per_share, out.get("value_per_share"),
              unit="USD/share")

        arithmetic_valid = all(item["status"] == "pass" for item in checks)
        findings: list[dict[str, Any]] = []
        evidence = dcf.get("audit", {}).get("evidence_ids", [])

        def flag(code: str, severity: str, message: str, evidence_ids: Iterable[str] = ()) -> None:
            findings.append({
                "code": code,
                "severity": severity,
                "message": message,
                "evidence_ids": sorted(set(evidence_ids)),
            })

        if not arithmetic_valid:
            flag(
                "dcf_arithmetic_mismatch", "error",
                "At least one DCF output did not reproduce from the recorded assumptions; the "
                "engine result is reported but not accepted as validated.",
                evidence,
            )
        terminal_share = pv_terminal / enterprise_value if enterprise_value else None
        if terminal_share is not None and terminal_share > 0.9:
            flag(
                "terminal_value_dominates", "warning",
                f"{terminal_share:.1%} of enterprise value comes from the terminal value; the "
                "valuation is a statement about the terminal assumption, not the forecast.",
                evidence,
            )
        if enterprise_value and enterprise_value < 0:
            flag(
                "negative_enterprise_value", "finding",
                "The reported inputs and assumptions imply a negative enterprise value. The "
                "number is preserved; it is a finding about cash burn and capital intensity, "
                "not a result to be tuned away.",
                evidence,
            )
        if equity_value < 0:
            flag(
                "negative_equity_value", "finding",
                "Equity value is negative under the stated assumptions. Atlas reports it as a "
                "finding instead of raising the margin, lowering capex or changing WACC.",
                evidence,
            )
        if any(flow < 0 for flow in fcff):
            flag(
                "negative_fcff", "finding",
                "At least one forecast year has negative free cash flow to the firm.",
                evidence,
            )
        if margin < -0.1 or margin > 0.7:
            flag(
                "extreme_operating_margin", "warning",
                f"Operating margin of {margin:.1%} is an extreme assumption and is not supported "
                "by a cross-check beyond the latest reported period.",
            )
        if capex_pct > 0.5:
            flag(
                "high_capex_intensity", "warning",
                f"Capex of {capex_pct:.1%} of revenue drives the result; the terminal value may "
                "carry an unsustainably high reinvestment rate.",
            )
        if wacc < 0.05:
            flag(
                "low_discount_rate", "warning",
                f"A {wacc:.2%} WACC is below a plausible long-run risk-free rate; no bond or "
                "market data is bundled to validate it.",
            )
        if tax_rate < 0.05:
            flag(
                "low_tax_rate", "warning",
                f"A {tax_rate:.1%} tax rate is far below the statutory rate and materially "
                "raises NOPAT.",
            )

        share_denominator = self._share_denominator(a, metrics)
        if share_denominator["basis"] != "period_end_share_count":
            flag(
                "share_denominator_fallback", "warning",
                share_denominator["limitation"],
                share_denominator.get("evidence_ids", []),
            )

        if not arithmetic_valid:
            verdict = "arithmetic_failure"
        elif terminal_share is not None and terminal_share > 0.9:
            verdict = "not_economically_robust"
        elif findings:
            verdict = "supported_with_findings"
        else:
            verdict = "supported"
        return {
            "schema": "atlas.equity_research.dcf_audit.v1",
            "method": VALUATION_METHOD,
            "eligibility": eligibility,
            "checks": checks,
            "arithmetic_valid": arithmetic_valid,
            "component_count": len(checks),
            "terminal_value_share": terminal_share,
            "share_denominator": share_denominator,
            "findings": findings,
            "verdict": verdict,
            "economically_supported": verdict in {"supported", "supported_with_findings"},
            "formula": (
                "FCFF = NOPAT + D&A − capex − ΔNWC; EV = PV(FCFF) + PV(TV); "
                "equity = EV + cash − debt; value/share = equity / shares"
            ),
            "note": (
                "This audit recomputes each component independently of the compiled operator "
                "graph. A passing audit means the arithmetic is internally consistent; it does "
                "not make the assumptions true."
            ),
        }

    def _share_denominator(self, assumptions: dict[str, Any],
                           metrics: dict[str, Any]) -> dict[str, Any]:
        provenance = (assumptions.get("provenance") or {}).get("shares_outstanding") or {}
        basis = provenance.get("basis")
        value = float(assumptions["shares"])
        reported = (metrics.get("metrics", {}).get("shares_outstanding") or {}).get("value")
        weighted = (metrics.get("metrics", {}).get("weighted_average_shares_diluted") or {}).get("value")
        if basis == "weighted_average_diluted" or (basis is None and reported is None and weighted):
            return {
                "basis": "weighted_average_diluted",
                "value": value,
                "period_end_count": reported,
                "weighted_average_count": weighted or value,
                "evidence_ids": provenance.get("evidence_ids", []),
                "limitation": (
                    "The share count is a period-weighted diluted average, not a point-in-time "
                    "cover-page count. It is the right denominator for a diluted per-share "
                    "figure but it does not describe shares outstanding on the valuation date."
                ),
            }
        if basis == "derived_net_income_over_eps" or (basis is None and reported is None and not weighted):
            return {
                "basis": "derived_net_income_over_eps",
                "value": value,
                "period_end_count": None,
                "weighted_average_count": None,
                "evidence_ids": provenance.get("evidence_ids", []),
                "limitation": (
                    "No reported share count was available. The denominator is derived as net "
                    "income divided by diluted EPS, which inherits both reported facts and "
                    "rounding in the published EPS; it is an estimate, not a reported count."
                ),
            }
        return {
            "basis": "period_end_share_count",
            "value": value,
            "period_end_count": reported if reported is not None else value,
            "weighted_average_count": weighted,
            "evidence_ids": provenance.get("evidence_ids", []),
            "limitation": (
                "A point-in-time share count at the balance-sheet date is used for a per-share "
                "value; option dilution and post-period issuance are not reflected."
            ),
        }

    def valuation(self, identifier: str, *, assumptions: dict[str, Any] | None = None,
                  as_of: str | None = None, mode: str | None = None,
                  target_price: float | None = None) -> dict[str, Any]:
        """Return the method-appropriate valuation and its eligibility contract."""
        return self._valuation(
            identifier, assumptions=assumptions, as_of=as_of, mode=mode,
            target_price=target_price,
        )

    def analyse(self, identifier: str, *, assumptions: dict[str, Any] | None = None,
                as_of: str | None = None, mode: str | None = None,
                target_price: float | None = None) -> dict[str, Any]:
        workspace = self.workspace(identifier, as_of=as_of, mode=mode)
        valuation = self._valuation(
            identifier, assumptions=assumptions, as_of=workspace["as_of"],
            mode=workspace["mode"], target_price=target_price,
        )
        report = self._render_report(workspace, valuation)
        digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
        metadata = {
            "schema": REPORT_SCHEMA,
            "report_version": REPORT_VERSION,
            "report_sha256": digest,
            "as_of": workspace["as_of"],
            "mode": workspace["mode"],
            "issuer_id": workspace["company"]["issuer_id"],
            "cik": workspace["company"].get("cik"),
            "ticker": workspace["coverage"].get("ticker"),
            "financial_coverage_valid": workspace["coverage"]["financial_coverage_valid"],
            "financial_coverage_missing": workspace["coverage"]["financial_coverage_missing"],
            "valuation_eligibility": valuation["eligibility"]["status"],
            "valuation_method": valuation.get("method"),
            "valuation_contract": (valuation.get("contract") or {}).get("state"),
            "institution_model": (valuation.get("institution") or {}).get("model_version"),
            "valuation_executes": bool(valuation.get("executes")),
            "valuation_economically_supported": bool(valuation.get("economically_supported")),
            "dcf_audit_verdict": (
                valuation.get("audit", {}).get("verdict") if valuation.get("audit") else None
            ),
            "valuation_status": valuation["status"],
            "model_fingerprint": (
                valuation["dcf"].get("fingerprint") if valuation.get("dcf") else None
            ),
            "compiler_version": (
                valuation["dcf"].get("manifest", {}).get("compiler_version")
                if valuation.get("dcf") else None
            ),
            "source_revision": os.environ.get("ATLAS_SOURCE_REVISION", "working-tree"),
            "source_ids": ["sec-edgar"],
        }
        return {
            "schema": EQUITY_SCHEMA,
            "workspace": workspace,
            "valuation": valuation,
            "report": report,
            "metadata": metadata,
        }

    def _render_report(self, workspace: dict[str, Any], valuation: dict[str, Any]) -> str:
        company = workspace["company"]
        coverage = workspace["coverage"]
        metrics = workspace["metrics"]
        history = workspace["history"]
        lines = [
            f"# {company['legal_name']} — Equity Research",
            "",
            f"**Ticker:** {coverage.get('ticker') or 'not mapped'}  ",
            f"**CIK:** {company.get('cik') or '—'}  ",
            f"**Information cutoff:** {workspace['as_of']} ({workspace['mode']})  ",
            f"**Status:** deterministic source-grounded research; no LLM generated any factual claim.",
            "",
            "## Research question",
            "",
            f"What do the reported financial statements imply about {company['legal_name']}'s recent "
            "performance, financial quality and value under explicit analyst assumptions?",
            "",
            "## Company identity and source-limited context",
            "",
            f"Legal issuer: **{company['legal_name']}**. CIK `{company.get('cik')}`. "
            f"SIC code `{company.get('sic') or 'not reported'}`. Fiscal year end "
            f"`{company.get('fiscal_year_end') or 'not reported'}`.",
            "",
            "Atlas does not generate a qualitative business description, competitive position or "
            "management narrative without a source document. The source-limited context is the SEC "
            "registrant identity and its filed reports. The latest stored filing is "
            f"**{company.get('latest_filing', {}).get('form_type') if company.get('latest_filing') else 'none'}** "
            f"filed {company.get('latest_filing', {}).get('filed_date') if company.get('latest_filing') else '—'}.",
            "",
            "## Data coverage",
            "",
            f"- SEC evidence records: **{coverage['evidence_records']:,}** across **{coverage['concepts']}** mapped concepts.",
            f"- Annual periods retained: **{coverage['annual_periods']}** ({coverage['first_period'] or '—'} to {coverage['last_period'] or '—'}).",
            f"- SEC filings in the compact fixture: **{coverage['filings']:,}**.",
            f"- Market observations: **{coverage['market_observations']:,}**"
            + (f" from **{coverage['price_source']}**." if coverage["price_source"] else ". No price source is bundled."),
            "",
            "The compact research fixture retains 2018+ annual observations and recent sub-annual "
            "observations. It is not a complete SEC archive and does not include licensed market prices.",
            "",
            "## Historical financial results",
            "",
        ]
        concepts = {row["concept"]: row for row in history.get("concepts", [])}
        periods = history.get("periods", [])
        labels = [
            ("revenue", "Revenue"),
            ("gross_profit", "Gross profit"),
            ("operating_income", "Operating income"),
            ("net_income", "Net income"),
            ("operating_cash_flow", "Operating cash flow"),
            ("capex", "Capex"),
        ]
        if periods and concepts:
            lines.append("| Metric | " + " | ".join(period[:4] for period in periods) + " |")
            lines.append("| --- | " + " | ".join("---:" for _ in periods) + " |")
            for key, label in labels:
                row = concepts.get(key)
                if not row:
                    continue
                values = {point["period_end"]: point["text"] for point in row.get("points", [])}
                lines.append("| " + label + " | " + " | ".join(values.get(period, "—") for period in periods) + " |")
            fcf = _value(metrics, "free_cash_flow")
            lines.append("| Free cash flow (latest) | " + " | ".join(
                _money(fcf) if period == metrics.get("period_end") else "—" for period in periods
            ) + " |")
        else:
            lines.append("No annual statement periods are available for this view.")

        lines += [
            "",
            f"Latest annual period: **{metrics.get('period_end') or 'unavailable'}**. "
            f"Revenue growth: **{_pct(_value(metrics, 'revenue_growth'))}**. "
            f"Operating margin: **{_pct(_value(metrics, 'operating_margin'))}**. "
            f"Free cash flow: **{_money(_value(metrics, 'free_cash_flow'))} USD**.",
            "",
            "## Financial reconciliation and quality",
            "",
            "| Check | Formula | Expected | Actual | Status |",
            "| --- | --- | ---: | ---: | --- |",
        ]
        for check in workspace["quality_checks"]:
            if check["status"] in {"unavailable"}:
                continue
            lines.append(
                f"| {check['name']} | `{check['formula']}` | {check['expected']} | "
                f"{check['actual']} | **{check['status']}** |"
            )
        lines += [
            "",
            "A residual is not forced to zero. Missing inputs are omitted rather than treated as zero. "
            "The independent validation endpoint separately recomputes ratios from their inputs.",
            "",
        ]
        eligibility = valuation["eligibility"]
        lines += [
            "## Valuation methodology and eligibility",
            "",
            f"- Method under evaluation: `{eligibility['method']}` for a non-financial operating company.",
            f"- Eligibility status: **{eligibility['status']}**.",
        ]
        for reason in eligibility["reasons"]:
            lines.append(f"- {reason}")
        if eligibility.get("required_remedy"):
            lines.append(f"- Required before any per-share valuation: {eligibility['required_remedy']}.")
        contract = valuation.get("contract")
        if contract:
            lines += [
                "",
                "### Valuation eligibility contract",
                "",
                f"- Contract: `{contract['contract_version']}`",
                f"- State: **{contract['state']}** ({contract['state_index']} of {len(contract['state_history']) - 1} transitions reached)",
                f"- Business model: **{contract['business_model']}** — {contract['classification_basis']}",
                f"- Method: `{contract.get('method') or 'none'}`",
                f"- Share-count basis: **{contract.get('share_count_basis')}**",
                f"- Arithmetic validation: **{contract.get('audit_status')}**",
                "- Promotion policy: execution alone does not promote this contract. Independent arithmetic, an economic review and a reference benchmark are separate gates.",
            ]
            for limitation in contract.get("economic_limitations", []):
                lines.append(f"- Limitation: {limitation}")
            if contract.get("prohibited_methods"):
                for item in contract["prohibited_methods"]:
                    lines.append(f"- Prohibited: {item}")
        lines += ["", "## Valuation", ""]
        if valuation["status"] != "supported":
            label = (
                "DCF rejected for this issuer type"
                if valuation["status"] == "unsupported_methodology"
                else "DCF unavailable"
            )
            lines += [
                f"**{label}.** {_excerpt(valuation.get('reason'), 500)}",
                "",
                "This is a declared limitation, not a zero, a comparable-company multiple or a "
                "synthetic price. Atlas does not tune assumptions to produce an attractive value.",
            ]
        elif valuation.get("institution"):
            model = valuation["institution"]
            outputs = model["outputs"]
            lines += [
                f"Method: `{model['method']}` — {model.get('method_description')}",
                "",
                f"Model version `{model['model_version']}`. The model executed: "
                f"**{'yes' if model.get('executes') else 'no'}**. Execution is not an economic "
                "validation, and the contract state records how far verification has actually gone.",
                "",
                "| Output | Value |",
                "| --- | ---: |",
            ]
            for key, value in outputs.items():
                if key in {"rows", "residual_income_cross_check", "reported_roe", "negative_residual_equity"}:
                    continue
                rendered = _money(value) if isinstance(value, (int, float)) else _excerpt(value, 120)
                lines.append(f"| {key.replace('_', ' ')} | {rendered} |")
            if outputs.get("negative_residual_equity"):
                lines += [
                    "",
                    "The calculated residual equity value is negative. Atlas reports it as a calculated "
                    "residual, not as a negative share price a holder could realise. The computation is "
                    "not floored at zero and the assumptions are not tuned to remove the result.",
                ]
            lines += ["", "### Assumptions", "", "| Input | Value |", "| --- | ---: |"]
            for key, value in model["assumptions"].items():
                rendered = _money(value) if isinstance(value, (int, float)) and abs(value) > 5 else value
                lines.append(f"| {key} | {rendered} |")
            rows = (outputs.get("rows") or [])
            if rows:
                lines += [
                    "", "### Residual-income schedule", "",
                    "| Year | Opening book value | Net income | Dividends | Residual income | PV |",
                    "| --- | ---: | ---: | ---: | ---: | ---: |",
                ]
                for row in rows:
                    lines.append(
                        f"| {row['year']} | {_money(row['opening_book_value'])} | {_money(row['net_income'])} | "
                        f"{_money(row['dividends'])} | {_money(row['residual_income'])} | {_money(row['present_value'])} |"
                    )
            lines += ["", "### Sensitivity", "", "| Scenario | Value per share |", "| --- | ---: |"]
            grid = (model.get("sensitivity") or {}).get("cost_of_equity_and_roe") or []
            for cell in grid:
                label = f"CoE {cell['cost_of_equity']:.1%}, ROE {cell['roe']:.1%}"
                lines.append(f"| {label} | {_money(cell.get('value_per_share'))} |")
            for cell in (model.get("sensitivity") or {}).get("cost_of_equity_and_growth") or []:
                label = f"CoE {cell['cost_of_equity']:.1%}, growth {cell['growth']:.1%}"
                lines.append(f"| {label} | {_money(cell.get('value_per_share'))} |")
            for cell in (model.get("sensitivity") or {}).get("share_basis") or []:
                lines.append(
                    f"| Share basis {cell['basis']} ({cell['shares']:,.0f}) | {_money(cell.get('value_per_share'))} |"
                )
            for finding in model.get("findings", []):
                lines.append(f"- **{finding['code']}**: {finding['detail']}")
            for limitation in model.get("limitations", []):
                lines.append(f"- Limitation: {limitation}")
        else:
            dcf = valuation["dcf"]
            assumptions = dcf["assumptions"]
            outputs = dcf["outputs"]
            lines += [
                "The DCF is compiled from the same `atlas.model.v1` runtime used by Model Forge and "
                "portable applications. Every number below is reproducible from the model spec.",
                "",
                "| Output | Value |",
                "| --- | ---: |",
                f"| Value per share | **{_money(outputs.get('value_per_share'))} USD** |",
                f"| Equity value | {_money(outputs.get('equity_value'))} USD |",
                f"| Enterprise value | {_money(outputs.get('enterprise_value'))} USD |",
                f"| PV explicit forecast | {_money(outputs.get('pv_explicit'))} USD |",
                f"| PV terminal value | {_money(outputs.get('pv_terminal'))} USD |",
                "",
                "### Assumptions and provenance",
                "",
                "| Input | Value | Classification |",
                "| --- | ---: | --- |",
            ]
            provenance = dcf.get("audit", {}).get("observed_inputs", {})
            for key in ("revenue", "operating_margin", "revenue_growth", "capex",
                        "cash_and_equivalents", "total_debt", "shares_outstanding"):
                item = provenance.get(key)
                if item is None:
                    continue
                kind = item.get("kind") or "reported"
                value = item.get("value")
                lines.append(f"| {key.replace('_', ' ')} | {_excerpt(value, 80) if isinstance(value, list) else _money(value) if isinstance(value, (int, float)) else value} | {kind} |")
            for item in dcf.get("audit", {}).get("assumptions", []):
                classification = item.get("kind") or item.get("source") or "assumption"
                lines.append(f"| {item['key']} | {item['value']} | {classification} |")
            denominator = valuation["audit"]["share_denominator"]
            lines += [
                "",
                "### Share denominator",
                "",
                f"Basis: **{denominator['basis']}** at **{denominator['value']:,.0f}** shares. "
                f"Point-in-time count: {_money(denominator['period_end_count'])}; "
                f"weighted average diluted count: {_money(denominator['weighted_average_count'])}.",
                "",
                denominator["limitation"],
                "",
                "### Independent component audit",
                "",
                "Each component is recomputed with plain arithmetic from the recorded assumptions, "
                "separately from the compiled operator graph.",
                "",
                "| Component | Formula | Recomputed | Engine | Status |",
                "| --- | --- | ---: | ---: | --- |",
            ]
            for item in valuation["audit"]["checks"]:
                expected = item["expected"]
                actual = item["actual"]
                if isinstance(expected, list):
                    expected_text = f"{len(expected)} periods"
                    actual_text = f"{len(actual)} periods" if isinstance(actual, list) else str(actual)
                else:
                    expected_text = _money(expected if isinstance(expected, (int, float)) else None)
                    actual_text = _money(actual if isinstance(actual, (int, float)) else None)
                lines.append(
                    f"| {item['name']} | `{item['formula']}` | {expected_text} | "
                    f"{actual_text} | **{item['status']}** |"
                )
            lines += [
                "",
                f"Audit verdict: **{valuation['audit']['verdict']}**. "
                f"Terminal value share of enterprise value: "
                f"{_pct(valuation['audit']['terminal_value_share'], 1)}.",
            ]
            lines += [
                "",
                "### Scenarios",
                "",
                "| Scenario | Value per share | Delta vs base |",
                "| --- | ---: | ---: |",
            ]
            for name, item in valuation["scenarios"]["scenarios"].items():
                if "error" in item:
                    lines.append(f"| {name} | unsupported: {_excerpt(item['error'], 90)} | — |")
                else:
                    lines.append(f"| {name} | {_money(item['value_per_share'])} | {_money(item['delta_vs_base'])} |")
            lines += [
                "",
                "Scenarios branch from one shared model definition; they are conditional arithmetic, "
                "not forecasts or management guidance.",
                "",
                "### Sensitivity",
                "",
                "| WACC \\ terminal growth | " + " | ".join(valuation["sensitivity"]["column_labels"]) + " |",
                "| --- | " + " | ".join("---:" for _ in valuation["sensitivity"]["column_labels"]) + " |",
            ]
            for label, row in zip(valuation["sensitivity"]["row_labels"], valuation["sensitivity"]["matrix"]):
                lines.append("| " + label + " | " + " | ".join(_money(value) for value in row) + " |")
            if valuation.get("reverse") is not None:
                reverse = valuation["reverse"]
                lines += [
                    "",
                    "### Reverse DCF",
                    "",
                    f"Solved: **{reverse.get('solved')}**. "
                    + (f"Implied terminal growth **{_pct(reverse.get('implied_value'))}** for target "
                       f"{_money(reverse.get('target_price'))} USD per share." if reverse.get("solved")
                       else _excerpt(reverse.get("reason"), 160)),
                ]
        price = metrics.get("price")
        lines += [
            "",
            "## Historical availability and missing information",
            "",
            f"- The report is computed as of **{workspace['as_of']}** in **{workspace['mode']}** mode; "
            "filings accepted after that instant are excluded by the existing evidence kernel.",
            f"- Market price: **{'not bundled' if price is None else _money(price) + ' USD (' + str(metrics.get('price_source')) + ')'}**.",
            "- Not available: qualitative business narrative, management guidance, sell-side estimates, "
            "licensed consensus data, evaluated bond prices and low-latency news.",
        ]
        if coverage["missing_core_concepts"]:
            lines.append("- Missing core concepts: " + ", ".join(coverage["missing_core_concepts"]) + ".")
        if metrics.get("missing"):
            lines.append("- Missing latest-period metrics: " + ", ".join(metrics["missing"]) + ".")
        lines += [
            "",
            "## Risks visible in the reported data",
            "",
            f"- Free cash flow is **{_money(_value(metrics, 'free_cash_flow'))} USD** after absolute capex; "
            "capital intensity can make a DCF negative even when accounting profit is positive.",
            f"- Total debt is **{_money(_value(metrics, 'total_debt'))} USD** against "
            f"**{_money(_value(metrics, 'cash_and_equivalents'))} USD** of cash and equivalents, where both are reported.",
            "- Accounting identity differences and missing fields are shown above. They are not adjusted away.",
            "- The model does not include litigation, regulatory, concentration or management-quality judgments.",
            "",
            "## Peer context",
            "",
            _peer_table(workspace["peer_comparison"]),
            "",
            "## Findings and audit verdict",
            "",
        ]
        findings = valuation.get("findings", [])
        if findings:
            lines += ["| Code | Severity | Finding |", "| --- | --- | --- |"]
            for finding in findings:
                lines.append(
                    f"| `{finding['code']}` | {finding['severity']} | "
                    f"{finding.get('message') or finding.get('detail') or ''} |"
                )
            lines.append("")
        else:
            lines += ["No audit findings were raised for this issuer.", ""]
        audit = valuation.get("audit")
        if audit:
            lines += [
                f"- Financial coverage valid: **{coverage['financial_coverage_valid']}** "
                f"(missing: {', '.join(coverage['financial_coverage_missing']) or 'none'}).",
                f"- Model executes: **{audit.get('arithmetic_valid', audit.get('passed'))}**; "
                f"verdict **{audit.get('verdict', 'n/a')}**; economically supported: "
                f"**{audit.get('economically_supported', valuation.get('economically_supported', False))}**.",
                "- Arithmetic consistency is not economic validity; discount rate, growth and "
                "terminal assumptions remain unvalidated analyst assumptions.",
            ]
        else:
            lines.append(
                f"- Financial coverage valid: **{coverage['financial_coverage_valid']}** "
                f"(missing: {', '.join(coverage['financial_coverage_missing']) or 'none'})."
            )
        lines += [
            "",
            "## Reproduction",
            "",
            "- report SHA-256 is recorded in the analysis metadata and the research package "
            "manifest; the digest covers this full document.",
            f"- Selection policy: `{workspace.get('metrics', {}).get('policy')}`",
            f"- Compiler: `{COMPILER_VERSION}`",
            f"- Source revision: `{os.environ.get('ATLAS_SOURCE_REVISION', 'working-tree')}`",
            "- The corresponding Research Application packages the financial snapshot, model spec, "
            "expected outputs and this report. The package is unsigned; its hash proves integrity, not publisher identity.",
            "",
        ]
        return "\n".join(lines) + "\n"

    # -------------------------------------------------------------------- package
    def _source_rows(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        return [
            dict(row) for row in self.db.query(
                f"SELECT source_id, name, kind, homepage, licence, redistribution, notes "
                f"FROM source WHERE source_id IN ({marks}) ORDER BY source_id", ids
            )
        ]

    def _institution_application(self, analysis: dict[str, Any], version: str = "1.0.0") -> dict[str, Any]:
        """Package a bank or insurer analysis without pretending it is an FEC DCF."""
        workspace = analysis["workspace"]
        valuation = analysis["valuation"]
        model = valuation["institution"]
        company = workspace["company"]
        coverage = workspace["coverage"]
        contract = model.get("contract") or {}
        as_of = workspace["as_of"]
        cik = str(company.get("cik") or "")
        source_rows = self._source_rows(["sec-edgar"])
        if not source_rows:
            raise MissingDataError("SEC source metadata is missing from this database")
        decisions = self.rights.decisions_for_metadata(source_rows)
        if not all(item["packaging_allowed"] for item in decisions):
            raise ValidationError("SEC source rights do not permit research package export")
        outputs = model["outputs"]
        expected = {
            key: outputs[key]
            for key in ("value_per_share", "calculated_equity_value", "realizable_common_price")
            if key in outputs
        }
        app_id = f"{APPLICATION_ID_PREFIX}-{cik}-{model['method']}"[:96]
        app = {
            "schema": APPLICATION_SCHEMA,
            "application_id": app_id,
            "name": f"Equity research · {company['legal_name']}",
            "version": version,
            "publisher": {"id": "atlas.first-party", "name": "Atlas Quant first-party"},
            "description": (
                f"Source-grounded {model['method']} equity research for {company['legal_name']} "
                f"({coverage.get('ticker') or company.get('cik')}) using SEC facts."
            ),
            "compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"},
            "runtime": {
                "kind": "report_bundle",
                "model_runtime": "atlas.report_bundle.v1",
                "report_sha256": analysis["metadata"]["report_sha256"],
                "model_version": model["model_version"],
            },
            "dependencies": {
                "compiler": COMPILER_VERSION,
                "operators": [],
                "model_runtime": "atlas.report_bundle.v1",
                "datasets": [{
                    "source_id": source_rows[0]["source_id"],
                    "required": True,
                    "redistribution": source_rows[0]["redistribution"],
                }],
            },
            "inputs": [
                {"key": key, "type": "Scalar", "unit": "fraction", "default": value,
                 "classification": "assumption"}
                for key, value in model["assumptions"].items()
            ],
            "outputs": [
                {"key": "value_per_share", "unit": "USD/share"},
                {"key": "calculated_equity_value", "unit": "USD"},
            ],
            "views": [
                {"id": "report", "type": "report", "title": "Equity research report"},
                {"id": "eligibility", "type": "table", "title": "Valuation eligibility contract"},
                {"id": "model", "type": "table", "title": "Institution model and sensitivity"},
                {"id": "evidence", "type": "evidence", "title": "Source records and X-Ray"},
                {"id": "limitations", "type": "limitations", "title": "Coverage and known limitations"},
            ],
            "sources": [{
                "source_id": source_rows[0]["source_id"],
                "name": source_rows[0]["name"],
                "kind": source_rows[0]["kind"],
                "homepage": source_rows[0].get("homepage"),
                "license": source_rows[0]["licence"],
                "redistribution": source_rows[0]["redistribution"],
                "rights_basis": decisions[0]["license"],
                "snapshot_paths": [
                    "data/financials.json", "artifacts/institution.json",
                    "artifacts/eligibility_contract.json", "report.md",
                ],
            }],
            "capabilities": [
                "read_approved_snapshot", "render_declarative_ui", "write_application_state",
            ],
            "resources": {
                "max_package_bytes": 8 * 1024 * 1024,
                "max_memory_mb": 256,
                "max_execution_seconds": 30,
            },
            "license": "Apache-2.0 for application and report metadata; SEC facts retain their public-domain terms.",
            "limitations": workspace["limitations"] + model.get("limitations", []),
            "created_at": as_of,
            "state": {
                "issuer_id": company["issuer_id"],
                "cik": company.get("cik"),
                "period_end": workspace["metrics"].get("period_end"),
                "report_sha256": analysis["metadata"]["report_sha256"],
                "valuation_fingerprint": None,
                "valuation_method": model["method"],
                "valuation_contract_state": contract.get("state"),
                "valuation_economically_supported": bool(model.get("economically_supported")),
                "institution_model_version": model["model_version"],
                "price_included": False,
            },
        }
        financials = {
            "schema": "atlas.equity_research.financials.v1",
            "issuer": company,
            "coverage": coverage,
            "metrics": workspace["metrics"],
            "statements": workspace["statements"],
            "history": workspace["history"],
            "quality_checks": workspace["quality_checks"],
            "provenance": workspace["provenance"],
            "limitations": workspace["limitations"],
        }
        files = {
            "data/financials.json": pretty(financials),
            "artifacts/institution.json": pretty(model),
            "artifacts/eligibility_contract.json": pretty(contract),
            "artifacts/expected_outputs.json": pretty(expected),
            "report.md": analysis["report"].encode("utf-8"),
            "sources.json": pretty({
                "schema": "atlas.application.sources.v1",
                "sources": app["sources"],
                "note": "Only SEC public-domain observations are packaged; no market prices are included.",
            }),
            "README.md": (
                f"# {app['name']}\n\n"
                f"Runtime: `atlas.report_bundle.v1` using `{model['model_version']}`. Built from SEC "
                f"facts as of {as_of}.\n\n"
                "This is a reproducible analysis bundle, not a DCF model. The eligibility contract "
                "records which verification gates the result has actually passed.\n"
            ).encode("utf-8"),
        }
        metadata = [
            {"path": "data/financials.json", "role": "approved_source_snapshot",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/institution.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/eligibility_contract.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/expected_outputs.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "report.md", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "text/markdown"},
            {"path": "sources.json", "role": "rights_manifest",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
        ]
        payload = build_package(
            app, files, file_metadata=metadata, built_at=as_of,
            source_revision=os.environ.get("ATLAS_SOURCE_REVISION", "working-tree"),
            reproducibility="computationally_reproducible",
        )
        return {
            "payload": payload,
            "application": app,
            "expected_outputs": expected,
            "report_sha256": analysis["metadata"]["report_sha256"],
        }

    def _application(self, analysis: dict[str, Any], version: str = "1.0.0") -> dict[str, Any]:
        if analysis["valuation"].get("institution"):
            return self._institution_application(analysis, version=version)
        workspace = analysis["workspace"]
        valuation = analysis["valuation"]
        if valuation["status"] != "supported":
            if valuation["status"] == "unsupported_methodology":
                raise ValidationError(
                    "this issuer cannot be packaged as a DCF valuation application: the selected "
                    "methodology is not economically valid for a financial institution",
                    eligibility=valuation["eligibility"],
                    reason=valuation.get("reason"),
                )
            raise MissingDataError(
                "this issuer cannot be packaged as a valuation application because required inputs are missing",
                reason=valuation.get("reason"),
            )
        dcf = valuation["dcf"]
        company = workspace["company"]
        coverage = workspace["coverage"]
        model_spec = dcf["model_spec"]
        assumptions = dcf["assumptions"]
        as_of = workspace["as_of"]
        cik = str(company.get("cik") or "")
        app_id = f"{APPLICATION_ID_PREFIX}-{cik}"[:96]
        source_rows = self._source_rows(["sec-edgar"])
        if not source_rows:
            raise MissingDataError("SEC source metadata is missing from this database")
        decisions = self.rights.decisions_for_metadata(source_rows)
        if not all(item["packaging_allowed"] for item in decisions):
            raise ValidationError("SEC source rights do not permit research package export")
        inputs = []
        units = {
            "revenue": "USD", "revenue_growth": "fraction", "operating_margin": "fraction",
            "tax_rate": "fraction", "da_pct": "fraction", "capex_pct": "fraction",
            "nwc_pct": "fraction", "wacc": "fraction", "terminal_growth": "fraction",
            "cash": "USD", "debt": "USD", "shares": "shares",
        }
        defaults = {
            "revenue": assumptions["revenue"],
            "revenue_growth": assumptions["revenue_growth"],
            "operating_margin": assumptions["operating_margin"],
            "tax_rate": assumptions["tax_rate"],
            "da_pct": assumptions["da_pct_revenue"],
            "capex_pct": assumptions["capex_pct_revenue"],
            "nwc_pct": assumptions["nwc_pct_revenue"],
            "wacc": assumptions["wacc"],
            "terminal_growth": assumptions["terminal_growth"],
            "cash": assumptions["cash"],
            "debt": assumptions["debt"],
            "shares": assumptions["shares"],
        }
        for item in model_spec.get("inputs", []):
            key = item["name"]
            inputs.append({
                "key": key,
                "type": item.get("type", "Scalar"),
                "unit": units.get(key, "unit"),
                "default": defaults[key],
                "classification": "assumption",
            })
        scalar_outputs = {
            "value_per_share": "USD/share", "equity_value": "USD",
            "enterprise_value": "USD", "pv_explicit": "USD",
            "pv_terminal": "USD", "terminal_value": "USD",
        }
        expected = {
            key: dcf["outputs"][key] for key in scalar_outputs if key in dcf["outputs"]
        }
        app = {
            "schema": APPLICATION_SCHEMA,
            "application_id": app_id,
            "name": f"Equity research · {company['legal_name']}",
            "version": version,
            "publisher": {"id": "atlas.first-party", "name": "Atlas Quant first-party"},
            "description": (
                f"Source-grounded equity research and reproducible DCF for {company['legal_name']} "
                f"({coverage.get('ticker') or company.get('cik')}) using SEC facts."
            ),
            "compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"},
            "runtime": {
                "kind": "fec_model",
                "model_runtime": "atlas.fec.model.v1",
                "report_sha256": analysis["metadata"]["report_sha256"],
            },
            "dependencies": {
                "compiler": COMPILER_VERSION,
                "operators": [
                    {"name": name, "version": value}
                    for name, value in sorted(dcf.get("manifest", {}).get("operator_versions", {}).items())
                ],
                "model_runtime": "atlas.fec.model.v1",
                "datasets": [{
                    "source_id": source_rows[0]["source_id"],
                    "required": True,
                    "redistribution": source_rows[0]["redistribution"],
                }],
            },
            "inputs": inputs,
            "outputs": [{"key": key, "unit": unit} for key, unit in scalar_outputs.items() if key in expected],
            "views": [
                {"id": "report", "type": "report", "title": "Equity research report"},
                {"id": "financials", "type": "table", "title": "Financial statements and quality checks"},
                {"id": "valuation", "type": "chart", "title": "DCF outputs and sensitivity"},
                {"id": "scenarios", "type": "scenario", "title": "Scenario comparison"},
                {"id": "evidence", "type": "evidence", "title": "Source records and X-Ray"},
                {"id": "limitations", "type": "limitations", "title": "Coverage and known limitations"},
            ],
            "sources": [{
                "source_id": source_rows[0]["source_id"],
                "name": source_rows[0]["name"],
                "kind": source_rows[0]["kind"],
                "homepage": source_rows[0].get("homepage"),
                "license": source_rows[0]["licence"],
                "redistribution": source_rows[0]["redistribution"],
                "rights_basis": decisions[0]["license"],
                "snapshot_paths": [
                    "data/financials.json", "artifacts/dcf.json",
                    "artifacts/model.json", "artifacts/scenarios.json",
                    "artifacts/sensitivity.json", "artifacts/dcf_audit.json", "report.md",
                ],
            }],
            "capabilities": [
                "read_approved_snapshot", "execute_fec_operator",
                "render_declarative_ui", "write_application_state",
            ],
            "resources": {
                "max_package_bytes": 8 * 1024 * 1024,
                "max_memory_mb": 256,
                "max_execution_seconds": 30,
            },
            "license": "Apache-2.0 for application and report metadata; SEC facts retain their public-domain terms.",
            "limitations": workspace["limitations"],
            "created_at": as_of,
            "state": {
                "issuer_id": company["issuer_id"],
                "cik": company.get("cik"),
                "period_end": workspace["metrics"].get("period_end"),
                "report_sha256": analysis["metadata"]["report_sha256"],
                "valuation_fingerprint": dcf.get("fingerprint"),
                "valuation_audit_verdict": valuation["audit"]["verdict"],
                "valuation_economically_supported": valuation["audit"]["economically_supported"],
                "share_denominator_basis": valuation["audit"]["share_denominator"]["basis"],
                "price_included": False,
            },
        }
        financials = {
            "schema": "atlas.equity_research.financials.v1",
            "issuer": company,
            "coverage": coverage,
            "metrics": workspace["metrics"],
            "statements": workspace["statements"],
            "history": workspace["history"],
            "quality_checks": workspace["quality_checks"],
            "provenance": workspace["provenance"],
            "limitations": workspace["limitations"],
        }
        dcf_artifact = {
            "schema": "atlas.equity_research.dcf.v1",
            "issuer": dcf.get("issuer"),
            "outputs": dcf.get("outputs"),
            "assumptions": assumptions,
            "audit": _without_timings({
                **(dcf.get("audit") or {}),
                "trace": _stable_trace((dcf.get("audit") or {}).get("trace", [])),
            }),
            "data_status": dcf.get("data_status"),
            "fingerprint": dcf.get("fingerprint"),
            "model_version": model_spec.get("version"),
        }
        files = {
            "data/financials.json": pretty(financials),
            "artifacts/dcf.json": pretty(dcf_artifact),
            "artifacts/model.json": pretty(model_spec),
            "artifacts/expected_outputs.json": pretty(expected),
            "artifacts/scenarios.json": pretty(valuation["scenarios"]),
            "artifacts/sensitivity.json": pretty(valuation["sensitivity"]),
            "artifacts/dcf_audit.json": pretty(valuation["audit"]),
            "report.md": analysis["report"].encode("utf-8"),
            "sources.json": pretty({
                "schema": "atlas.application.sources.v1",
                "sources": app["sources"],
                "note": "Only SEC public-domain observations are packaged; no licensed market prices are included.",
            }),
            "README.md": (
                f"# {app['name']}\n\n"
                f"Runtime: `{app['runtime']['model_runtime']}`. Built from SEC facts as of {as_of} "
                "(the latest evidence availability in the packaged snapshot, not wall-clock time).\n\n"
                "The package is declarative and unsigned. Its SHA-256 proves integrity only. "
                "Install it in Atlas, verify the package, and execute it to reproduce the DCF outputs.\n"
            ).encode("utf-8"),
        }
        metadata = [
            {"path": "data/financials.json", "role": "approved_source_snapshot",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/dcf.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/model.json", "role": "model_artifact",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/expected_outputs.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/scenarios.json", "role": "scenario_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "artifacts/sensitivity.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "report.md", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "text/markdown"},
            {"path": "artifacts/dcf_audit.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
            {"path": "sources.json", "role": "rights_manifest",
             "rights": "public_domain", "source_ids": ["sec-edgar"],
             "media_type": "application/json"},
        ]
        payload = build_package(
            app, files, file_metadata=metadata, built_at=as_of,
            source_revision=os.environ.get("ATLAS_SOURCE_REVISION", "working-tree"),
            reproducibility="computationally_reproducible",
        )
        return {
            "payload": payload,
            "application": app,
            "expected_outputs": expected,
            "report_sha256": analysis["metadata"]["report_sha256"],
        }

    def _package_cutoff(self, identifier: str) -> str:
        """Pin a package to the latest evidence availability, not to wall-clock time.

        A package built twice must be byte-identical. Using ``utcnow()`` inside the report
        makes the cutoff differ between two builds seconds apart, so the package cutoff is
        the data vintage itself: the latest moment at which any packaged fact was public.
        """
        issuer = read_models.resolve_company(self.db, identifier)
        value = self.db.scalar(
            "SELECT MAX(availability_time) FROM evidence WHERE entity_id=?",
            (issuer["issuer_id"],), default=None,
        )
        return value or iso(utcnow())

    def create_package(self, identifier: str, *, assumptions: dict[str, Any] | None = None,
                       as_of: str | None = None, mode: str | None = None,
                       target_price: float | None = None,
                       version: str = "1.0.0") -> dict[str, Any]:
        analysis = self.analyse(
            identifier, assumptions=assumptions,
            as_of=as_of or self._package_cutoff(identifier), mode=mode,
            target_price=target_price,
        )
        built = self._application(analysis, version=version)
        from ..applications.contracts import read_package

        loaded = read_package(built["payload"])
        return {
            "schema": "atlas.equity_research.package.v1",
            "payload": built["payload"],
            "manifest": loaded["manifest"],
            "package_sha256": loaded["package_sha256"],
            "package_id": loaded["manifest"]["package_id"],
            "application_id": built["application"]["application_id"],
            "version": built["application"]["version"],
            "report_sha256": built["report_sha256"],
            "expected_outputs": built["expected_outputs"],
            "reproducibility": loaded["manifest"]["reproducibility"]["level"],
            "report": analysis["report"],
            "valuation": analysis["valuation"],
            "metadata": analysis["metadata"],
        }


def _peer_table(peers: dict[str, Any]) -> str:
    rows = peers.get("rows", [])
    if not rows:
        return "No peer rows are available."
    labels = peers.get("labels", {})
    keys = ["revenue_growth", "gross_margin", "operating_margin", "net_margin", "roe"]
    available = [key for key in keys if any(key in row.get("metrics", {}) for row in rows)]
    header = "| Company | " + " | ".join(labels.get(key, key) for key in available) + " |"
    lines = [
        header,
        "| --- | " + " | ".join("---:" for _ in available) + " |",
    ]
    for row in rows[:12]:
        cells = []
        for key in available:
            item = row.get("metrics", {}).get(key)
            if item is None:
                cells.append("—")
            elif key in {"revenue_growth", "gross_margin", "operating_margin", "net_margin", "roe"}:
                cells.append(_pct(item.get("value")))
            else:
                cells.append(str(item.get("text")))
        name = row.get("ticker") or row.get("legal_name")
        if row.get("is_target"):
            name = f"**{name}**"
        lines.append("| " + str(name) + " | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        f"Universe: {peers.get('universe', {}).get('issuers', 0)} issuers stored in this database. "
        "This is not a curated industry index; missing metrics are omitted, never zero-filled."
    )
    return "\n".join(lines)
