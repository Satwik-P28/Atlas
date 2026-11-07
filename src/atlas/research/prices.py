"""Market-price ingestion and price-based analysis with explicit rights.

Atlas does not redistribute vendor market data. A user or an authorised feed may import
observed prices; the resulting rows retain the source, retrieval time, adjustment
semantics and redistribution terms. Analyses that require a price report the price as
unavailable until such an import exists, and never substitute a synthetic quote.

Market observations are append-only. A source is identified by its provider/dataset and
rights terms, never by a shared placeholder id. Importing provider B cannot delete or
rewrite provider A's observations, and two providers may report different closes for the
same security and session. Selecting a canonical quote is a separate, versioned policy;
the alternatives remain inspectable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..entities.master import SecurityMaster
from ..market.bars import ADJUSTMENT_RAW, Bar, BarStore
from ..storage.db import Database

PRICE_SCHEMA = "atlas.market_price.summary.v1"
IMPORT_SCHEMA = "atlas.market_price.import.v2"
SOURCE_SELECTION_POLICY = "atlas.market_price.selection.v1"

ALLOWED_REDISTRIBUTION = {"public_domain", "user_responsibility", "restricted", "private"}
EXPORTABLE_REDISTRIBUTION = {"public_domain"}
SUPPORTED_ADJUSTMENT_SEMANTICS = {"unadjusted", "raw"}


class PriceImportError(ValueError):
    """A price import was rejected because its provenance, identity or rights are incomplete."""


def _parse_ts(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise PriceImportError("price row has no date")
    try:
        if "T" in text:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return iso(moment.astimezone(timezone.utc))
        day = parse_date(text)
    except (TypeError, ValueError) as exc:
        raise PriceImportError(f"price row has an invalid date: {text!r}") from exc
    # Daily bars are stored at the UTC midnight convention used by this importer.
    return f"{day.isoformat()}T00:00:00Z"


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PriceImportError(f"price row has an invalid {field}: {value!r}") from exc
    if not parsed.is_finite():
        raise PriceImportError(f"price row has a non-finite {field}")
    return parsed


def _source_identity(
    source_name: str,
    licence: str,
    redistribution: str,
    authorization_basis: str | None,
    collection_method: str,
) -> tuple[str, str]:
    """Return a stable source id and canonical identity hash.

    The same provider with a different licence or redistribution grant is a different
    source record. A later import therefore cannot rewrite an earlier observation's
    rights by reusing a generic id.
    """
    canonical = json.dumps(
        {
            "source_name": source_name.strip(),
            "licence": licence.strip(),
            "redistribution": redistribution,
            "authorization_basis": (authorization_basis or "").strip(),
            "collection_method": collection_method.strip(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"market-{digest[:20]}", digest


def _resolve_security(
    db: Database,
    *,
    ticker: str,
    as_of: str | None,
    security_id: str | None,
    mic: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve a ticker to exactly one active listing, or fail explicitly."""
    master = SecurityMaster(db)
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise PriceImportError("a price import requires a ticker")
    resolution = master.resolve_ticker(symbol, as_of=as_of)
    candidates = list(resolution.candidates)
    if not candidates:
        raise PriceImportError(
            f"no active ticker assignment resolves {symbol}; supply a verified identity instead of guessing"
        )
    if security_id:
        candidates = [candidate for candidate in candidates if candidate.security_id == security_id]
        if not candidates:
            raise PriceImportError(
                f"ticker {symbol} is not assigned to requested security {security_id} at {as_of or 'the current date'}"
            )
    distinct_securities = {candidate.security_id for candidate in candidates}
    if len(distinct_securities) > 1:
        raise PriceImportError(
            f"ticker {symbol} is ambiguous across {len(distinct_securities)} securities; "
            "specify security_id and mic explicitly"
        )
    resolved_id = candidates[0].security_id
    listings = []
    cutoff = iso_date(as_of or utcnow())
    for listing in master.listings(resolved_id):
        if listing.get("mic") is None:
            continue
        if listing.get("valid_from") and str(listing["valid_from"])[:10] > cutoff:
            continue
        if listing.get("valid_to") and str(listing["valid_to"])[:10] < cutoff:
            continue
        if mic and str(listing["mic"]).upper() != mic.upper():
            continue
        listings.append(listing)
    if mic and not listings:
        raise PriceImportError(
            f"security {resolved_id} has no active listing on {mic.upper()} at {cutoff}"
        )
    if len(listings) != 1:
        choices = [
            {"listing_id": item["listing_id"], "mic": item["mic"], "currency": item.get("currency")}
            for item in listings
        ]
        raise PriceImportError(
            f"security {resolved_id} has {len(listings)} active listings; "
            "specify mic to select the exact trading venue"
            if listings else
            f"security {resolved_id} has no active listing at {cutoff}"
        )
    listing = listings[0]
    security = master.security(resolved_id)
    if security is None:  # pragma: no cover - resolver invariant
        raise PriceImportError(f"resolved security {resolved_id} is missing")
    return (
        {"security_id": resolved_id, "ticker": symbol, "as_of": cutoff,
         "resolution_confidence": resolution.confidence,
         "candidates": [candidate.to_dict() for candidate in resolution.candidates]},
        security,
        listing,
    )


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
    automated_access_authorized: bool = False,
    authorization_basis: str | None = None,
    collection_method: str = "user_import",
    security_id: str | None = None,
    mic: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Import observed closes for one security without destroying other sources.

    The import is all-or-nothing. Every row is parsed and checked before a single write;
    a malformed row rejects the batch instead of leaving a partial observation set.
    Identical replay is idempotent, while a changed value for the same source and session
    is appended as a new revision with ``supersedes_bar`` pointing to its predecessor.
    """
    if redistribution not in ALLOWED_REDISTRIBUTION:
        raise PriceImportError(
            "redistribution terms must be one of " + ", ".join(sorted(ALLOWED_REDISTRIBUTION))
        )
    if not str(source_name or "").strip() or not str(licence or "").strip():
        raise PriceImportError("a price import requires a source name and a licence")
    adjustment = str(adjustment_semantics or "").strip().lower()
    if adjustment not in SUPPORTED_ADJUSTMENT_SEMANTICS:
        raise PriceImportError(
            "only raw/unadjusted observations may be imported; adjusted series must be "
            "derived on read from raw bars and corporate actions"
        )
    if automated_access_authorized and not str(authorization_basis or "").strip():
        raise PriceImportError(
            "automated access requires an explicit authorization basis; rights are never inferred"
        )
    if redistribution == "public_domain" and not str(authorization_basis or "").strip():
        raise PriceImportError(
            "public-domain redistribution requires an authorization basis naming the source terms"
        )

    identity, security, listing = _resolve_security(
        db, ticker=ticker, as_of=as_of, security_id=security_id, mic=mic
    )
    resolved_mic = str(listing["mic"]).upper()
    expected_currency = str(listing.get("currency") or security.get("currency") or "USD").upper()
    if str(currency).upper() != expected_currency:
        raise PriceImportError(
            f"currency {currency!r} does not match the selected listing/security currency {expected_currency}"
        )

    now = iso(utcnow())
    retrieved = iso(_parse_ts(retrieved_at)) if retrieved_at else now
    source_id, source_hash = _source_identity(
        source_name, licence, redistribution, authorization_basis, collection_method
    )

    prepared: list[Bar] = []
    canonical_rows: list[dict[str, Any]] = []
    seen: dict[str, tuple[str, str, str, str, str | None]] = {}
    duplicate_input_rows = 0
    for index, item in enumerate(rows):
        ts = _parse_ts(item.get("date") or item.get("ts_utc"))
        close = _decimal(item.get("close"), field="close")
        if close <= 0:
            raise PriceImportError(f"row {index}: close must be positive")
        open_price = _decimal(item.get("open", close), field="open")
        high = _decimal(item.get("high", close), field="high")
        low = _decimal(item.get("low", close), field="low")
        if min(open_price, high, low, close) <= 0:
            raise PriceImportError(f"row {index}: OHLC values must be positive")
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            raise PriceImportError(f"row {index}: OHLC values are internally inconsistent")
        row_adjustment = str(item.get("adjustment") or adjustment).strip().lower()
        if row_adjustment not in SUPPORTED_ADJUSTMENT_SEMANTICS:
            raise PriceImportError(
                f"row {index}: adjustment {row_adjustment!r} is not a raw observation"
            )
        volume: Decimal | None = None
        if item.get("volume") is not None:
            volume = _decimal(item.get("volume"), field="volume")
            if volume < 0:
                raise PriceImportError(f"row {index}: volume cannot be negative")
        signature = (
            str(open_price), str(high), str(low), str(close),
            str(volume) if volume is not None else None,
        )
        if ts in seen:
            if seen[ts] != signature:
                raise PriceImportError(
                    f"batch contains conflicting observations for {ts}; split them into distinct source batches"
                )
            duplicate_input_rows += 1
            continue
        seen[ts] = signature
        prepared.append(
            Bar(
                security_id=identity["security_id"],
                mic=resolved_mic,
                ts_utc=ts,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                currency=expected_currency,
                source_id=source_id,
                adjustment_status=ADJUSTMENT_RAW,
                observed_at=retrieved,
            )
        )
        canonical_rows.append(
            {
                "ts_utc": ts, "open": str(open_price), "high": str(high), "low": str(low),
                "close": str(close), "volume": str(volume) if volume is not None else None,
            }
        )
    if not prepared:
        raise PriceImportError("import contains no usable observations")

    content_hash = hashlib.sha256(
        json.dumps(
            {
                "source_id": source_id,
                "security_id": identity["security_id"],
                "mic": resolved_mic,
                "adjustment": adjustment,
                "rows": sorted(canonical_rows, key=lambda row: row["ts_utc"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    batch_id = f"MIB-{content_hash[:24]}"

    series_id = "MPS-" + hashlib.sha256(
        f"{identity['security_id']}|{source_id}|{adjustment}".encode("utf-8")
    ).hexdigest()[:24]
    with db.transaction():
        existing_source = db.query_one("SELECT * FROM source WHERE source_id=?", (source_id,))
        if existing_source is None:
            db.execute(
                "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    source_id, source_name.strip(), "market_data", None, licence.strip(),
                    redistribution,
                    f"identity_sha256={source_hash}; dataset={source_name.strip()}; "
                    f"collection={collection_method}; authorization={authorization_basis or 'none'}",
                    now,
                ),
            )
        else:
            expected = (
                source_name.strip(), licence.strip(), redistribution,
            )
            actual = (
                existing_source["name"], existing_source["licence"],
                existing_source["redistribution"],
            )
            if actual != expected:
                raise PriceImportError(
                    f"source identity collision for {source_id}; existing rights were not modified"
                )
        existing_series = db.query_one(
            "SELECT * FROM market_price_series WHERE security_id=? AND source_id=? "
            "AND adjustment_semantics=?",
            (identity["security_id"], source_id, adjustment),
        )
        if existing_series is None:
            db.execute(
                "INSERT INTO market_price_series (series_id, security_id, source_id, series_name, licence, "
                "redistribution, automated_access_authorized, authorization_basis, collection_method, "
                "adjustment_semantics, retrieved_from, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    series_id, identity["security_id"], source_id, source_name.strip(), licence.strip(),
                    redistribution, int(automated_access_authorized), authorization_basis,
                    collection_method, adjustment, retrieved, now,
                ),
            )
        else:
            series_id = existing_series["series_id"]
            if (
                existing_series["licence"] != licence.strip()
                or existing_series["redistribution"] != redistribution
                or int(existing_series["automated_access_authorized"]) != int(automated_access_authorized)
                or (existing_series["authorization_basis"] or None) != (authorization_basis or None)
            ):
                raise PriceImportError(
                    "the existing series rights differ from this import; historical rights are immutable"
                )
        summary = BarStore(db).ingest(prepared, observed_at=retrieved)
        db.execute(
            "INSERT INTO ingestion_run (run_id, command, started_at, finished_at, status, stats_json, error, resumable) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
            "finished_at=excluded.finished_at, status=excluded.status, stats_json=excluded.stats_json, "
            "error=NULL, resumable=excluded.resumable",
            (
                batch_id, "research.import_price_series", now, iso(utcnow()), "completed",
                json.dumps(
                    {
                        "schema": IMPORT_SCHEMA,
                        "security_id": identity["security_id"], "mic": resolved_mic,
                        "source_id": source_id, "adjustment_semantics": adjustment,
                        "content_hash": content_hash, "rows": len(prepared),
                        "duplicate_input_rows": duplicate_input_rows,
                        "inserted": summary.inserted, "duplicates": summary.duplicates,
                        "revisions": summary.revisions,
                    },
                    sort_keys=True,
                ),
                None, 0,
            ),
        )

    return {
        "schema": IMPORT_SCHEMA,
        "batch_id": batch_id,
        "content_hash": content_hash,
        "ticker": identity["ticker"],
        "security_id": identity["security_id"],
        "mic": resolved_mic,
        "identity": identity,
        "written": summary.inserted,
        "revisions": summary.revisions,
        "duplicates": summary.duplicates + duplicate_input_rows,
        "rejected": 0,
        "source": {
            "source_id": source_id,
            "name": source_name.strip(),
            "identity_sha256": source_hash,
            "licence": licence.strip(),
            "redistribution": redistribution,
            "export_allowed": redistribution in EXPORTABLE_REDISTRIBUTION,
            "retrieved_at": retrieved,
        },
        "adjustment_semantics": adjustment,
        "authorization": {
            "automated_access_authorized": bool(automated_access_authorized),
            "authorization_basis": authorization_basis,
            "collection_method": collection_method,
            "redistribution": redistribution,
        },
        "limitation": (
            "Imported prices are user-supplied observations, not a point-in-time vendor vintage. "
            "They are not redistributed in a research package unless their terms permit it. "
            "A correction appends a revision; the prior observation is retained."
        ),
    }


def _selected_row(
    db: Database,
    security_id: str,
    date_text: str,
    *,
    source_id: str | None = None,
    mic: str | None = None,
    policy: str = SOURCE_SELECTION_POLICY,
) -> tuple[Any | None, dict[str, Any]]:
    if policy != SOURCE_SELECTION_POLICY:
        raise PriceImportError(f"unknown market-price selection policy {policy!r}")
    where = [
        "b.security_id=?", "b.interval='1d'", "substr(b.ts_utc,1,10)<=?",
        "b.revision_seq=(SELECT MAX(b2.revision_seq) FROM bar b2 WHERE "
        "b2.security_id=b.security_id AND b2.mic=b.mic AND b2.interval=b.interval "
        "AND b2.ts_utc=b.ts_utc AND b2.source_id=b.source_id)",
    ]
    params: list[Any] = [security_id, str(date_text)[:10]]
    if source_id:
        where.append("b.source_id=?")
        params.append(source_id)
    if mic:
        where.append("b.mic=?")
        params.append(mic.upper())
    row = db.query_one(
        "SELECT b.*, s.name, s.licence, s.redistribution FROM bar b "
        "LEFT JOIN source s ON s.source_id=b.source_id WHERE "
        + " AND ".join(where)
        + " ORDER BY b.ts_utc DESC, b.ingested_at DESC, b.source_id ASC, b.mic ASC LIMIT 1",
        params,
    )
    selection: dict[str, Any] = {
        "policy": policy,
        "requested_source_id": source_id,
        "selected_source_id": row["source_id"] if row else None,
        "price_date": row["ts_utc"][:10] if row else None,
        "ingested_at": row["ingested_at"] if row else None,
        "conflict_resolution": (
            "explicit_source_filter" if source_id else
            "latest_session_then_latest_ingestion_then_source_id"
        ),
        "alternatives": [],
        "conflict": False,
    }
    if row is not None:
        alternatives = [
            {
                "source_id": alt["source_id"], "mic": alt["mic"],
                "close": float(alt["close"]), "ingested_at": alt["ingested_at"],
                "revision_seq": alt["revision_seq"],
            }
            for alt in db.query(
                "SELECT b.source_id, b.mic, b.close, b.ingested_at, b.revision_seq FROM bar b "
                "WHERE b.security_id=? AND b.interval='1d' AND b.ts_utc=? "
                "AND b.revision_seq=(SELECT MAX(b2.revision_seq) FROM bar b2 WHERE "
                "b2.security_id=b.security_id AND b2.mic=b.mic AND b2.interval=b.interval "
                "AND b2.ts_utc=b.ts_utc AND b2.source_id=b.source_id) "
                "ORDER BY b.source_id, b.mic",
                (security_id, row["ts_utc"]),
            )
            if alt["source_id"] != row["source_id"] or alt["mic"] != row["mic"]
        ]
        selection["alternatives"] = alternatives
        closes = {round(float(row["close"]), 10)} | {round(item["close"], 10) for item in alternatives}
        selection["conflict"] = len(closes) > 1
    return row, selection


def price_summary(
    db: Database, security_id: str, *, source_id: str | None = None,
    mic: str | None = None,
) -> dict[str, Any]:
    row, selection = _selected_row(
        db, security_id, "2999-12-31", source_id=source_id, mic=mic
    )
    if row is None:
        return {
            "schema": PRICE_SCHEMA,
            "status": "unavailable",
            "observations": 0,
            "source_selection": selection,
            "detail": (
                "No authorised price series is stored for this security. Atlas does not bundle or "
                "invent market prices, so price multiples, reverse DCF and price-versus-model "
                "comparisons are unavailable."
            ),
        }
    chosen_source = row["source_id"]
    observations = db.scalar(
        "SELECT COUNT(DISTINCT ts_utc) FROM bar WHERE security_id=? AND interval='1d' "
        "AND source_id=? AND revision_seq=(SELECT MAX(b2.revision_seq) FROM bar b2 "
        "WHERE b2.security_id=bar.security_id AND b2.mic=bar.mic AND b2.interval=bar.interval "
        "AND b2.ts_utc=bar.ts_utc AND b2.source_id=bar.source_id)",
        (security_id, chosen_source), 0,
    )
    bounds = db.query_one(
        "SELECT MIN(ts_utc) AS first, MAX(ts_utc) AS last FROM bar WHERE security_id=? "
        "AND interval='1d' AND source_id=?",
        (security_id, chosen_source),
    )
    source_ids = [
        item["source_id"] for item in db.query(
            "SELECT DISTINCT source_id FROM bar WHERE security_id=? ORDER BY source_id", (security_id,)
        )
    ]
    return {
        "schema": PRICE_SCHEMA,
        "status": "available",
        "observations": int(observations or 0),
        "first_date": bounds["first"][:10] if bounds and bounds["first"] else None,
        "last_date": bounds["last"][:10] if bounds and bounds["last"] else None,
        "latest_close": float(row["close"]),
        "latest_session": row["ts_utc"][:10],
        "currency": row["currency"],
        "mic": row["mic"],
        "adjustment_semantics": row["adjustment_status"],
        "source_selection": selection,
        "available_source_ids": source_ids,
        "source": {
            "source_id": row["source_id"],
            "name": row["name"],
            "licence": row["licence"],
            "redistribution": row["redistribution"],
            "export_allowed": row["redistribution"] in EXPORTABLE_REDISTRIBUTION,
            "observed_at": row["observed_at"],
            "ingested_at": row["ingested_at"],
            "revision_seq": row["revision_seq"],
        },
        "limitation": (
            "Observed historical closes are not a point-in-time vendor vintage; corporate-action "
            "adjustment is whatever the importer declared. Other providers' observations are retained "
            "and inspectable, and changing the selected source is explicit."
        ),
    }


def price_history(
    db: Database,
    security_id: str,
    *,
    limit: int = 400,
    end_date: str | None = None,
    source_id: str | None = None,
    mic: str | None = None,
) -> dict[str, Any]:
    """Return one provider's observations up to ``end_date``; a cutoff sees no later session."""
    cutoff = (end_date or "")[:10]
    _, selection = _selected_row(
        db, security_id, cutoff or "2999-12-31", source_id=source_id, mic=mic
    )
    chosen_source = selection.get("selected_source_id")
    if not chosen_source:
        return {
            "status": "unavailable", "observations": 0, "points": [],
            "source_selection": selection,
        }
    where = [
        "b.security_id=?", "b.interval='1d'", "b.source_id=?",
        "b.revision_seq=(SELECT MAX(b2.revision_seq) FROM bar b2 WHERE "
        "b2.security_id=b.security_id AND b2.mic=b.mic AND b2.interval=b.interval "
        "AND b2.ts_utc=b.ts_utc AND b2.source_id=b.source_id)",
    ]
    params: list[Any] = [security_id, chosen_source]
    if cutoff:
        where.append("substr(b.ts_utc,1,10)<=?")
        params.append(cutoff)
    if mic:
        where.append("b.mic=?")
        params.append(mic.upper())
    rows = list(db.query(
        "SELECT b.ts_utc, b.close, b.volume, b.source_id, b.adjustment_status, "
        "s.name, s.licence, s.redistribution FROM bar b LEFT JOIN source s ON s.source_id=b.source_id "
        "WHERE " + " AND ".join(where) + " ORDER BY b.ts_utc DESC LIMIT ?",
        params + [limit],
    ))
    if not rows:
        return {"status": "unavailable", "observations": 0, "points": [],
                "source_selection": selection}
    points = [{"date": row["ts_utc"][:10], "close": float(row["close"]),
               "volume": row["volume"]} for row in reversed(rows)]
    closes = sorted(point["close"] for point in points)
    latest = points[-1]
    below = sum(1 for value in closes if value <= latest["close"])
    latest_row = rows[0]
    return {
        "status": "available",
        "observations": len(points),
        "first_date": points[0]["date"],
        "last_date": latest["date"],
        "latest_close": latest["close"],
        "minimum_close": closes[0],
        "maximum_close": closes[-1],
        "latest_percentile": (below / len(closes)) if closes else None,
        "mic": mic.upper() if mic else None,
        "source": {
            "source_id": latest_row["source_id"], "name": latest_row["name"],
            "licence": latest_row["licence"], "redistribution": latest_row["redistribution"],
        },
        "source_selection": selection,
        "export_allowed": latest_row["redistribution"] in EXPORTABLE_REDISTRIBUTION,
        "points": points,
    }


