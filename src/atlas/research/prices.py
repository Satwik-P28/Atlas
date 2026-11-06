"""Market-price ingestion and price-based analysis with explicit rights.

Atlas does not redistribute vendor market data. A user or an authorised feed may import
observed prices; the resulting rows retain the source, retrieval time, adjustment
semantics and redistribution terms. Analyses that require a price report the price as
unavailable until such an import exists, and never substitute a synthetic quote.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..core.temporal import iso, parse_date, utcnow
from ..entities.master import SecurityMaster
from ..storage.db import Database

PRICE_SCHEMA = "atlas.market_price.summary.v1"
IMPORT_SCHEMA = "atlas.market_price.import.v1"

ALLOWED_REDISTRIBUTION = {"public_domain", "user_responsibility", "restricted", "private"}
EXPORTABLE_REDISTRIBUTION = {"public_domain"}


class PriceImportError(ValueError):
    """A price import was rejected because its provenance or rights are incomplete."""


def _parse_ts(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise PriceImportError("price row has no date")
    if "T" in text:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return iso(moment.astimezone(timezone.utc))
    day = parse_date(text)
    return f"{day.isoformat()}T00:00:00Z"


def import_price_series(
    db: Database,
    *,
    ticker: str,
    rows: Iterable[Mapping[str, Any]],
    source_name: str,
    licence: str,
    redistribution: str,
    adjustment_semantics: str,
    retrieved_at: str | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    """Import observed closes for one security.

    Every import must declare its source, licence, redistribution terms and adjustment
    semantics. Rows missing a date or close are rejected rather than forward-filled.
    """
    if redistribution not in ALLOWED_REDISTRIBUTION:
        raise PriceImportError(
            "redistribution terms must be one of " + ", ".join(sorted(ALLOWED_REDISTRIBUTION))
        )
    if not source_name or not licence:
        raise PriceImportError("a price import requires a source name and a licence")
    if not adjustment_semantics:
        raise PriceImportError("adjustment semantics must be declared (unadjusted, split_adjusted, total_return)")

    master = SecurityMaster(db)
    issuer = None
    security_id = None
    for row in db.query(
        "SELECT l.security_id, ta.ticker FROM ticker_assignment ta "
        "JOIN listing l ON l.listing_id = ta.listing_id "
        "WHERE upper(ta.ticker) = upper(?)",
        (ticker,),
    ):
        security_id = row["security_id"]
        break
    if security_id is None:
        raise PriceImportError(f"no listed security is registered for ticker {ticker}")

    source_id = "user-market-data"
    existing = db.query_one("SELECT * FROM source WHERE source_id=?", (source_id,))
    now = iso(utcnow())
    if existing is None:
        db.execute(
            "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (source_id, source_name, "market_data", None, licence, redistribution, None, now),
        )
    else:
        db.execute(
            "UPDATE source SET name=?, licence=?, redistribution=?, notes=? WHERE source_id=?",
            (source_name, licence, redistribution, now, source_id),
        )

    retrieved = retrieved_at or now
    written = 0
    rejected = 0
    for item in rows:
        try:
            ts = _parse_ts(item.get("date") or item.get("ts_utc"))
            close = float(item["close"])
        except (KeyError, TypeError, ValueError, PriceImportError):
            rejected += 1
            continue
        adjustment = str(item.get("adjustment") or adjustment_semantics)
        # The compact schema has no unique constraint covering the bar identity, so an
        # explicit delete keeps a re-import idempotent instead of stacking duplicates.
        db.execute(
            "DELETE FROM bar WHERE security_id=? AND mic=? AND interval=? AND ts_utc=?",
            (security_id, "XNYS", "1d", ts),
        )
        db.execute(
            "INSERT INTO bar (security_id, mic, interval, ts_utc, revision_seq, open, high, low, close, "
            "volume, trades, vwap, currency, adjustment_status, source_id, observed_at, ingested_at, "
            "supersedes_bar, quality_flags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                security_id, "XNYS", "1d", ts, 0,
                float(item["open"]) if item.get("open") is not None else close,
                float(item["high"]) if item.get("high") is not None else close,
                float(item["low"]) if item.get("low") is not None else close,
                close,
                int(item["volume"]) if item.get("volume") is not None else None,
                None, None, currency, adjustment, source_id, retrieved, now, None,
                json.dumps(["user_imported"]),
            ),
        )
        written += 1
    return {
        "schema": IMPORT_SCHEMA,
        "ticker": ticker,
        "security_id": security_id,
        "written": written,
        "rejected": rejected,
        "source": {
            "source_id": source_id,
            "name": source_name,
            "licence": licence,
            "redistribution": redistribution,
            "export_allowed": redistribution in EXPORTABLE_REDISTRIBUTION,
            "retrieved_at": retrieved,
        },
        "adjustment_semantics": adjustment_semantics,
        "limitation": (
            "Imported prices are user-supplied observations, not a point-in-time vendor vintage. "
            "They are not redistributed in a research package unless their terms permit it."
        ),
    }


def price_summary(db: Database, security_id: str) -> dict[str, Any]:
    rows = list(db.query(
        "SELECT b.ts_utc, b.close, b.currency, b.adjustment_status, b.source_id, b.observed_at, "
        "s.name, s.licence, s.redistribution "
        "FROM bar b LEFT JOIN source s ON s.source_id=b.source_id "
        "WHERE b.security_id=? AND b.interval='1d' ORDER BY b.ts_utc",
        (security_id,),
    ))
    if not rows:
        return {
            "schema": PRICE_SCHEMA,
            "status": "unavailable",
            "observations": 0,
            "detail": (
                "No authorised price series is stored for this security. Atlas does not bundle or "
                "invent market prices, so price multiples, reverse DCF and price-versus-model "
                "comparisons are unavailable."
            ),
        }
    latest = rows[-1]
    return {
        "schema": PRICE_SCHEMA,
        "status": "available",
        "observations": len(rows),
        "first_date": rows[0]["ts_utc"][:10],
        "last_date": latest["ts_utc"][:10],
        "latest_close": float(latest["close"]),
        "currency": latest["currency"],
        "adjustment_semantics": latest["adjustment_status"],
        "source": {
            "source_id": latest["source_id"],
            "name": latest["name"],
            "licence": latest["licence"],
            "redistribution": latest["redistribution"],
            "export_allowed": latest["redistribution"] in EXPORTABLE_REDISTRIBUTION,
            "observed_at": latest["observed_at"],
        },
        "limitation": (
            "Observed historical closes are not a point-in-time vendor vintage; corporate-action "
            "adjustment is whatever the importer declared."
        ),
    }


def price_history(db: Database, security_id: str, *, limit: int = 400) -> dict[str, Any]:
    rows = list(db.query(
        "SELECT b.ts_utc, b.close, b.volume, b.source_id, b.adjustment_status, "
        "s.name, s.licence, s.redistribution "
        "FROM bar b LEFT JOIN source s ON s.source_id=b.source_id "
        "WHERE b.security_id=? AND b.interval='1d' ORDER BY b.ts_utc DESC LIMIT ?",
        (security_id, limit),
    ))
    if not rows:
        return {"status": "unavailable", "observations": 0, "points": []}
    points = [{"date": row["ts_utc"][:10], "close": float(row["close"]),
               "volume": row["volume"]} for row in reversed(rows)]
    closes = sorted(point["close"] for point in points)
    latest = points[-1]
    below = sum(1 for value in closes if value <= latest["close"])
    return {
        "status": "available",
        "observations": len(points),
        "first_date": points[0]["date"],
        "last_date": latest["date"],
        "latest_close": latest["close"],
        "minimum_close": closes[0],
        "maximum_close": closes[-1],
        "latest_percentile": (below / len(closes)) if closes else None,
        "source": {
            "source_id": rows[-1]["source_id"], "name": rows[-1]["name"],
            "licence": rows[-1]["licence"], "redistribution": rows[-1]["redistribution"],
        },
        "export_allowed": rows[-1]["redistribution"] in EXPORTABLE_REDISTRIBUTION,
        "points": points,
    }


def price_on_or_before(db: Database, security_id: str, date_text: str) -> dict[str, Any] | None:
    """Return the last observation at or before a declared comparison date."""
    row = db.query_one(
        "SELECT ts_utc, close, currency, adjustment_status, source_id, observed_at "
        "FROM bar WHERE security_id=? AND interval='1d' AND substr(ts_utc,1,10)<=? "
        "ORDER BY ts_utc DESC LIMIT 1",
        (security_id, date_text[:10]),
    )
    if row is None:
        return None
    return {
        "date": row["ts_utc"][:10],
        "close": float(row["close"]),
        "currency": row["currency"],
        "adjustment_semantics": row["adjustment_status"],
        "source_id": row["source_id"],
        "observed_at": row["observed_at"],
    }


def market_analysis(
    *,
    price: Mapping[str, Any] | None,
    history: Mapping[str, Any] | None,
    value_per_share: float | None,
    accounting_period_end: str | None,
    implied: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare a model value with an observed price without hiding the date gap."""
    if not price:
        return {
            "schema": "atlas.market_analysis.v1",
            "status": "unavailable",
            "reason": "No observed price exists on or before the comparison date.",
            "implied": None,
        }
    price_date = price["date"]
    accounting = (accounting_period_end or "")[:10]
    mixed = bool(accounting and accounting != price_date)
    premium = ((value_per_share / price["close"]) - 1.0) if value_per_share and price["close"] else None
    return {
        "schema": "atlas.market_analysis.v1",
        "status": "available",
        "price": price["close"],
        "price_date": price_date,
        "currency": price["currency"],
        "source_id": price["source_id"],
        "adjustment_semantics": price["adjustment_semantics"],
        "accounting_period_end": accounting or None,
        "mixed_date": mixed,
        "date_gap_days": (
            (datetime.fromisoformat(price_date) - datetime.fromisoformat(accounting)).days
            if mixed else 0
        ),
        "model_value_per_share": value_per_share,
        "model_premium_to_price": premium,
        "history": {
            "observations": (history or {}).get("observations", 0),
            "first_date": (history or {}).get("first_date"),
            "last_date": (history or {}).get("last_date"),
            "minimum_close": (history or {}).get("minimum_close"),
            "maximum_close": (history or {}).get("maximum_close"),
            "latest_percentile": (history or {}).get("latest_percentile"),
        },
        "implied": dict(implied or {}),
        "export_allowed": bool((history or {}).get("export_allowed")),
        "warning": (
            "The price date differs from the accounting period end. This is a mixed-date "
            "comparison, not a point-in-time valuation." if mixed else
            "Price and accounting dates align; the model still depends on assumptions."
        ),
        "note": (
            "A model-price difference is not an investment recommendation. The model value "
            "may be wrong, the price may embed expectations the model omits, or both."
        ),
    }


