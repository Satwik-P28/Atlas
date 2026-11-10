"""Terminal read models.

This module is the only place the HTTP layer gets financial data. Every value comes
from a Phase 1 query (``EvidenceKernel.as_of``, ``BarStore``, ``ActionStore``,
``SecurityMaster``); nothing here re-implements point-in-time selection, adjustment or
identity resolution, and nothing writes evidence.

Two rules are enforced in code, not just documentation:

* a fact is never returned without its ``evidence_id``;
* a derived metric always carries its formula, its input evidence ids and the
  period/price dates it mixed. If an input is missing the metric is ``missing`` with a
  reason instead of being computed on a substitute.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

from ..core.concepts import concept_metadata
from ..core.errors import UnknownEntity, ValidationError
from ..core.temporal import AsOfMode, iso, iso_date, parse_date, utcnow
from ..entities.master import SecurityMaster
from ..evidence.kernel import EvidenceKernel, SELECTION_POLICY
from ..market.actions import ActionStore
from ..market.adjust import MODE_SPLIT, MODE_TOTAL_RETURN, split_adjust, total_return
from ..market.bars import Bar, BarStore
from ..market import evidence as market_evidence
from ..storage.db import Database
from .indicators import compute_many

TERMINAL_SCHEMA = "atlas.terminal.v1"

RANGE_DAYS = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366, "2Y": 731, "5Y": 1826, "MAX": 12000}
FORM_WORDS = {"10-K": "Annual report", "10-Q": "Quarterly report", "8-K": "Current report", "DEF 14A": "Proxy statement"}

DERIVED_FORMULAS = {
    "gross_margin": "gross_profit / revenue",
    "operating_margin": "operating_income / revenue",
    "net_margin": "net_income / revenue",
    "revenue_growth": "revenue_t / revenue_{t-1} - 1 (same fiscal period type, duration within 10 days)",
    "liabilities_to_assets": "liabilities / assets",
    "roe": "net_income / equity",
    "total_debt": "long_term_debt + short_term_debt",
    "free_cash_flow": "operating_cash_flow - abs(capex)",
    "market_cap": "last_close * shares_outstanding",
    "pe": "market_cap / net_income",
    "ps": "market_cap / revenue",
    "ev": "market_cap + total_debt - cash_and_equivalents",
    "earnings_yield": "net_income / market_cap",
    "fcf_yield": "free_cash_flow / market_cap",
    "book_to_market": "equity / market_cap",
    "ev_revenue": "ev / revenue",
}


# --------------------------------------------------------------------- helpers
def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _text(value: Decimal, unit: str) -> str:
    if unit == "fraction":
        return f"{value:.6f}"
    if unit in {"USD/share", "shares"}:
        return f"{value:.4f}" if unit == "USD/share" else f"{value:.0f}"
    return f"{value:.2f}"


def _sources(db: Database) -> list[dict[str, Any]]:
    rows = db.query("SELECT source_id, name, kind, licence, redistribution FROM source ORDER BY source_id")
    return [{key: row[key] for key in row.keys()} for row in rows]


def _source_status(db: Database, source_id: str | None) -> str:
    if not source_id:
        return "unknown"
    row = db.query_one("SELECT kind FROM source WHERE source_id = ?", (source_id,))
    if row is None:
        return "unknown"
    return {
        "synthetic": "synthetic",
        "sec_edgar": "reported",
        "csv_import": "imported",
        "market_data": "reported",
    }.get(row["kind"], row["kind"])


def _default_mic(master: SecurityMaster, security_id: str) -> str | None:
    for listing in master.listings(security_id):
        if listing.get("is_primary"):
            return str(listing["mic"])
    listings = master.listings(security_id)
    return str(listings[0]["mic"]) if listings else None


def _ticker(
    master: SecurityMaster, security_id: str, *, as_of: str | None = None
) -> dict[str, Any] | None:
    current = master.current_ticker(security_id, as_of=as_of)
    if current is None:
        return None
    return {
        "ticker": current.get("ticker"),
        "mic": current.get("mic"),
        "valid_from": current.get("valid_from"),
        "status": current.get("status"),
        "confidence": current.get("confidence"),
    }


def _security_summary(master: SecurityMaster, db: Database, security: dict[str, Any]) -> dict[str, Any]:
    bars = BarStore(db)
    mic = _default_mic(master, security["security_id"])
    coverage = bars.coverage(security["security_id"], mic) if mic else {"sessions": 0}
    latest = (
        market_evidence.latest_observation(db, security["security_id"], mic=mic).observation
        if mic else None
    )
    return {
        "security_id": security["security_id"],
        "issuer_id": security["issuer_id"],
        "class_designation": security.get("class_designation"),
        "security_type": security.get("security_type"),
        "currency": security.get("currency"),
        "status": security.get("status"),
        "tickers": [_ticker(master, security["security_id"])] if _ticker(master, security["security_id"]) else [],
        "mic": mic,
        "last_close": latest.close if latest else None,
        "last_bar_date": latest.session_date if latest else None,
        "sessions": int(coverage.get("sessions") or 0),
        "data_status": _source_status(db, latest.source_id if latest else None),
    }


def _issuer_row(master: SecurityMaster, db: Database, issuer: dict[str, Any]) -> dict[str, Any]:
    securities = [
        _security_summary(master, db, security)
        for security in master.securities_for_issuer(issuer["issuer_id"])
    ]
    return {
        "issuer_id": issuer["issuer_id"],
        "cik": issuer.get("cik"),
        "legal_name": issuer["legal_name"],
        "entity_type": issuer.get("entity_type"),
        "sic": issuer.get("sic"),
        "fiscal_year_end": issuer.get("fiscal_year_end"),
        "domicile_country": issuer.get("domicile_country"),
        "securities": securities,
        "evidence_count": int(
            db.scalar("SELECT COUNT(*) FROM evidence WHERE entity_id = ?", (issuer["issuer_id"],), 0) or 0
        ),
        "filing_count": int(
            db.scalar("SELECT COUNT(*) FROM filing WHERE issuer_id = ?", (issuer["issuer_id"],), 0) or 0
        ),
    }


def _batch_security_summaries(db: Database, securities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build every security summary with a fixed number of queries, not per security.

    The company list previously ran 2–3 queries per security (latest close, coverage,
    ticker) and the latest-close query scanned the bar table. Query count now depends on
    the number of issuers, not the number of securities × rows.
    """
    if not securities:
        return {}
    ids = [security["security_id"] for security in securities]
    marks = ",".join("?" for _ in ids)
    today = iso_date(utcnow())
    listings = db.query(
        f"SELECT * FROM listing WHERE security_id IN ({marks}) ORDER BY is_primary DESC, valid_from",
        ids,
    )
    listing_by_security: dict[str, list[dict[str, Any]]] = {sid: [] for sid in ids}
    for row in listings:
        listing_by_security[row["security_id"]].append({key: row[key] for key in row.keys()})
    ticker_rows = db.query(
        f"SELECT ta.ticker, ta.status, ta.confidence, ta.valid_from, ta.valid_to, l.security_id, l.mic "
        f"FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
        f"WHERE l.security_id IN ({marks}) AND ta.status != 'retracted' AND ta.valid_from <= ? "
        f"AND (ta.valid_to IS NULL OR ta.valid_to >= ?) "
        f"ORDER BY l.is_primary DESC, ta.valid_from DESC",
        ids + [today, today],
    )
    ticker_by_security: dict[str, dict[str, Any]] = {}
    for row in ticker_rows:
        ticker_by_security.setdefault(
            row["security_id"],
            {
                "ticker": row["ticker"],
                "mic": row["mic"],
                "valid_from": row["valid_from"],
                "status": row["status"],
                "confidence": row["confidence"],
            },
        )
    coverage = {
        row["security_id"]: int(row["sessions"] or 0)
        for row in db.query(
            f"SELECT security_id, COUNT(DISTINCT ts_utc) AS sessions FROM bar "
            f"WHERE security_id IN ({marks}) GROUP BY security_id",
            ids,
        )
    }

    bars = BarStore(db)
    summaries: dict[str, dict[str, Any]] = {}
    for security in securities:
        security_id = security["security_id"]
        rows = listing_by_security.get(security_id, [])
        primary = next((row for row in rows if row.get("is_primary")), rows[0] if rows else None)
        mic = str(primary["mic"]) if primary else None
        latest = (
            market_evidence.latest_observation(db, security_id, mic=mic).observation
            if mic else None
        )
        ticker = ticker_by_security.get(security_id)
        summaries[security_id] = {
            "security_id": security_id,
            "issuer_id": security["issuer_id"],
            "class_designation": security.get("class_designation"),
            "security_type": security.get("security_type"),
            "currency": security.get("currency"),
            "status": security.get("status"),
            "tickers": [ticker] if ticker else [],
            "mic": mic,
            "last_close": latest.close if latest else None,
            "last_bar_date": latest.session_date if latest else None,
            "sessions": coverage.get(security_id, 0),
            "data_status": _source_status(db, latest.source_id if latest else None),
        }
    return summaries