def price_on_or_before(
    db: Database,
    security_id: str,
    date_text: str,
    *,
    source_id: str | None = None,
    mic: str | None = None,
    policy: str = SOURCE_SELECTION_POLICY,
) -> dict[str, Any] | None:
    """Return the selected source's last observation at or before a comparison date."""
    row, selection = _selected_row(
        db, security_id, date_text, source_id=source_id, mic=mic, policy=policy
    )
    if row is None:
        return None
    return {
        "date": row["ts_utc"][:10],
        "close": float(row["close"]),
        "currency": row["currency"],
        "mic": row["mic"],
        "adjustment_semantics": row["adjustment_status"],
        "source_id": row["source_id"],
        "observed_at": row["observed_at"],
        "ingested_at": row["ingested_at"],
        "revision_seq": row["revision_seq"],
        "source_selection": selection,
    }


def market_analysis(
    *,
    price: Mapping[str, Any] | None,
    history: Mapping[str, Any] | None,
    value_per_share: float | None,
    accounting_period_end: str | None,
    implied: Mapping[str, Any] | None = None,
    information_cutoff: str | None = None,
    filing_available_at: str | None = None,
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
    cutoff = (information_cutoff or "")[:10]
    if cutoff and price_date > cutoff:
        return {
            "schema": "atlas.market_analysis.v1",
            "status": "rejected_lookahead",
            "reason": (
                f"The selected price {price_date} is after the research information cutoff {cutoff}. "
                "Atlas refuses to compare a model with a future price unless the caller labels it "
                "as a hypothetical."
            ),
            "information_cutoff": cutoff,
            "price_date": price_date,
        }
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
        "mic": price.get("mic"),
        "revision_seq": price.get("revision_seq"),
        "adjustment_semantics": price["adjustment_semantics"],
        "accounting_period_end": accounting or None,
        "information_cutoff": cutoff or None,
        "filing_available_at": filing_available_at,
        "lookahead_safe": True,
        "mixed_date": mixed,
        "date_gap_days": (
            (datetime.fromisoformat(price_date) - datetime.fromisoformat(accounting)).days
            if mixed else 0
        ),
        "model_value_per_share": value_per_share,
        "model_premium_to_price": premium,
        "source_selection": price.get("source_selection") or (
            (history or {}).get("source_selection")
        ),
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
