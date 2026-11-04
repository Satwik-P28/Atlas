"""Deterministic screener over the securities actually stored in this database.

The screener is deliberately honest about scope. It evaluates the issuers Atlas knows
about, reports how many it skipped for missing inputs, and never presents four sample
companies as a market-wide universe. It is deterministic: the same database, as-of
instant and filter document produce the same rows in the same order.

Values come from :func:`atlas.terminal.read_models.issuer_metrics`, so every filter
operates on a number that already carries its formula and evidence ids. A missing
metric fails a filter rather than being coerced to zero.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..core.errors import ValidationError
from ..core.temporal import AsOfMode, iso, utcnow
from ..storage.db import Database
from . import metric_store
from .read_models import DERIVED_FORMULAS, list_companies

OPS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "between": lambda a, b: b[0] <= a <= b[1],
}

SOURCE_METRICS = {
    "revenue": ("Revenue", "USD"),
    "gross_profit": ("Gross profit", "USD"),
    "operating_income": ("Operating income", "USD"),
    "net_income": ("Net income", "USD"),
    "operating_cash_flow": ("Operating cash flow", "USD"),
    "capex": ("Capital expenditure", "USD"),
    "free_cash_flow": ("Free cash flow", "USD"),
    "assets": ("Total assets", "USD"),
    "liabilities": ("Total liabilities", "USD"),
    "equity": ("Shareholders' equity", "USD"),
    "cash_and_equivalents": ("Cash and equivalents", "USD"),
    "total_debt": ("Total debt", "USD"),
    "shares_outstanding": ("Shares outstanding", "shares"),
    "eps_diluted": ("Diluted EPS", "USD/share"),
    "research_and_development": ("Research and development", "USD"),
    "gross_margin": ("Gross margin", "fraction"),
    "operating_margin": ("Operating margin", "fraction"),
    "net_margin": ("Net margin", "fraction"),
    "revenue_growth": ("Revenue growth (YoY)", "fraction"),
    "liabilities_to_assets": ("Liabilities / assets", "ratio"),
    "roe": ("Return on equity", "fraction"),
    "market_cap": ("Market capitalisation", "USD"),
    "pe": ("P/E", "ratio"),
    "ps": ("P/S", "ratio"),
    "ev": ("Enterprise value", "USD"),
    "ev_revenue": ("EV / revenue", "ratio"),
    "earnings_yield": ("Earnings yield", "fraction"),
    "fcf_yield": ("FCF yield", "fraction"),
    "book_to_market": ("Book / market", "fraction"),
}


def metric_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": label,
            "unit": unit,
            "formula": DERIVED_FORMULAS.get(key),
            "kind": "derived" if key in DERIVED_FORMULAS else "source_observation",
        }
        for key, (label, unit) in sorted(SOURCE_METRICS.items(), key=lambda item: item[1][0])
    ]


def _validate_filters(filters: Any) -> list[dict[str, Any]]:
    if filters is None:
        return []
    if not isinstance(filters, list) or len(filters) > 12:
        raise ValidationError("filters must be a list of at most 12 entries")
    cleaned = []
    for index, item in enumerate(filters):
        if not isinstance(item, dict):
            raise ValidationError("filter must be an object", index=index)
        unknown = set(item) - {"metric", "op", "value", "value2"}
        if unknown:
            raise ValidationError("unknown filter key", index=index, unknown=sorted(unknown))
        metric = item.get("metric")
        if metric not in SOURCE_METRICS:
            raise ValidationError(
                "unknown screener metric", index=index, metric=metric, supported=sorted(SOURCE_METRICS)
            )
        op = item.get("op")
        if op not in OPS:
            raise ValidationError("unknown comparison", index=index, op=op, supported=sorted(OPS))
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError("filter value must be a number", index=index)
        entry = {"metric": metric, "op": op, "value": float(value)}
        if op == "between":
            value2 = item.get("value2")
            if isinstance(value2, bool) or not isinstance(value2, (int, float)):
                raise ValidationError("between requires a numeric value2", index=index)
            entry["value2"] = float(value2)
            if entry["value2"] < entry["value"]:
                raise ValidationError("between value2 must be >= value", index=index)
        cleaned.append(entry)
    return cleaned


def run_screener(
    db: Database,
    *,
    filters: Sequence[dict[str, Any]] | None = None,
    match: str = "AND",
    sort: dict[str, Any] | None = None,
    limit: int = 50,
    as_of: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    if match not in {"AND", "OR"}:
        raise ValidationError("match must be AND or OR", match=match)
    cleaned = _validate_filters(list(filters or ()))
    limit = max(1, min(int(limit), 200))
    instant = iso(as_of) if as_of else iso(utcnow())
    resolved_mode = mode or AsOfMode.PUBLIC_AVAILABLE.value
    try:
        AsOfMode(resolved_mode)
    except ValueError:
        raise ValidationError("unknown as-of mode", mode=resolved_mode)

    companies = list_companies(db, limit=500)
    rows: list[dict[str, Any]] = []
    excluded_missing = 0
    skipped: list[dict[str, Any]] = []
    for company in companies:
        # Pass the caller's cutoff, not the freshly generated display instant. A None
        # cutoff is an implicit "now" and the materializer normalizes it to end-of-day;
        # an explicit historical cutoff is preserved exactly.
        detail = metric_store.get_issuer_metrics(
            db, company["issuer_id"], as_of=as_of, mode=resolved_mode
        )
        metrics = detail["metrics"]
        primary = company["securities"][0] if company["securities"] else None
        row = {
            "issuer_id": company["issuer_id"],
            "legal_name": company["legal_name"],
            "ticker": (primary["tickers"][0]["ticker"] if primary and primary["tickers"] else None),
            "security_id": primary["security_id"] if primary else None,
            "period_end": detail["period_end"],
            "price_as_of": detail["price_as_of"],
            "metrics": {
                key: {
                    "value": value.get("value"),
                    "text": value.get("text"),
                    "unit": value.get("unit"),
                    "formula": value.get("formula"),
                    "evidence_ids": value.get("evidence_ids", []),
                }
                for key, value in metrics.items()
            },
            "missing": detail["missing"],
            "data_status": primary.get("data_status") if primary else None,
        }
        if not cleaned:
            rows.append(row)
            continue
        results: list[bool] = []
        failed_for_missing = False
        for condition in cleaned:
            entry = metrics.get(condition["metric"])
            if entry is None or entry.get("value") is None:
                failed_for_missing = True
                results.append(False)
                continue
            actual = float(entry["value"])
            if condition["op"] == "between":
                results.append(condition["value"] <= actual <= condition["value2"])
            else:
                results.append(bool(OPS[condition["op"]](actual, condition["value"])))
        passed = all(results) if match == "AND" else any(results)
        if passed:
            rows.append(row)
        elif failed_for_missing:
            excluded_missing += 1
            skipped.append(
                {
                    "issuer_id": company["issuer_id"],
                    "legal_name": company["legal_name"],
                    "missing": [
                        c["metric"] for c in cleaned if c["metric"] not in metrics or metrics[c["metric"]].get("value") is None
                    ],
                }
            )

    if sort:
        if not isinstance(sort, dict) or set(sort) - {"metric", "direction"}:
            raise ValidationError("sort must be {metric, direction}")
        metric = sort.get("metric")
        direction = sort.get("direction", "desc")
        if metric not in SOURCE_METRICS:
            raise ValidationError("unknown sort metric", metric=metric, supported=sorted(SOURCE_METRICS))
        if direction not in {"asc", "desc"}:
            raise ValidationError("sort direction must be asc or desc", direction=direction)
        present = [row for row in rows if row["metrics"].get(metric, {}).get("value") is not None]
        absent = [row for row in rows if row["metrics"].get(metric, {}).get("value") is None]
        present.sort(
            key=lambda row: row["metrics"][metric]["value"], reverse=(direction == "desc")
        )
        present.sort(key=lambda row: row["ticker"] or "")  # stable tie-break
        rows = present + absent
    else:
        rows.sort(key=lambda row: row["ticker"] or "")

    covered_metrics = sorted(
        {key for row in rows for key, value in row["metrics"].items() if value["value"] is not None}
    )
    return {
        "matched": len(rows),
        "returned": min(len(rows), limit),
        "rows": rows[:limit],
        "universe": {
            "issuers_in_database": len(companies),
            "evaluated": len(companies),
            "excluded_for_missing_inputs": excluded_missing,
            "note": (
                f"This screener covers the {len(companies)} issuer(s) stored in this Atlas database. "
                "It is not a market-wide screen."
            ),
        },
        "filters": cleaned,
        "match": match,
        "sort": sort,
        "as_of": instant,
        "mode": resolved_mode,
        "skipped": skipped[:20],
        "covered_metrics": covered_metrics,
        "data_status": (
            "synthetic" if {row.get("data_status") for row in rows} == {"synthetic"}
            else "reported" if {row.get("data_status") for row in rows} <= {"reported"}
            else "mixed"
        ) if rows else None,
        "schema": "atlas.terminal.v1",
        "notes": [
            "A security with a missing metric fails a filter on that metric instead of being treated as zero.",
            "Sorting is deterministic: ticker breaks ties.",
        ],
    }