def _batch_issuer_rows(db: Database, issuers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not issuers:
        return []
    issuer_ids = [issuer["issuer_id"] for issuer in issuers]
    marks = ",".join("?" for _ in issuer_ids)
    securities = db.query(
        f"SELECT * FROM security WHERE issuer_id IN ({marks}) AND is_active = 1 "
        f"ORDER BY issuer_id, class_designation",
        issuer_ids,
    )
    summaries = _batch_security_summaries(db, [{key: row[key] for key in row.keys()} for row in securities])
    evidence_counts = {
        row["entity_id"]: int(row["n"])
        for row in db.query(
            f"SELECT entity_id, COUNT(*) AS n FROM evidence WHERE entity_id IN ({marks}) GROUP BY entity_id",
            issuer_ids,
        )
    }
    filing_counts = {
        row["issuer_id"]: int(row["n"])
        for row in db.query(
            f"SELECT issuer_id, COUNT(*) AS n FROM filing WHERE issuer_id IN ({marks}) GROUP BY issuer_id",
            issuer_ids,
        )
    }
    built: list[dict[str, Any]] = []
    for issuer in issuers:
        issuer_id = issuer["issuer_id"]
        built.append(
            {
                "issuer_id": issuer_id,
                "cik": issuer.get("cik"),
                "legal_name": issuer["legal_name"],
                "entity_type": issuer.get("entity_type"),
                "sic": issuer.get("sic"),
                "fiscal_year_end": issuer.get("fiscal_year_end"),
                "domicile_country": issuer.get("domicile_country"),
                "securities": [
                    summaries[security["security_id"]]
                    for security in securities
                    if security["issuer_id"] == issuer_id and security["security_id"] in summaries
                ],
                "evidence_count": evidence_counts.get(issuer_id, 0),
                "filing_count": filing_counts.get(issuer_id, 0),
            }
        )
    return built


# ------------------------------------------------------------------- companies
def list_companies(db: Database, *, q: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Company list, batched and cached by database generation."""
    from .cache import get_or_compute

    def compute() -> list[dict[str, Any]]:
        rows = db.query("SELECT * FROM issuer WHERE is_active = 1 ORDER BY legal_name COLLATE NOCASE")
        companies = _batch_issuer_rows(db, [{key: row[key] for key in row.keys()} for row in rows])
        needle = (q or "").strip().lower()
        if needle:
            def matches(company: dict[str, Any]) -> bool:
                haystack = [str(company.get("legal_name") or ""), str(company.get("cik") or "")]
                haystack.extend(str(t.get("ticker") or "") for s in company["securities"] for t in s["tickers"])
                return any(needle in value.lower() for value in haystack)

            companies = [company for company in companies if matches(company)]
        return companies[: max(1, min(limit, 500))]

    return get_or_compute(db, "companies", {"q": q, "limit": limit}, compute)


def resolve_company(db: Database, identifier: str) -> dict[str, Any]:
    """Resolve an issuer id, CIK or ticker. Ambiguity is an error, never a guess."""
    master = SecurityMaster(db)
    if identifier.startswith("ISS-"):
        profile = master.issuer_profile(issuer_id=identifier)
        return profile["issuer"]
    if identifier.isdigit():
        return master.require_issuer_by_cik(identifier)
    resolution = master.resolve_ticker(identifier)
    if resolution.ambiguous:
        raise ValidationError(
            "ticker resolves to more than one security",
            ticker=identifier,
            candidates=[c.to_dict() for c in resolution.candidates],
        )
    if resolution.resolved is None:
        raise UnknownEntity("ticker is not known to Atlas", ticker=identifier)
    candidate = resolution.require_single()
    issuer = master.issuer(candidate.issuer_id)
    if issuer is None:
        raise UnknownEntity("ticker resolved to a security without an issuer", ticker=identifier)
    return issuer


def company_detail(db: Database, identifier: str) -> dict[str, Any]:
    master = SecurityMaster(db)
    issuer = resolve_company(db, identifier)
    row = _issuer_row(master, db, issuer)
    precision = db.query(
        "SELECT availability_precision AS precision, COUNT(*) AS n FROM evidence WHERE entity_id = ? "
        "GROUP BY availability_precision",
        (issuer["issuer_id"],),
    )
    by_precision = {r["precision"]: int(r["n"]) for r in precision}
    latest_filing = db.query_one(
        "SELECT accession_number, form_type, filed_date, acceptance_datetime FROM filing "
        "WHERE issuer_id = ? ORDER BY filed_date DESC, accession_number DESC LIMIT 1",
        (issuer["issuer_id"],),
    )
    warnings: list[str] = []
    if by_precision.get("date", 0):
        warnings.append(
            f"{by_precision['date']} fact(s) carry date-precision availability; a same-day answer "
            "before the filing acceptance time may be unavailable"
        )
    if by_precision.get("unknown", 0):
        warnings.append(f"{by_precision['unknown']} fact(s) have unevidenced availability and are excluded from public views")
    warnings.append("ticker valid_from is the observation date, not an evidenced listing date")
    row.update(
        {
            "availability": {
                "exact": by_precision.get("exact", 0),
                "date": by_precision.get("date", 0),
                "unknown": by_precision.get("unknown", 0),
            },
            "latest_filing": dict(latest_filing) if latest_filing else None,
            "warnings": warnings,
            "schema": TERMINAL_SCHEMA,
        }
    )
    return row


def search(db: Database, q: str) -> list[dict[str, Any]]:
    companies = list_companies(db, q=q, limit=20)
    return [
        {
            "type": "company",
            "issuer_id": company["issuer_id"],
            "label": company["legal_name"],
            "cik": company["cik"],
            "tickers": [t["ticker"] for s in company["securities"] for t in s["tickers"] if t.get("ticker")],
            "security_id": company["securities"][0]["security_id"] if company["securities"] else None,
            "evidence_count": company["evidence_count"],
        }
        for company in companies
    ]


# ------------------------------------------------------------------ statements
def _coerce_mode(mode: str | None) -> str:
    value = mode or AsOfMode.PUBLIC_AVAILABLE.value
    try:
        return AsOfMode(value).value
    except ValueError:
        raise ValidationError(
            "unknown as-of mode", mode=value, supported=[m.value for m in AsOfMode]
        )


def _as_of(as_of: str | None) -> str:
    return iso(as_of) if as_of else iso(utcnow())


def _duration_days(fact: dict[str, Any]) -> int | None:
    start, end = fact.get("period_start"), fact.get("period_end")
    if not start or not end:
        return None
    try:
        return (parse_date(end) - parse_date(start)).days
    except (ValueError, TypeError):
        return None


def _statement_rows(statement: str) -> list[dict[str, Any]]:
    meta = concept_metadata()
    return [
        {
            "concept": key,
            "label": str(value.get("label") or key),
            "unit": value.get("unit") or value.get("canonical_unit"),
            # The registry declares whether a concept is a duration or an instant. The
            # fact's own classification is not trusted here: a balance-sheet concept is
            # an instant by definition, and a payload that stores a zero-length window
            # must not make it disappear from the balance sheet.
            "axis": "instant" if value.get("period_type") == "instant" else "duration",
        }
        for key, value in meta.items()
        if value.get("statement") == statement
    ]


def statements(
    db: Database,
    issuer_identifier: str,
    *,
    statement: str = "income",
    period: str = "FY",
    as_of: str | None = None,
    mode: str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    if statement not in {"income", "balance", "cashflow"}:
        raise ValidationError("unknown statement", statement=statement, supported=["income", "balance", "cashflow"])
    if period not in {"FY", "Q"}:
        raise ValidationError("period must be FY or Q", period=period)
    limit = max(1, min(int(limit), 20))
    issuer = resolve_company(db, issuer_identifier)
    instant = _as_of(as_of)
    resolved_mode = _coerce_mode(mode)
    kernel = EvidenceKernel(db)
    result = kernel.as_of(
        entity_id=issuer["issuer_id"],
        as_of=instant,
        mode=resolved_mode,
        statement=statement,
        include_unknown=False,
    )
    rows = _statement_rows(statement)
    axis = {row["concept"]: row["axis"] for row in rows}
    wanted = set(axis)
    facts = [fact for fact in result.facts if fact.concept in wanted]

    def keep(fact: Any) -> bool:
        if axis.get(fact.concept) == "instant":
            return bool(fact.period_end)
        days = _duration_days(fact.to_dict())
        if days is None:
            return False
        if period == "FY":
            return 330 <= days <= 400 and (fact.fiscal_period in (None, "FY") or fact.fiscal_period == "FY")
        return 60 <= days <= 120 and (fact.fiscal_period or "").startswith("Q")

    facts = [fact for fact in facts if keep(fact)]
    ends = sorted({fact.period_end for fact in facts if fact.period_end}, reverse=True)[:limit]
    included = set(ends)
    columns = []
    for end in ends:
        sample = next(
            (f for f in facts if f.period_end == end and axis.get(f.concept) == "duration"), None
        ) or next((f for f in facts if f.period_end == end), None)
        columns.append(
            {
                "period_end": end,
                "period_start": sample.period_start if sample else None,
                "fiscal_year": sample.fiscal_year if sample else None,
                "fiscal_period": sample.fiscal_period if sample else period,
                "revision_kind": sample.revision_kind if sample else None,
                "accession_number": sample.accession_number if sample else None,
            }
        )
    by_cell = {(fact.concept, fact.period_end): fact for fact in facts if fact.period_end in included}
    table_rows = []
    for row in rows:
        cells = []
        present = 0
        for column in columns:
            fact = by_cell.get((row["concept"], column["period_end"]))
            if fact is None:
                cells.append({"value": None, "unit": row["unit"], "missing": True})
                continue
            present += 1
            cells.append(
                {
                    "value": fact.value,
                    "unit": fact.unit,
                    "evidence_id": fact.evidence_id,
                    "missing": False,
                    "flags": fact.quality_flags,
                    "revision_kind": fact.revision_kind,
                    "revision_count": fact.revision_count,
                    "derivation_kind": fact.derivation_kind,
                    "derivation_rule": fact.derivation_rule,
                    "availability_time": fact.availability_time,
                    "availability_precision": fact.availability_precision,
                    "quality": fact.quality,
                    "accession_number": fact.accession_number,
                    "form_type": fact.form_type,
                }
            )
        if present:
            table_rows.append({**row, "cells": cells})
    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"], "cik": issuer["cik"]},
        "statement": statement,
        "period": period,
        "as_of": instant,
        "mode": resolved_mode,
        "policy": SELECTION_POLICY,
        "completeness": result.completeness,
        "excluded_not_yet_available": result.excluded_not_yet_available,
        "excluded_unknown_availability": result.excluded_unknown_availability,
        "contradictions": result.contradictions,
        "notes": result.notes,
        "columns": columns,
        "rows": table_rows,
        "units_note": "magnitudes as reported; ratios computed from these values carry their own formula",
        "schema": TERMINAL_SCHEMA,
    }


# ---------------------------------------------------------------------- metrics
def _fact_for(facts: Sequence[Any], concept: str, period_end: str | None) -> Any | None:
    candidates = [f for f in facts if f.concept == concept and f.period_end == period_end]
    return candidates[0] if candidates else None


def issuer_metrics(
    db: Database,
    issuer_identifier: str,
    *,
    as_of: str | None = None,
    mode: str | None = None,
    market_basis: str | None = None,
) -> dict[str, Any]:
    issuer = resolve_company(db, issuer_identifier)
    instant = _as_of(as_of)
    resolved_mode = _coerce_mode(mode)
    kernel = EvidenceKernel(db)
    result = kernel.as_of(entity_id=issuer["issuer_id"], as_of=instant, mode=resolved_mode)
    facts = result.facts
    # A fiscal year is a 330-400 day duration. A companyfacts payload can tag a
    # transition period or a quarterly window as "FY"; those are not annual periods
    # and must not become the reference period for a trailing metric.
    duration_facts = [
        f for f in facts
        if f.period_type == "duration"
        and (f.fiscal_period or "") == "FY"
        and 330 <= (_duration_days(f.to_dict()) or 0) <= 400
    ]
    reference_end = max((f.period_end for f in duration_facts if f.period_end), default=None)
    previous_end = None
    if reference_end:
        earlier = sorted(
            {
                f.period_end
                for f in duration_facts
                if f.period_end and f.period_end < reference_end and 330 <= (_duration_days(f.to_dict()) or 0) <= 400
            },
            reverse=True,
        )
        previous_end = earlier[0] if earlier else None

    master = SecurityMaster(db)
    security = (master.securities_for_issuer(issuer["issuer_id"]) or [None])[0]
    mic = _default_mic(master, security["security_id"]) if security else None
    # Two different questions, kept distinguishable:
    #
    # * no ``as_of`` — a *current* comparison: the most recent price against the most
    #   recently available accounting evidence, with both dates reported;
    # * with ``as_of`` — a *point-in-time* comparison: the price must satisfy the same
    #   cutoff as the accounting evidence, so a July price can never enter a June run.
    # ``market_basis`` lets a caller that always has an instant (the materialized-metrics
    # cache) still ask the *current* question. Without it, every cached read would be
    # labelled point-in-time with a cutoff of today, which is true but misleading.
    requested_basis = (market_basis or "").strip().lower() or None
    if requested_basis not in {None, "current", "current_market", "point_in_time"}:
        raise ValidationError(
            "unknown market basis",
            market_basis=market_basis,
            supported=["current_market", "point_in_time"],
        )
    point_in_time = requested_basis == "point_in_time" or (
        requested_basis is None and as_of is not None
    )
    market_basis = "point_in_time" if point_in_time else "current_market"
    market_cutoff = iso_date(instant) if point_in_time else None
    price_selection = (
        market_evidence.select_price(
            db,
            security["security_id"],
            market_cutoff or market_evidence.NO_CUTOFF,
            mic=mic,
        )
        if security and mic
        else None
    )
    # The same immutable observation the Markets page shows, not a second query.
    latest_bar = price_selection.observation if price_selection else None

    metrics: dict[str, dict[str, Any]] = {}

    def source_metric(concept: str, label: str) -> dict[str, Any] | None:
        fact = _fact_for(facts, concept, reference_end)
        if fact is None or fact.value is None:
            return None
        value = _dec(fact.value)
        if value is None:
            return None
        return {
            "key": concept,
            "label": label,
            "value": float(value),
            "text": str(fact.value),
            "unit": fact.unit,
            "kind": "source_observation",
            "formula": None,
            "period_end": fact.period_end,
            "evidence_ids": [fact.evidence_id],
            "source": "SEC XBRL company facts",
        }

    sources = [
        ("revenue", "Revenue"),
        ("gross_profit", "Gross profit"),
        ("operating_income", "Operating income"),
        ("net_income", "Net income"),
        ("net_income_common", "Net income available to common"),
        ("operating_cash_flow", "Operating cash flow"),
        ("capex", "Capital expenditure"),
        ("assets", "Total assets"),
        ("liabilities", "Total liabilities"),
        ("equity", "Shareholders' equity"),
        ("preferred_stock", "Preferred stock"),
        ("cash_and_equivalents", "Cash and equivalents"),
        ("long_term_debt", "Long-term debt"),
        ("short_term_debt", "Short-term debt"),
        ("shares_outstanding", "Shares outstanding"),
        ("weighted_average_shares_diluted", "Weighted average diluted shares"),
        ("eps_diluted", "Diluted EPS"),
        ("research_and_development", "Research and development"),
    ]
    for concept, label in sources:
        metric = source_metric(concept, label)
        if metric:
            metrics[concept] = metric

    # Average-equity ROE needs the prior fiscal-year instant, not the prior duration
    # fact. Keep it as a separate, evidenced concept so an ending-equity proxy is never
    # silently presented as a company-reported or average-equity return.
    if previous_end:
        for concept, label, key in (
            ("equity", "Shareholders' equity at prior fiscal year-end", "beginning_equity"),
            ("preferred_stock", "Preferred stock at prior fiscal year-end", "beginning_preferred_stock"),
        ):
            fact = _fact_for(facts, concept, previous_end)
            if fact is None or fact.value is None:
                continue
            value = _dec(fact.value)
            if value is None:
                continue
            metrics[key] = {
                "key": key,
                "label": label,
                "value": float(value),
                "text": str(fact.value),
                "unit": fact.unit,
                "kind": "source_observation",
                "formula": None,
                "period_end": fact.period_end,
                "evidence_ids": [fact.evidence_id],
                "source": "SEC XBRL company facts",
                "note": "Prior fiscal year-end instant used only for average-equity ROE.",
            }

    def derived(
        key: str,
        label: str,
        numerator: str | None,
        denominator: str | None,
        *,
        unit: str = "fraction",
        inputs: Sequence[str] = (),
        note: str | None = None,
    ) -> None:
        if numerator is None:
            return
        top = metrics.get(numerator, {}).get("value")
        bottom = metrics.get(denominator, {}).get("value") if denominator else 1.0
        if top is None or bottom in (None, 0):
            return
        value = Decimal(str(top)) / Decimal(str(bottom))
        evidence = [eid for name in ([numerator] + ([denominator] if denominator else [])) if name for eid in metrics.get(name, {}).get("evidence_ids", [])]
        metrics[key] = {
            "key": key,
            "label": label,
            "value": float(value),
            "text": _text(value, unit),
            "unit": unit,
            "kind": "derived_ratio",
            "formula": DERIVED_FORMULAS[key],
            "period_end": reference_end,
            "evidence_ids": evidence,
            "inputs": list(inputs),
            "note": note,
        }

    derived("gross_margin", "Gross margin", "gross_profit", "revenue")
    derived("operating_margin", "Operating margin", "operating_income", "revenue")
    derived("net_margin", "Net margin", "net_income", "revenue")
    if "liabilities" in metrics and "assets" in metrics:
        derived("liabilities_to_assets", "Liabilities / assets", "liabilities", "assets")
    if "net_income" in metrics and "equity" in metrics and metrics["equity"]["value"]:
        derived("roe", "Return on equity", "net_income", "equity")

    # Total debt and free cash flow are additive combinations, not ratios.
    if "long_term_debt" in metrics or "short_term_debt" in metrics:
        total_debt = Decimal(str(metrics.get("long_term_debt", {}).get("value") or 0)) + Decimal(
            str(metrics.get("short_term_debt", {}).get("value") or 0)
        )
        metrics["total_debt"] = {
            "key": "total_debt",
            "label": "Total debt",
            "value": float(total_debt),
            "text": f"{total_debt:.2f}",
            "unit": "USD",
            "kind": "derived_sum",
            "formula": DERIVED_FORMULAS["total_debt"],
            "period_end": reference_end,
            "evidence_ids": [
                eid
                for name in ("long_term_debt", "short_term_debt")
                for eid in metrics.get(name, {}).get("evidence_ids", [])
            ],
            "note": "components reported; a missing component is treated as zero only when the other is present",
        }
    if "operating_cash_flow" in metrics and "capex" in metrics:
        fcf = Decimal(str(metrics["operating_cash_flow"]["value"])) - abs(Decimal(str(metrics["capex"]["value"])))
        metrics["free_cash_flow"] = {
            "key": "free_cash_flow",
            "label": "Free cash flow",
            "value": float(fcf),
            "text": f"{fcf:.2f}",
            "unit": "USD",
            "kind": "derived_difference",
            "formula": DERIVED_FORMULAS["free_cash_flow"],
            "period_end": reference_end,
            "evidence_ids": metrics["operating_cash_flow"]["evidence_ids"] + metrics["capex"]["evidence_ids"],
            "note": "capex is normalised to a magnitude before subtraction",
        }

    if previous_end and reference_end:
        current = _fact_for(facts, "revenue", reference_end)
        previous = _fact_for(facts, "revenue", previous_end)
        if current and previous and current.value and previous.value and _dec(previous.value):
            growth = Decimal(str(current.value)) / Decimal(str(previous.value)) - 1
            metrics["revenue_growth"] = {
                "key": "revenue_growth",
                "label": "Revenue growth (YoY)",
                "value": float(growth),
                "text": _text(growth, "fraction"),
                "unit": "fraction",
                "kind": "derived_growth",
                "formula": DERIVED_FORMULAS["revenue_growth"],
                "period_end": reference_end,
                "comparison_period_end": previous_end,
                "evidence_ids": [current.evidence_id, previous.evidence_id],
            }

    if latest_bar and "shares_outstanding" in metrics:
        shares = Decimal(str(metrics["shares_outstanding"]["value"]))
        cap = Decimal(str(latest_bar.close)) * shares
        metrics["market_cap"] = {
            "key": "market_cap",
            "label": "Market capitalisation",
            "value": float(cap),
            "text": f"{cap:.2f}",
            "unit": "USD",
            "kind": "derived_market",
            "formula": DERIVED_FORMULAS["market_cap"],
            "period_end": reference_end,
            "price_as_of": latest_bar.session_date,
            "price_observation_id": latest_bar.observation_id,
            "evidence_ids": metrics["shares_outstanding"]["evidence_ids"],
            "note": (
                f"current price ({latest_bar.session_date}) applied to the share count reported for "
                f"{reference_end}; mixing dates is explicit, and the price source is "
                f"{_source_status(db, latest_bar.source_id)}"
            ),
        }
        for key, label, concept in (("pe", "P/E", "net_income"), ("ps", "P/S", "revenue")):
            base = metrics.get(concept, {}).get("value")
            if base and base > 0:
                ratio = cap / Decimal(str(base))
                metrics[key] = {
                    "key": key,
                    "label": label,
                    "value": float(ratio),
                    "text": f"{ratio:.3f}",
                    "unit": "ratio",
                    "kind": "derived_market",
                    "formula": DERIVED_FORMULAS[key],
                    "period_end": reference_end,
                    "price_as_of": latest_bar.session_date,
                    "price_observation_id": latest_bar.observation_id,
                    "evidence_ids": metrics["shares_outstanding"]["evidence_ids"] + metrics[concept]["evidence_ids"],
                    "note": f"trailing {concept.replace('_', ' ')} for FY ending {reference_end}",
                }
        # Yield valuations are the reciprocals of the corresponding multiples. They are
        # computed independently from the same evidence so the relationship can be
        # checked (earnings_yield * pe == 1), not assumed.
        for key, label, concept in (
            ("earnings_yield", "Earnings yield", "net_income"),
            ("fcf_yield", "FCF yield", "free_cash_flow"),
            ("book_to_market", "Book / market", "equity"),
        ):
            base_value = metrics.get(concept, {}).get("value")
            if base_value is None or cap <= 0:
                continue
            yield_value = Decimal(str(base_value)) / cap
            metrics[key] = {
                "key": key,
                "label": label,
                "value": float(yield_value),
                "text": _text(yield_value, "fraction"),
                "unit": "fraction",
                "kind": "derived_market",
                "formula": DERIVED_FORMULAS[key],
                "period_end": reference_end,
                "price_as_of": latest_bar.session_date,
                "price_observation_id": latest_bar.observation_id,
                "evidence_ids": metrics["shares_outstanding"]["evidence_ids"]
                + metrics[concept]["evidence_ids"],
                "note": (
                    f"trailing {concept.replace('_', ' ')} for FY ending {reference_end} divided by"
                    f" market cap at {latest_bar.session_date}; price source is "
                    f"{_source_status(db, latest_bar.source_id)}"
                ),
            }
        if "total_debt" in metrics and "cash_and_equivalents" in metrics:
            ev = cap + Decimal(str(metrics["total_debt"]["value"])) - Decimal(
                str(metrics["cash_and_equivalents"]["value"])
            )
            metrics["ev"] = {
                "key": "ev",
                "label": "Enterprise value",
                "value": float(ev),
                "text": f"{ev:.2f}",
                "unit": "USD",
                "kind": "derived_market",
                "formula": DERIVED_FORMULAS["ev"],
                "period_end": reference_end,
                "price_as_of": latest_bar.session_date,
                "price_observation_id": latest_bar.observation_id,
                "evidence_ids": metrics["shares_outstanding"]["evidence_ids"]
                + metrics["total_debt"]["evidence_ids"]
                + metrics["cash_and_equivalents"]["evidence_ids"],
            }
            if metrics.get("revenue", {}).get("value"):
                multiple = ev / Decimal(str(metrics["revenue"]["value"]))
                metrics["ev_revenue"] = {
                    "key": "ev_revenue",
                    "label": "EV / revenue",
                    "value": float(multiple),
                    "text": f"{multiple:.3f}",
                    "unit": "ratio",
                    "kind": "derived_market",
                    "formula": DERIVED_FORMULAS["ev_revenue"],
                    "period_end": reference_end,
                    "price_as_of": latest_bar.session_date,
                    "price_observation_id": latest_bar.observation_id,
                    "evidence_ids": metrics["ev"]["evidence_ids"] + metrics["revenue"]["evidence_ids"],
                }

    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
        "as_of": instant,
        "mode": resolved_mode,
        "policy": SELECTION_POLICY,
        "period_end": reference_end,
        "comparison_period_end": previous_end,
        "price_as_of": latest_bar.session_date if latest_bar else None,
        "price": float(latest_bar.close) if latest_bar else None,
        "price_source": _source_status(db, latest_bar.source_id) if latest_bar else None,
        "price_observation_id": latest_bar.observation_id if latest_bar else None,
        "price_source_selection": (price_selection.to_legacy() if price_selection else None),
        "market_basis": market_basis,
        "market_cutoff": market_cutoff,
        "completeness": result.completeness,
        "metrics": metrics,
        "missing": [
            key
            for key in ("revenue", "net_income", "gross_profit", "operating_income", "assets", "liabilities", "equity")
            if key not in metrics
        ],
        "notes": [
            "ratios are computed at read time and are not stored as evidence",
            "a metric whose inputs are missing is omitted rather than estimated",
            *(
                [
                    f"point-in-time run: the price must be dated on or before {market_cutoff}. "
                    "Atlas cannot prove the vendor revision available on that date matched the one "
                    "stored now; revision history is preserved, vendor vintage is not."
                ]
                if market_basis == "point_in_time"
                else []
            ),
        ],
        "schema": TERMINAL_SCHEMA,
    }


# ---------------------------------------------------------------------- research
_RESEARCH_CONCEPTS = (
    ("revenue", "Revenue"),
    ("gross_profit", "Gross profit"),
    ("operating_income", "Operating income"),
    ("net_income", "Net income"),
    ("operating_cash_flow", "Operating cash flow"),
    ("capex", "Capital expenditure"),
    ("eps_diluted", "Diluted EPS"),
)
_RESEARCH_LABELS = dict(_RESEARCH_CONCEPTS)
_RESEARCH_PEER_METRICS = (
    "revenue_growth",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "pe",
    "ev_revenue",
    "earnings_yield",
)


def financial_history(
    db: Database,
    issuer_identifier: str,
    *,
    concepts: Sequence[str] | None = None,
    limit: int = 8,
    as_of: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Annual history for a small, explicit set of concepts.

    Points carry their evidence id, so a chart cell can open X-Ray. Periods are aligned
    across concepts, and a missing period is absent rather than interpolated.
    """
    issuer = resolve_company(db, issuer_identifier)
    instant = _as_of(as_of)
    resolved_mode = _coerce_mode(mode)
    result = EvidenceKernel(db).as_of(
        entity_id=issuer["issuer_id"], as_of=instant, mode=resolved_mode
    )
    wanted = [c for c in (concepts or [concept for concept, _ in _RESEARCH_CONCEPTS]) if isinstance(c, str)]
    unknown = [concept for concept in wanted if concept not in _RESEARCH_LABELS]
    if unknown:
        raise ValidationError(
            "unknown history concept", concepts=unknown, supported=list(_RESEARCH_LABELS)
        )
    duration = [
        fact
        for fact in result.facts
        if fact.period_type == "duration"
        and (fact.fiscal_period or "") == "FY"
        and 330 <= (_duration_days(fact.to_dict()) or 0) <= 400
    ]
    periods = sorted(
        {fact.period_end for fact in duration if fact.concept in wanted and fact.period_end},
        reverse=True,
    )[: max(1, min(int(limit), 20))]
    selected = set(periods)
    rows: list[dict[str, Any]] = []
    for concept in wanted:
        latest_by_period: dict[str, Any] = {}
        for fact in duration:
            if fact.concept != concept or fact.period_end not in selected:
                continue
            current = latest_by_period.get(fact.period_end)
            if current is None or str(fact.availability_time or "") >= str(current.availability_time or ""):
                latest_by_period[fact.period_end] = fact
        points = []
        for period in sorted(selected):
            fact = latest_by_period.get(period)
            if fact is None:
                continue
            points.append(
                {
                    "period_end": period,
                    "period_start": fact.period_start,
                    "fiscal_year": fact.fiscal_year,
                    "value": float(fact.value) if fact.value is not None else None,
                    "text": str(fact.value) if fact.value is not None else None,
                    "unit": fact.unit,
                    "evidence_id": fact.evidence_id,
                    "revision_kind": fact.revision_kind,
                }
            )
        rows.append(
            {
                "concept": concept,
                "label": _RESEARCH_LABELS[concept],
                "unit": next((point["unit"] for point in points), "USD"),
                "points": points,
            }
        )
    return {
        "issuer": {
            "issuer_id": issuer["issuer_id"],
            "legal_name": issuer["legal_name"],
            "cik": issuer.get("cik"),
        },
        "as_of": instant,
        "mode": resolved_mode,
        "periods": sorted(selected),
        "concepts": rows,
        "completeness": result.completeness,
        "notes": [
            "Annual durations only; no quarterly interpolation.",
            "A period with no selected fact is omitted, not shown as zero.",
            "Every point is a link to the exact evidence record used.",
        ],
        "schema": TERMINAL_SCHEMA,
    }


def peers(
    db: Database, issuer_identifier: str, *, as_of: str | None = None, mode: str | None = None
) -> dict[str, Any]:
    """Compare the issuer with every issuer in this database, never a wider universe."""
    issuer = resolve_company(db, issuer_identifier)
    instant = _as_of(as_of)
    resolved_mode = _coerce_mode(mode)
    from statistics import median

    companies = list_companies(db, limit=500)
    rows: list[dict[str, Any]] = []
    for company in companies:
        detail = issuer_metrics(db, company["issuer_id"], as_of=instant, mode=resolved_mode)
        primary = company["securities"][0] if company["securities"] else None
        rows.append(
            {
                "issuer_id": company["issuer_id"],
                "legal_name": company["legal_name"],
                "ticker": (
                    primary["tickers"][0]["ticker"]
                    if primary and primary.get("tickers")
                    else None
                ),
                "is_target": company["issuer_id"] == issuer["issuer_id"],
                "period_end": detail.get("period_end"),
                "data_status": primary.get("data_status") if primary else None,
                "metrics": {
                    key: {
                        "value": detail["metrics"][key].get("value"),
                        "text": detail["metrics"][key].get("text"),
                        "unit": detail["metrics"][key].get("unit"),
                    }
                    for key in _RESEARCH_PEER_METRICS
                    if key in detail["metrics"] and detail["metrics"][key].get("value") is not None
                },
            }
        )
    labels = {
        "revenue_growth": "Revenue growth",
        "gross_margin": "Gross margin",
        "operating_margin": "Operating margin",
        "net_margin": "Net margin",
        "roe": "ROE",
        "pe": "P/E",
        "ev_revenue": "EV / revenue",
        "earnings_yield": "Earnings yield",
    }
    medians = {
        key: float(median(values))
        for key in _RESEARCH_PEER_METRICS
        if (values := [row["metrics"][key]["value"] for row in rows if key in row["metrics"]])
    }
    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
        "as_of": instant,
        "mode": resolved_mode,
        "rows": rows,
        "labels": labels,
        "medians": medians,
        "universe": {
            "issuers": len(rows),
            "note": "This comparison covers only issuers stored in this Atlas database; it is not an industry index.",
        },
        "notes": [
            "Missing metrics are omitted per company, never treated as zero.",
            "Medians are computed over companies that actually report the input.",
            "Price-dependent metrics use each company's latest stored close, stated per metric.",
        ],
        "schema": TERMINAL_SCHEMA,
    }


def revisions(db: Database, issuer_identifier: str, *, limit: int = 50) -> dict[str, Any]:
    """Evidence revisions plus amended filings for one issuer."""
    issuer = resolve_company(db, issuer_identifier)
    capped = max(1, min(int(limit), 200))
    rows = db.query(
        "SELECT evidence_id, concept, period_end, revision_kind, supersedes, availability_time, "
        "value_numeric, value_text, unit, accession_number, form_type FROM evidence "
        "WHERE entity_id = ? AND revision_kind != 'original' "
        "ORDER BY availability_time DESC, evidence_id LIMIT ?",
        (issuer["issuer_id"], capped),
    )
    amendments = db.query(
        "SELECT accession_number, form_type, filed_date, period_of_report, is_amendment, "
        "amends_accession FROM filing WHERE issuer_id = ? AND is_amendment = 1 "
        "ORDER BY filed_date DESC LIMIT ?",
        (issuer["issuer_id"], capped),
    )
    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
        "revisions": [
            {
                **dict(row),
                "value": row["value_numeric"] if row["value_numeric"] is not None else row["value_text"],
            }
            for row in rows
        ],
        "amended_filings": [dict(row) for row in amendments],
        "counts": {"evidence_revisions": len(rows), "amended_filings": len(amendments)},
        "notes": [
            "A revision is retained as a new evidence record; the original is never overwritten.",
            "Amended filings are SEC form amendments, which may or may not change a financial value.",
        ],
        "schema": TERMINAL_SCHEMA,
    }