def valuation_multiples(metrics: Mapping[str, Any], price: float | None) -> dict[str, Any]:
    def metric(key: str) -> float | None:
        item = (metrics.get("metrics") or {}).get(key)
        if not isinstance(item, Mapping) or item.get("value") is None:
            return None
        try:
            return float(item["value"])
        except (TypeError, ValueError):
            return None

    if price is None or price <= 0:
        return {
            "status": "unavailable",
            "reason": "A positive observed market price is required.",
            "pe": None, "pb": None, "ps": None, "fcf_yield": None,
        }
    eps = metric("eps_diluted")
    equity = metric("equity")
    shares = metric("shares_outstanding")
    revenue = metric("revenue")
    fcf = metric("free_cash_flow")
    book_per_share = (equity / shares) if equity and shares else None
    sales_per_share = (revenue / shares) if revenue and shares else None
    return {
        "status": "available",
        "price": price,
        "pe": (price / eps) if eps and eps > 0 else None,
        "pb": (price / book_per_share) if book_per_share and book_per_share > 0 else None,
        "ps": (price / sales_per_share) if sales_per_share and sales_per_share > 0 else None,
        "fcf_yield": (fcf / (price * shares)) if fcf is not None and shares else None,
        "book_value_per_share": book_per_share,
        "sales_per_share": sales_per_share,
        "note": "Multiples use the same reported period as the metrics; price and accounting date are not synchronised.",
    }
