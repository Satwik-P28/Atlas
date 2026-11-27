"""Research workflows over data that has actually been integrated.

This is a thin orchestration layer. Statements, metrics and valuation come from the
existing Atlas read models and valuation core; nothing here re-implements accounting or
invents a number. Every workflow reports the evidence it used and refuses to run a model
whose inputs are absent.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..core.temporal import iso, utcnow
from ..entities.master import SecurityMaster
from ..research.equity import EquityResearchService
from ..storage.db import open_database
from ..terminal import read_models
from ..terminal.metric_store import get_issuer_metrics

HISTORICAL_SCHEMA = "atlas.open_data.research_workflows.v1"


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _metric(payload: dict[str, Any], key: str) -> float | None:
    item = (payload.get("metrics") or {}).get(key)
    if isinstance(item, dict) and item.get("value") is not None:
        try:
            return float(item["value"])
        except (TypeError, ValueError):
            return None
    return None


def company_search(atlas_db: str, query: str, *, limit: int = 25) -> dict[str, Any]:
    db = open_database(atlas_db)
    try:
        master = SecurityMaster(db)
        needle = f"%{query.strip()}%"
        rows = [dict(row) for row in db.query(
            "SELECT i.issuer_id, i.cik, i.legal_name, i.sic FROM issuer i "
            "WHERE i.legal_name LIKE ? OR i.cik LIKE ? OR EXISTS ("
            " SELECT 1 FROM security s JOIN ticker_assignment t ON t.listing_id IN "
            " (SELECT listing_id FROM listing WHERE security_id=s.security_id) "
            " WHERE s.issuer_id=i.issuer_id AND t.ticker LIKE ?) "
            "ORDER BY i.legal_name COLLATE NOCASE LIMIT ?",
            (needle, needle, needle.upper(), limit),
        )]
        for row in rows:
            issuer = master.issuer(row["issuer_id"])
            row["ticker"] = None
            for security in master.securities_for_issuer(row["issuer_id"]):
                current = master.current_ticker(security["security_id"])
                if current:
                    row["ticker"] = current["ticker"]
                    break
            row["evidence"] = int(db.scalar(
                "SELECT COUNT(*) FROM evidence WHERE entity_id=?", (row["issuer_id"],), 0
            ) or 0)
        return {"schema": HISTORICAL_SCHEMA, "workflow": "company_search", "query": query,
                "count": len(rows), "results": rows}
    finally:
        db.close()


def financials(atlas_db: str, identifier: str, *, as_of: str | None = None,
               period: str = "FY", limit: int = 6) -> dict[str, Any]:
    db = open_database(atlas_db)
    try:
        statements = {
            name: read_models.statements(db, identifier, statement=name, period=period,
                                         as_of=as_of, limit=limit)
            for name in ("income", "balance", "cashflow")
        }
        issuer = None
        for statement in statements.values():
            if statement.get("issuer"):
                issuer = statement["issuer"]
                break
        metrics = {}
        if issuer:
            metrics = get_issuer_metrics(db, issuer["issuer_id"], as_of=as_of)
        values = {
            key: _metric(metrics, key) for key in (
                "revenue", "gross_profit", "operating_income", "net_income",
                "operating_cash_flow", "capex", "free_cash_flow", "assets", "liabilities",
                "equity", "cash_and_equivalents", "eps_diluted", "shares_outstanding",
            )
        }
        ratios = {
            "gross_margin": _ratio(values["gross_profit"], values["revenue"]),
            "operating_margin": _ratio(values["operating_income"], values["revenue"]),
            "net_margin": _ratio(values["net_income"], values["revenue"]),
            "roa": _ratio(values["net_income"], values["assets"]),
            "roe": _ratio(values["net_income"], values["equity"]),
            "liabilities_to_assets": _ratio(values["liabilities"], values["assets"]),
            "fcf_margin": _ratio(values["free_cash_flow"], values["revenue"]),
        }
        return {
            "schema": HISTORICAL_SCHEMA, "workflow": "financials", "identifier": identifier,
            "as_of": metrics.get("as_of") if metrics else None,
            "issuer": issuer,
            "statements": {name: {"periods": [column.get("period_end") for column in value.get("columns") or []],
                                  "rows": len(value.get("rows") or []),
                                  "excluded_not_yet_available": value.get("excluded_not_yet_available")}
                           for name, value in statements.items()},
            "metrics": values,
            "ratios": ratios,
            "missing": metrics.get("missing") if metrics else None,
            "statement_payloads": statements,
        }
    finally:
        db.close()


def valuation(atlas_db: str, identifier: str, *, as_of: str | None = None,
              assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    db = open_database(atlas_db)
    try:
        service = EquityResearchService(db)
        payload = service.valuation(identifier, assumptions=assumptions, as_of=as_of)
        return {"schema": HISTORICAL_SCHEMA, "workflow": "valuation",
                "identifier": identifier, "result": payload}
    finally:
        db.close()


def run_models(atlas_db: str, *, limit: int = 25, as_of: str | None = None) -> dict[str, Any]:
    """Run the method-appropriate valuation for the most evidence-rich issuers."""
    db = open_database(atlas_db)
    try:
        issuers = [dict(row) for row in db.query(
            "SELECT entity_id AS issuer_id, COUNT(*) AS facts FROM evidence "
            "GROUP BY entity_id ORDER BY facts DESC LIMIT ?", (limit,),
        )]
        service = EquityResearchService(db)
        items = []
        for row in issuers:
            issuer = service.master.issuer(row["issuer_id"])
            if issuer is None:
                continue
            try:
                result = service.valuation(issuer["issuer_id"], as_of=as_of)
            except Exception as exc:  # noqa: BLE001 - one issuer must not abort the run
                items.append({"issuer_id": row["issuer_id"], "cik": issuer.get("cik"),
                              "legal_name": issuer.get("legal_name"), "status": "error",
                              "error": f"{type(exc).__name__}: {exc}"})
                continue
            dcf = result.get("dcf") or {}
            institution = result.get("institution") or {}
            items.append({
                "issuer_id": row["issuer_id"],
                "cik": issuer.get("cik"),
                "legal_name": issuer.get("legal_name"),
                "evidence_facts": row["facts"],
                "method": result.get("method"),
                "status": result.get("status"),
                "executes": bool(result.get("executes")),
                "economically_supported": bool(result.get("economically_supported")),
                "value_per_share": (dcf.get("outputs") or {}).get("value_per_share")
                if dcf else (institution.get("outputs") or {}).get("value_per_share"),
                "contract_state": (result.get("contract") or {}).get("state"),
                "reason": result.get("reason"),
            })
        return {
            "schema": HISTORICAL_SCHEMA,
            "workflow": "run_models",
            "generated_at": iso(utcnow()),
            "issuers": len(items),
            "executed": sum(1 for item in items if item.get("executes")),
            "economically_supported": sum(1 for item in items if item.get("economically_supported")),
            "items": items,
        }
    finally:
        db.close()


def comparables(atlas_db: str, identifier: str, *, limit: int = 10) -> dict[str, Any]:
    """Peer comparison by reported SIC, with no invented peer taxonomy or prices."""
    db = open_database(atlas_db)
    try:
        master = SecurityMaster(db)
        target = master.issuer(identifier) or master.issuer_by_cik(identifier)
        if target is None:
            issuer_rows = db.query(
                "SELECT i.* FROM issuer i JOIN security s ON s.issuer_id=i.issuer_id "
                "JOIN listing l ON l.security_id=s.security_id JOIN ticker_assignment t "
                "ON t.listing_id=l.listing_id WHERE t.ticker=? LIMIT 1", (identifier.upper(),),
            )
            target = dict(issuer_rows[0]) if issuer_rows else None
        if target is None:
            raise KeyError(f"unknown issuer {identifier!r}")
        sic = str(target.get("sic") or "")[:2]
        peers = [dict(row) for row in db.query(
            "SELECT * FROM issuer WHERE sic LIKE ? AND issuer_id != ? ORDER BY legal_name LIMIT ?",
            (f"{sic}%", target["issuer_id"], limit),
        )] if sic else []
        rows = []
        for issuer in [target] + peers:
            metrics = get_issuer_metrics(db, issuer["issuer_id"])
            rows.append({
                "issuer_id": issuer["issuer_id"], "cik": issuer.get("cik"),
                "legal_name": issuer["legal_name"], "sic": issuer.get("sic"),
                "revenue": _metric(metrics, "revenue"),
                "net_income": _metric(metrics, "net_income"),
                "net_margin": _ratio(_metric(metrics, "net_income"), _metric(metrics, "revenue")),
                "roe": _ratio(_metric(metrics, "net_income"), _metric(metrics, "equity")),
            })
        return {"schema": HISTORICAL_SCHEMA, "workflow": "comparables",
                "target": target["issuer_id"], "sic_prefix": sic,
                "peer_basis": "first two SIC digits; not a curated peer taxonomy",
                "rows": rows}
    finally:
        db.close()


def screen(atlas_db: str, *, min_revenue: float | None = None, min_net_margin: float | None = None,
           min_roe: float | None = None, limit: int = 50) -> dict[str, Any]:
    """Historical screening over reported metrics; no forward estimates are implied."""
    db = open_database(atlas_db)
    try:
        issuers = [dict(row) for row in db.query(
            "SELECT issuer_id, cik, legal_name, sic FROM issuer WHERE is_active=1 "
            "ORDER BY legal_name LIMIT 5000"
        )]
        results = []
        for issuer in issuers:
            metrics = get_issuer_metrics(db, issuer["issuer_id"])
            revenue = _metric(metrics, "revenue")
            margin = _ratio(_metric(metrics, "net_income"), revenue)
            roe = _ratio(_metric(metrics, "net_income"), _metric(metrics, "equity"))
            if min_revenue is not None and (revenue is None or revenue < min_revenue):
                continue
            if min_net_margin is not None and (margin is None or margin < min_net_margin):
                continue
            if min_roe is not None and (roe is None or roe < min_roe):
                continue
            results.append({**issuer, "revenue": revenue, "net_margin": margin, "roe": roe})
            if len(results) >= limit:
                break
        return {"schema": HISTORICAL_SCHEMA, "workflow": "screen",
                "criteria": {"min_revenue": min_revenue, "min_net_margin": min_net_margin,
                             "min_roe": min_roe},
                "matched": len(results), "results": results,
                "note": "Only issuers with a computed metric can match a metric threshold."}
    finally:
        db.close()