# ------------------------------------------------------------------------ market
def _parse_range(
    range_key: str, start: str | None, end: str | None, *, default_end: str
) -> tuple[str, str]:
    """Resolve a request into a date window.

    ``default_end`` is the most recent stored session, not today: a one-year chart of a
    series that ends in 2024 must show its last year of data, and the response states
    which window was actually used.
    """
    if start and end:
        start_date, end_date = parse_date(start), parse_date(end)
        if start_date > end_date:
            raise ValidationError("start must not be after end", start=start, end=end)
        return iso_date(start_date), iso_date(end_date)
    if range_key not in RANGE_DAYS:
        raise ValidationError("unknown range", range=range_key, supported=sorted(RANGE_DAYS))
    end_date = parse_date(end) if end else parse_date(default_end)
    days = RANGE_DAYS[range_key]
    if start:
        return iso_date(parse_date(start)), iso_date(end_date)
    return iso_date(end_date - timedelta(days=days)), iso_date(end_date)


def market_series(
    db: Database,
    security_id: str,
    *,
    range_key: str = "1Y",
    start: str | None = None,
    end: str | None = None,
    view: str = "split",
    indicators: Sequence[dict[str, Any]] = (),
    as_of: str | None = None,
) -> dict[str, Any]:
    master = SecurityMaster(db)
    security = master.security(security_id)
    if security is None:
        raise UnknownEntity("unknown security", security_id=security_id)
    mic = _default_mic(master, security_id)
    if mic is None:
        raise ValidationError("security has no listing; market data cannot be resolved", security_id=security_id)
    if view not in {"raw", "split", "total_return"}:
        raise ValidationError("unknown price view", view=view, supported=["raw", "split", "total_return"])
    coverage = BarStore(db).coverage(security_id, mic)
    last_session = iso_date(coverage["last_bar"]) if coverage.get("last_bar") else iso_date(utcnow())
    knowledge = iso(as_of) if as_of else None
    effective_end = last_session
    if knowledge:
        effective_end = min(last_session, iso_date(as_of))
    if end:
        effective_end = min(effective_end, iso_date(end))
    start_date, end_date = _parse_range(range_key, start, end, default_end=effective_end)
    end_date = min(end_date, effective_end)

    # One canonical series: one provider, one selected observation per session, at or
    # before the knowledge cutoff. The chart, its indicators and its last bar all come
    # from the same selection, so a displayed point cannot come from a different provider
    # than the price the page says it is showing.
    series_selection = market_evidence.select_series(
        db, security_id, mic=mic, start=start_date, end=end_date
    )
    bars = [point.to_bar() for point in series_selection.points]
    actions = ActionStore(db).list(security_id, knowledge_as_of=knowledge)
    issuer = master.issuer(security["issuer_id"]) or {}
    base = {
        "security": {
            "security_id": security_id,
            "issuer_id": security["issuer_id"],
            "legal_name": issuer.get("legal_name"),
            "class_designation": security.get("class_designation"),
            "ticker": (_ticker(master, security_id) or {}).get("ticker"),
        },
        "mic": mic,
        "view": view,
        "range": {"start": start_date, "end": end_date},
        "requested_range": range_key,
        "as_of": knowledge,
        "coverage": {
            "first": coverage.get("first_bar"),
            "last": coverage.get("last_bar"),
            "sessions": coverage.get("sessions"),
            "rows": coverage.get("rows"),
        },
        "range_note": (
            f"window ends at the last stored session ({last_session}), not today"
            if not end and last_session < iso_date(utcnow())
            else None
        ),
        "actions": [action.to_dict() for action in actions],
        "sources": _sources(db),
        "series": series_selection.summary(),
        "schema": TERMINAL_SCHEMA,
        "truncated": False,
        "warnings": list(series_selection.limitations),
    }
    if not bars:
        base.update(
            {
                "bars": [],
                "index": [],
                "indicators": [],
                "adjustment_status": None,
                "data_status": "no_data",
                "price_basis_note": "No market observations are stored for this range.",
                "truncated": False,
            }
        )
        base["warnings"].append("no bars in the requested window; nothing is interpolated")
        return base

    if view == "raw":
        display = [
            {
                "date": bar.session_date,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume) if bar.volume is not None else None,
            }
            for bar in bars
        ]
        payload = {
            "adjustment_status": "raw",
            "price_basis_note": "Raw provider observations, not adjusted for splits or dividends.",
            "actions_applied": [],
            "actions_withheld": [],
        }
    elif view == "split":
        series = split_adjust(bars, actions, reference_date=end_date, knowledge_as_of=knowledge)
        display = [
            {
                "date": bar.session_date,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume) if bar.volume is not None else None,
                "split_factor": float(bar.split_factor),
            }
            for bar in series.bars
        ]
        payload = {
            "adjustment_status": "split_adjusted",
            "price_basis_note": (
                f"Split-adjusted prices (reference {series.reference_date}). Dividends are not "
                "reinvested; this is a price series, not total return."
            ),
            "actions_applied": series.actions_applied,
            "actions_withheld": series.actions_withheld,
        }
        base["warnings"].extend(series.warnings)
    else:
        series = total_return(bars, actions, reference_date=end_date, knowledge_as_of=knowledge)
        display = []
        index_points = [{"time": d, "value": float(v)} for d, v in series.total_return_index]
        payload = {
            "adjustment_status": "total_return_index",
            "price_basis_note": (
                "Total-return INDEX with base 1.0, not a price. Dividends are reinvested; "
                "do not compare its level with a quoted price."
            ),
            "actions_applied": series.actions_applied,
            "actions_withheld": series.actions_withheld,
            "index": index_points,
        }
        base["warnings"].extend(series.warnings)

    if view == "total_return":
        # Indicators are computed on the displayed index level. Use the index value for
        # every OHLC field (the series has no intrabar range) and borrow the underlying
        # session volume so volume-weighted indicators stay meaningful.
        volume_by_date = {
            bar.session_date: float(bar.volume) if bar.volume is not None else 0.0 for bar in bars
        }
        closes_source = [
            {
                "date": point["time"],
                "open": point["value"],
                "high": point["value"],
                "low": point["value"],
                "close": point["value"],
                "volume": volume_by_date.get(point["time"], 0),
            }
            for point in payload["index"]
        ]
    else:
        closes_source = display
    if len(closes_source) > 2000:
        step = max(1, len(closes_source) // 2000)
        display = display[::step] if view != "total_return" else display
        if view == "total_return":
            payload["index"] = payload["index"][::step]
        closes_source = closes_source[::step]
        base["truncated"] = True
        base["warnings"].append("series downsampled to at most 2000 observations for the browser")

    indicator_result = compute_many(indicators, closes_source) if indicators else {"indicators": [], "signature": None}
    base.update(
        {
            "bars": display if view != "total_return" else [],
            "index": payload.get("index", []),
            "adjustment_status": payload["adjustment_status"],
            "price_basis_note": payload["price_basis_note"],
            "actions_applied": payload["actions_applied"],
            "actions_withheld": payload["actions_withheld"],
            "indicators": indicator_result["indicators"],
            "indicator_signature": indicator_result["signature"],
            "data_status": _source_status(db, bars[-1].source_id),
            "real_data": bool(
                db.scalar("SELECT kind FROM source WHERE source_id = ?", (bars[-1].source_id,), "") != "synthetic"
            ),
            "last_bar": {
                "date": bars[-1].session_date,
                "close": float(bars[-1].close),
                "observed_at": bars[-1].observed_at,
                "ingested_at": bars[-1].ingested_at,
                "source_id": bars[-1].source_id,
            },
        }
    )
    source_row = db.query_one(
        "SELECT source_id, name, kind, homepage, licence, redistribution, notes FROM source WHERE source_id = ?",
        (bars[-1].source_id,),
    )
    base["data_source"] = {key: source_row[key] for key in source_row.keys()} if source_row else None
    base["limitations"] = [
        "Daily vendor observations, timestamped at the session close; not exchange ticks.",
        "No vendor revision history is archived: a re-fetch creates a new Atlas bar revision.",
        "Corporate actions come from the vendor feed and are not independently confirmed by an exchange notice.",
    ] if bars[-1].source_id == "alphavantage" else []
    base["warnings"].extend(
        warning for item in indicator_result["indicators"] for warning in item["warnings"]
    )
    return base


def market_overview(
    db: Database, *, projection: str = "bulk", as_of: str | None = None
) -> dict[str, Any]:
    """Every row is one canonical series, not the union of whatever providers exist.

    The response contract is fixed; only its execution plan is selectable.
    ``projection="bulk"`` (the default, and what the HTTP route uses) builds the same
    items with a bounded number of set-based statements, and
    ``projection="scalar"`` runs the per-security reference loop below. The two must
    return identical documents; ``tests/test_phase9_2_8_bulk_overview.py`` compares them
    differentially over adversarial fixtures and generated ones.
    """
    from . import market_projection

    return market_projection.overview(db, plan=projection, as_of=as_of)


def market_overview_scalar(db: Database, *, as_of: str | None = None) -> dict[str, Any]:
    """Reference implementation: one canonical series per security, selected one at a time.

    Before Phase 9.2.7 this function read the raw bar table and took ``series[-1]``,
    ``series[-2]`` and ``series[-252]``. Those positions were raw rows: two providers on
    one session produced two rows for one date, so the "previous" row could be the same
    provider on the same day, and a correction could silently rewrite a historical point.
    The row now comes from the canonical series (one provider, one observation per
    session) and the changes are computed on a stated basis over actual selected dates.

    Kept as the executable definition of the contract: it is deliberately the slow, obvious
    path, so a performance change can be proven equivalent instead of asserted.
    """
    master = SecurityMaster(db)
    actions = ActionStore(db)
    rows = db.query("SELECT security_id FROM security ORDER BY security_id")
    today = str(as_of or iso_date(utcnow()))[:10]
    items = []
    for row in rows:
        security_id = row["security_id"]
        security = master.security(security_id)
        if security is None:
            continue
        mic = _default_mic(master, security_id)
        if mic is None:
            continue
        anchor = market_evidence.latest_observation(db, security_id, mic=mic, as_of=today)
        if anchor.observation is None:
            continue
        # A bounded window: the one-year comparison plus a buffer for sessions, not the
        # security's entire history.
        window_start = (
            parse_date(anchor.observation.session_date) - timedelta(days=400)
        ).isoformat()
        series = market_evidence.select_series(
            db, security_id, mic=mic, start=window_start, end=today, anchor=anchor
        )
        if not series.points:
            continue
        change = market_evidence.series_changes(
            series, actions.list(security_id, computable_only=True)
        )
        latest = series.points[-1]
        issuer = master.issuer(security["issuer_id"]) or {}
        items.append(
            {
                "security_id": security_id,
                "issuer_id": security["issuer_id"],
                "legal_name": issuer.get("legal_name"),
                "ticker": (_ticker(master, security_id, as_of=today) or {}).get("ticker"),
                "mic": mic,
                "last_close": float(latest.close),
                "last_bar_date": latest.session_date,
                "change_1d": change.one_day,
                "change_1y": change.one_year,
                "change_basis": change.basis,
                "change_1d_dates": (
                    [change.one_day_from["session_date"], change.one_day_to["session_date"]]
                    if change.one_day_from and change.one_day_to else None
                ),
                "change_1y_dates": (
                    [change.one_year_from["session_date"], change.one_year_to["session_date"]]
                    if change.one_year_from and change.one_year_to else None
                ),
                "change_1y_target": change.one_year_target,
                "change_1y_span_days": change.one_year_span_days,
                "volume": float(latest.volume) if latest.volume is not None else None,
                "sparkline": [float(point.close) for point in series.points[-30:]],
                "sessions": series.sessions,
                "data_status": _source_status(db, latest.source_id),
                "currency": security.get("currency"),
                "price_observation_id": latest.observation_id,
                "series_policy": series.policy,
                "series_limitations": list(series.limitations),
                "issuer_metrics": None,
            }
        )
    items.sort(key=lambda item: item["ticker"] or "")
    return {
        "items": items,
        "count": len(items),
        "as_of": iso(utcnow()),
        "data_status": "synthetic" if any(item["data_status"] == "synthetic" for item in items) else "reported",
        "sources": _sources(db),
        "schema": TERMINAL_SCHEMA,
        "notes": [
            "Prices are end-of-day observations. Freshness is the last stored session, not a live quote."
        ],
    }


# ----------------------------------------------------------------- filings/events
def filings(
    db: Database, issuer_identifier: str, *, limit: int = 25, offset: int = 0, forms: Sequence[str] = ()
) -> dict[str, Any]:
    issuer = resolve_company(db, issuer_identifier)
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    sql = "SELECT * FROM filing WHERE issuer_id = ?"
    params: list[Any] = [issuer["issuer_id"]]
    if forms:
        sql += f" AND form_type IN ({','.join('?' for _ in forms)})"
        params.extend(forms)
    total = int(db.scalar(f"SELECT COUNT(*) FROM ({sql})", params, 0) or 0)
    rows = db.query(
        sql + " ORDER BY filed_date DESC, accession_number DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    cik = str(issuer.get("cik") or "").lstrip("0") or "0"
    items = []
    for row in rows:
        accession = row["accession_number"]
        url = None
        if row["primary_document"]:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{row['primary_document']}"
        items.append(
            {
                "filing_id": row["filing_id"],
                "accession_number": accession,
                "form_type": row["form_type"],
                "form_label": FORM_WORDS.get(row["form_type"], row["form_type"]),
                "filed_date": row["filed_date"],
                "acceptance_datetime": row["acceptance_datetime"],
                "period_of_report": row["period_of_report"],
                "is_amendment": bool(row["is_amendment"]),
                "amends_accession": row["amends_accession"],
                "primary_document": row["primary_document"],
                "source_url": url,
                "source_id": row["source_id"],
            }
        )
    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "notes": [
            "SEC filing events only; Atlas has no licensed news feed and does not synthesise headlines."
        ],
        "schema": TERMINAL_SCHEMA,
    }


def events(db: Database, issuer_identifier: str, *, limit: int = 40) -> dict[str, Any]:
    issuer = resolve_company(db, issuer_identifier)
    master = SecurityMaster(db)
    items: list[dict[str, Any]] = []
    for row in db.query(
        "SELECT * FROM filing WHERE issuer_id = ? ORDER BY filed_date DESC LIMIT ?",
        (issuer["issuer_id"], max(1, min(limit, 100))),
    ):
        items.append(
            {
                "kind": "filing",
                "date": row["filed_date"],
                "timestamp": row["acceptance_datetime"],
                "title": f"{row['form_type']} filed",
                "detail": FORM_WORDS.get(row["form_type"], "SEC filing")
                + (f" for period {row['period_of_report']}" if row["period_of_report"] else ""),
                "reference": row["accession_number"],
                "amendment": bool(row["is_amendment"]),
                "source_id": row["source_id"],
            }
        )
    action_store = ActionStore(db)
    for security in master.securities_for_issuer(issuer["issuer_id"]):
        for action in action_store.list(security["security_id"]):
            items.append(
                {
                    "kind": "corporate_action",
                    "date": action.ex_date or action.effective_date or "",
                    "timestamp": action.availability_time,
                    "title": f"{action.action_type.replace('_', ' ').title()}",
                    "detail": (action.notes or action.action_type.replace("_", " ")).strip(),
                    "reference": action.action_id,
                    "security_id": security["security_id"],
                    "source_id": action.source_id,
                }
            )
    items.sort(key=lambda item: (item["date"] or "", item["timestamp"] or ""), reverse=True)
    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
        "items": items[: max(1, min(limit, 200))],
        "counts": {
            "filings": sum(1 for i in items if i["kind"] == "filing"),
            "corporate_actions": sum(1 for i in items if i["kind"] == "corporate_action"),
        },
        "schema": TERMINAL_SCHEMA,
    }


# ------------------------------------------------------------------------ x-ray
def xray(db: Database, evidence_id: str) -> dict[str, Any]:
    kernel = EvidenceKernel(db)
    report = kernel.provenance(evidence_id)
    payload = report.to_dict()
    payload["terminal"] = {
        "policy": SELECTION_POLICY,
        "schema": TERMINAL_SCHEMA,
        "holds": "one immutable observation, its source document, filing context and revision chain",
    }
    return payload


# ------------------------------------------------------------------------ health
def health(db: Database, issuer_identifier: str | None = None) -> dict[str, Any]:
    issuer = resolve_company(db, issuer_identifier) if issuer_identifier else None
    where = "WHERE entity_id = ?" if issuer else ""
    params: tuple[Any, ...] = (issuer["issuer_id"],) if issuer else ()
    precision = {
        row["availability_precision"]: int(row["n"])
        for row in db.query(
            f"SELECT availability_precision, COUNT(*) AS n FROM evidence {where} GROUP BY availability_precision",
            params,
        )
    }
    issues = {
        row["severity"]: int(row["n"])
        for row in db.query("SELECT severity, COUNT(*) AS n FROM data_quality_issue GROUP BY severity")
    }
    coverage = None
    if issuer:
        cik = issuer.get("cik")
        if cik:
            row = db.query_one(
                "SELECT COUNT(*) AS archives, SUM(filing_rows) AS rows, MAX(fetched_at) AS fetched_at "
                "FROM submissions_file WHERE cik = ?",
                (cik,),
            )
            coverage = {
                "archives": int(row["archives"] or 0),
                "archive_rows": int(row["rows"] or 0),
                "fetched_at": row["fetched_at"],
            }
    migrations = [
        {"version": row["version"], "name": row["name"], "applied_at": row["applied_at"]}
        for row in db.applied_migrations()
    ]
    return {
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]} if issuer else None,
        "evidence": int(db.scalar(f"SELECT COUNT(*) FROM evidence {where}", params, 0) or 0),
        "availability": {
            "exact": precision.get("exact", 0),
            "date": precision.get("date", 0),
            "unknown": precision.get("unknown", 0),
        },
        "issues": {"error": issues.get("error", 0), "warning": issues.get("warning", 0), "info": issues.get("info", 0)},
        "integrity_check": db.integrity_check(),
        "schema_version": db.schema_version(),
        "migrations": migrations,
        "history_coverage": coverage,
        "sources": _sources(db),
        "notes": [
            "availability 'date' means the fact can only be placed to a day, not an acceptance instant",
            "integrity_check is SQLite's own consistency check",
        ],
        "schema": TERMINAL_SCHEMA,
    }
