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
from . import rights as data_rights
from .observations import (
    PIN_STATUS_EXACT,
    observation_from_row,
    pin_from_row,
    resolve_pinned,
)

PRICE_SCHEMA = "atlas.market_price.summary.v1"
IMPORT_SCHEMA = "atlas.market_price.import.v2"

#: Version of the canonical-selection contract. v2 makes the *basis* of the choice
#: explicit (latest session, latest imported revision, explicit source, or a saved pin),
#: records the observation identity, and never mixes providers inside one series.
SOURCE_SELECTION_POLICY = "atlas.market_price.selection.v2"
LEGACY_SOURCE_SELECTION_POLICIES = {"atlas.market_price.selection.v1"}
SELECTION_POLICIES = {"latest_session", "latest_revision", "explicit_source", "pinned"}
POLICY_LABELS = {
    "latest_session": (
        "Latest market session at or before the requested date, newest revision of that "
        "session, then deterministic source/mic ordering"
    ),
    "latest_revision": (
        "Most recently imported observation first (ingestion order), then session; this is "
        "'latest import', not 'latest market information'"
    ),
    "explicit_source": "Latest session from one explicitly requested provider",
    "pinned": "The exact revision recorded by a saved observation pin",
}

ALLOWED_REDISTRIBUTION = set(data_rights.INGESTIBLE)
EXPORTABLE_REDISTRIBUTION = set(data_rights.EXPORTABLE)
SUPPORTED_ADJUSTMENT_SEMANTICS = {"unadjusted", "raw"}

#: Historical-identity states for a session inside a price batch. A session is only
#: trusted market history when one of the two positive states applies.
IDENTITY_VERIFIED = "verified_assignment"
IDENTITY_BACKFILL = "source_backfill"
IDENTITY_AMBIGUOUS = "ambiguous"
IDENTITY_CONFLICT = "known_conflicting_identity"
IDENTITY_UNSUPPORTED = "unsupported_identity"
TRUSTED_IDENTITY_STATES = {IDENTITY_VERIFIED, IDENTITY_BACKFILL}


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


def _backfill_verdict(
    basis: Mapping[str, Any] | None,
    *,
    security_id: str,
    mic: str,
    day: str,
) -> tuple[dict[str, Any] | None, str]:
    """Validate an operator's source-backed historical identity basis.

    A backfill is only credible when it names the same security and venue, supplies a
    permanent identifier that equals the stored security identity, cites the source record
    that establishes the mapping, names who established it, and covers the session. A
    current ticker is never accepted as evidence about the past.
    """
    if not isinstance(basis, Mapping) or not basis:
        return None, "no_verified_identity_basis"
    if str(basis.get("security_id") or "") != security_id:
        return None, "backfill_basis_names_another_security"
    if str(basis.get("venue") or "").upper() != mic.upper():
        return None, "backfill_basis_names_another_venue"
    permanent = str(basis.get("permanent_identifier") or "").strip()
    if not permanent or permanent != security_id:
        return None, "backfill_basis_lacks_a_matching_permanent_identifier"
    if not str(basis.get("evidence") or "").strip():
        return None, "backfill_basis_cites_no_source_record"
    if not str(basis.get("established_by") or "").strip():
        return None, "backfill_basis_has_no_accountable_author"
    applies = basis.get("applies_to")
    if isinstance(applies, (list, tuple, set)) and applies and str(sorted(applies)[0]) not in {"all", "*"}:
        covered = {str(item)[:10] for item in applies}
        if day not in covered:
            return None, "backfill_basis_does_not_cover_this_session"
    return {
        "state": IDENTITY_BACKFILL,
        "permanent_identifier": permanent,
        "venue": mic.upper(),
        "evidence": str(basis["evidence"]).strip(),
        "established_by": str(basis["established_by"]).strip(),
        "established_at": str(basis.get("established_at") or "").strip() or None,
        "mapping_basis": "source_backed_historical_backfill",
        "distinct_from_live_assignment": True,
    }, ""


def _validate_batch_sessions(
    master: SecurityMaster,
    *,
    ticker: str,
    security_id: str,
    mic: str,
    listing: Mapping[str, Any],
    sessions: Iterable[str],
    backfill_basis: Mapping[str, Any] | None = None,
    identity_pinned: bool = False,
) -> dict[str, Any]:
    """Classify the historical identity of every session in a price batch.

    Resolving a ticker once at a declared ``as_of`` date cannot establish what a ticker
    meant on an arbitrary past session. Each distinct session is re-resolved and classified:

    ``verified_assignment``
        The session falls inside this security's active listing/ticker assignment.
    ``source_backfill``
        No live assignment covers the session, but the operator supplied a verifiable
        source-backed basis (permanent identifier, venue, evidence record, author).
    ``ambiguous``
        No assignment and no verified basis. The rows are quarantined, not stored.
    ``known_conflicting_identity``
        The session resolves to a different security altogether. The batch is rejected as a
        cross-identity contamination rather than split by guesswork.
    """
    days = sorted({str(item)[:10] for item in sessions})
    valid_from = str(listing.get("valid_from") or "")[:10]
    valid_to = str(listing.get("valid_to") or "")[:10]
    advisories: list[dict[str, Any]] = []
    verified: list[str] = []
    backfills: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for day in days:
        if valid_from and day < valid_from:
            advisories.append(
                {"session": day, "reason": "session_before_listing_valid_from",
                 "listing_valid_from": valid_from}
            )
        if valid_to and day > valid_to:
            advisories.append(
                {"session": day, "reason": "session_after_listing_valid_to",
                 "listing_valid_to": valid_to}
            )
        resolution = master.resolve_ticker(ticker, as_of=day)
        matches = [
            candidate for candidate in resolution.candidates
            if candidate.security_id == security_id
            and (candidate.mic or "").upper() == mic.upper()
        ]
        others = {candidate.security_id for candidate in resolution.candidates} - {security_id}
        if matches and others and not identity_pinned:
            conflicts.append(
                {
                    "session": day,
                    "reason": "ticker_is_assigned_to_more_than_one_security",
                    "other_security_ids": sorted(others),
                    "candidates": [candidate.to_dict() for candidate in resolution.candidates],
                }
            )
        elif len(matches) == 1:
            verified.append(day)
        elif others:
            conflicts.append(
                {
                    "session": day,
                    "reason": "session_resolves_to_a_different_security",
                    "other_security_ids": sorted(others),
                    "candidates": [candidate.to_dict() for candidate in resolution.candidates],
                }
            )
        else:
            basis, reason = _backfill_verdict(
                backfill_basis, security_id=security_id, mic=mic.upper(), day=day
            )
            if basis is not None:
                backfills.append({"session": day, **basis})
            else:
                quarantined.append(
                    {
                        "session": day,
                        "state": IDENTITY_AMBIGUOUS,
                        "reason": reason,
                        "required": (
                            "supply backfill_basis naming the permanent identifier, venue and "
                            "source record that establish this session's security"
                        ),
                    }
                )
    if conflicts:
        raise PriceImportError(
            f"price batch spans {len(conflicts)} session(s) whose ticker resolves to a "
            f"different security than {security_id} on {mic.upper()}; split the batch by "
            f"identity or pin security_id and mic explicitly: {conflicts[0]}"
        )
    states = {
        IDENTITY_VERIFIED: len(verified),
        IDENTITY_BACKFILL: len(backfills),
        IDENTITY_AMBIGUOUS: len(quarantined),
        IDENTITY_CONFLICT: len(conflicts),
        IDENTITY_UNSUPPORTED: 0,
    }
    return {
        "sessions_checked": len(days),
        "first_session": days[0],
        "last_session": days[-1],
        "security_id": security_id,
        "mic": mic.upper(),
        "identity_basis": "per_session_ticker_resolution_with_source_backfill",
        "identity_states": states,
        "trusted_sessions": len(verified) + len(backfills),
        "verified_sessions": verified,
        "backfill_sessions": backfills,
        "quarantined_sessions": quarantined,
        "unassigned_sessions": [item["session"] for item in quarantined],
        "listing_validity_advisories": advisories,
        "policy": (
            "A session enters trusted market history only inside a live assignment window or "
            "under a source-backed historical backfill. An unverified session is quarantined; "
            "its rows are not stored, and no current ticker is assumed to describe the past."
        ),
    }

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
    backfill_basis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Import observed closes for one security without destroying other sources.

    The import is all-or-nothing. Every row is parsed and checked before a single write;
    a malformed row rejects the batch instead of leaving a partial observation set.
    Identical replay is idempotent, while a changed value for the same source and session
    is appended as a new revision with ``supersedes_bar`` pointing to its predecessor.
    """
    rights_decision = data_rights.classify(
        redistribution, copyright_licence=licence, copyright_holder=source_name
    )
    if not rights_decision["trusted"]:
        raise PriceImportError(
            "market data rights must be a known redistribution class ("
            + ", ".join(sorted(data_rights.INGESTIBLE))
            + f"); an unknown or incomplete grant fails closed: {redistribution!r}"
        )
    redistribution = rights_decision["redistribution"]
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

    session_identity = _validate_batch_sessions(
        SecurityMaster(db),
        ticker=identity["ticker"],
        security_id=identity["security_id"],
        mic=resolved_mic,
        listing=listing,
        sessions=[bar.ts_utc for bar in prepared],
        backfill_basis=backfill_basis,
        identity_pinned=bool(security_id and mic),
    )
    quarantined_days = {
        item["session"] for item in session_identity["quarantined_sessions"]
    }
    if quarantined_days:
        keep = [
            index for index, bar in enumerate(prepared)
            if str(bar.ts_utc)[:10] not in quarantined_days
        ]
        prepared = [prepared[index] for index in keep]
        canonical_rows = [canonical_rows[index] for index in keep]
        if not prepared:
            raise PriceImportError(
                "no session in this batch has a verified historical identity: "
                + ", ".join(sorted(quarantined_days))
                + "; supply a source-backed backfill basis or correct the batch"
            )

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
    # A project-authored synthetic series must never register as an observed market
    # source: read models label ``market_data`` as reported, which would present a
    # synthetic fixture as exchange data. The collection method decides the source kind.
    source_kind = (
        "synthetic" if collection_method.strip().lower() == "synthetic_fixture"
        else "market_data"
    )
    with db.transaction():
        existing_source = db.query_one("SELECT * FROM source WHERE source_id=?", (source_id,))
        if existing_source is None:
            db.execute(
                "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    source_id, source_name.strip(), source_kind, None, licence.strip(),
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
        "session_identity": session_identity,
        "quarantined": len(quarantined_days),
        "rights": rights_decision,
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


def _resolve_policy(
    policy: str,
    *,
    source_id: str | None,
    pin: Mapping[str, Any] | None,
) -> str:
    """Normalise a policy name and reject combinations it cannot answer."""
    if policy in LEGACY_SOURCE_SELECTION_POLICIES:
        # Legacy callers asked for "the canonical quote"; v2 states that basis as
        # latest_session explicitly instead of implying it.
        policy = "latest_session"
    if policy == SOURCE_SELECTION_POLICY:
        # v2 states the basis: an explicit source filter *is* the explicit_source policy.
        policy = "explicit_source" if source_id else "latest_session"
    if policy not in SELECTION_POLICIES:
        raise PriceImportError(f"unknown market-price selection policy {policy!r}")
    if policy == "explicit_source" and not source_id:
        raise PriceImportError("the explicit_source policy requires a source_id")
    if policy == "pinned" and not pin:
        raise PriceImportError("the pinned policy requires a stored observation pin")
    return policy


def _pinned_row(
    db: Database,
    security_id: str,
    pin: Mapping[str, Any],
    *,
    mic: str | None,
) -> tuple[Any | None, dict[str, Any]]:
    """Resolve a saved pin to its exact revision, never to the latest price."""
    replay = resolve_pinned(db, pin)
    if replay["status"] != PIN_STATUS_EXACT or replay["observation"] is None:
        selection = {
            "policy": SOURCE_SELECTION_POLICY,
            "requested_policy": "pinned",
            "policy_label": POLICY_LABELS["pinned"],
            "selected_source_id": pin.get("source_id"),
            "price_date": pin.get("session_date"),
            "revision_seq": pin.get("revision_seq"),
            "observation_id": pin.get("observation_id"),
            "content_hash": pin.get("content_hash"),
            "observation": dict(pin),
            "pinned": True,
            "exact_replay": False,
            "selection_status": replay["status"],
            "reason": replay["reason"],
            "conflict_resolution": "saved_observation_pin",
            "alternatives": [],
            "conflict": False,
        }
        return None, selection
    observation = replay["observation"]
    if mic and str(mic).upper() != str(observation["mic"]).upper():
        raise PriceImportError(
            f"pinned observation is on {observation['mic']}, not the requested venue {mic.upper()}"
        )
    if observation["security_id"] != security_id:
        raise PriceImportError(
            "pinned observation belongs to a different security; refusing to re-use it"
        )
    row = {
        "security_id": observation["security_id"],
        "mic": observation["mic"],
        "interval": observation["interval"],
        "ts_utc": observation["session"],
        "close": observation["close"],
        "currency": observation["currency"],
        "adjustment_status": observation["adjustment"],
        "source_id": observation["source_id"],
        "observed_at": observation["observed_at"],
        "ingested_at": observation["ingested_at"],
        "revision_seq": observation["revision_seq"],
        "name": pin.get("source_name"),
        "licence": pin.get("licence"),
        "redistribution": pin.get("redistribution"),
    }
    selection = {
        "policy": SOURCE_SELECTION_POLICY,
        "requested_policy": "pinned",
        "policy_label": POLICY_LABELS["pinned"],
        "requested_source_id": observation["source_id"],
        "selected_source_id": observation["source_id"],
        "price_date": observation["session_date"],
        "revision_seq": observation["revision_seq"],
        "observation_id": observation["observation_id"],
        "content_hash": observation["content_hash"],
        "observation": observation,
        "pinned": True,
        "exact_replay": True,
        "selection_status": PIN_STATUS_EXACT,
        "conflict_resolution": "saved_observation_pin",
        "dimensions": {
            "market_session": "pinned_session",
            "provider": "pinned_provider",
            "revision": "pinned_revision",
            "adjustment": "raw_observation_only",
        },
        "alternatives": [],
        "conflict": False,
        "provider_consistency": "single_provider",
    }
    return row, selection


def _selected_row(
    db: Database,
    security_id: str,
    date_text: str,
    *,
    source_id: str | None = None,
    mic: str | None = None,
    policy: str = SOURCE_SELECTION_POLICY,
    pin: Mapping[str, Any] | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    resolved_policy = _resolve_policy(policy, source_id=source_id, pin=pin)
    if resolved_policy == "pinned":
        assert pin is not None
        return _pinned_row(db, security_id, pin, mic=mic)
    ordering = {
        "latest_session": "b.ts_utc DESC, b.revision_seq DESC, b.source_id ASC, b.mic ASC",
        "latest_revision": "b.ingested_at DESC, b.ts_utc DESC, b.revision_seq DESC, b.source_id ASC",
        "explicit_source": "b.ts_utc DESC, b.revision_seq DESC, b.mic ASC",
    }[resolved_policy]
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
        + f" ORDER BY {ordering} LIMIT 1",
        params,
    )
    observation = (
        observation_from_row(
            row,
            source_name=row["name"],
            dataset=row["name"],
            licence=row["licence"],
            redistribution=row["redistribution"],
        )
        if row is not None else None
    )
    cutoff = str(date_text)[:10]
    selection: dict[str, Any] = {
        "policy": SOURCE_SELECTION_POLICY,
        "requested_policy": resolved_policy,
        "policy_label": POLICY_LABELS[resolved_policy],
        "requested_source_id": source_id,
        "selected_source_id": row["source_id"] if row else None,
        "price_date": row["ts_utc"][:10] if row else None,
        "session": row["ts_utc"] if row else None,
        "ingested_at": row["ingested_at"] if row else None,
        "revision_seq": row["revision_seq"] if row else None,
        "observation_id": observation["observation_id"] if observation else None,
        "content_hash": observation["content_hash"] if observation else None,
        "observation": observation,
        "pinned": False,
        "exact_replay": None,
        "information_cutoff": None if cutoff >= "2999-12-31" else cutoff,
        "dimensions": {
            "market_session": (
                "explicitly_requested_source_latest_session" if source_id else
                "latest_session_at_or_before_cutoff"
            ),
            "provider": (
                "explicit_source" if source_id else
                "single_provider_selected_then_held_constant"
            ),
            "revision": (
                "latest_ingested_revision" if resolved_policy == "latest_revision"
                else "latest_revision_of_selected_session"
            ),
            "adjustment": "raw_observation_only",
        },
        "conflict_resolution": (
            "explicit_source_filter" if source_id else
            "latest_session_then_latest_revision_then_source_id"
        ),
        "alternatives": [],
        "conflict": False,
        "provider_consistency": "single_provider",
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
    pin: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the selected observation at or before a comparison date.

    The result carries the observation identity (``observation_id``, ``content_hash``,
    revision and retrieval metadata) as well as the value, so a caller can pin exactly
    what it used.
    """
    row, selection = _selected_row(
        db, security_id, date_text, source_id=source_id, mic=mic, policy=policy, pin=pin
    )
    if row is None:
        return None
    pin_payload = None
    if selection.get("requested_policy") != "pinned":
        pin_payload = pin_from_row(
            row,
            source_name=row["name"],
            dataset=row["name"],
            licence=row["licence"],
            redistribution=row["redistribution"],
        )
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
        "observation_id": (selection.get("observation") or {}).get("observation_id"),
        "content_hash": (selection.get("observation") or {}).get("content_hash"),
        "observation": selection.get("observation"),
        "exact_replay": selection.get("exact_replay"),
        "pin": pin_payload,
        "source_selection": selection,
    }


def price_for_pin(
    db: Database,
    pin: Mapping[str, Any],
    *,
    information_cutoff: str | None = None,
) -> dict[str, Any]:
    """Replay a saved observation pin, or say plainly that exact replay is unavailable."""
    replay = resolve_pinned(db, pin)
    if replay["status"] != PIN_STATUS_EXACT:
        return {
            "schema": "atlas.market_price.replay.v1",
            "status": replay["status"],
            "exact_replay": False,
            "reason": replay["reason"],
            "pin": dict(pin) if isinstance(pin, Mapping) else None,
            "price": None,
        }
    price = replay["price"]
    cutoff = (information_cutoff or "")[:10]
    lookahead_safe = not cutoff or price["date"] <= cutoff
    return {
        "schema": "atlas.market_price.replay.v1",
        "status": "exact",
        "exact_replay": True,
        "lookahead_safe": lookahead_safe,
        "information_cutoff": cutoff or None,
        "pin": dict(pin),
        "observation": replay["observation"],
        "price": {**price, "lookahead_safe": lookahead_safe},
        "reason": (
            "Exact pinned revision replayed. A later correction to this session does not "
            "change this result." if lookahead_safe else
            "The pinned price is after the information cutoff; the replay is reported but "
            "must not be used as a point-in-time comparison."
        ),
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
        # The comparison fields stay present and explicitly null: a caller must be able to
        # distinguish "no accounting period because there is no price" from a missing key,
        # and no period end may be asserted for a comparison that did not happen.
        return {
            "schema": "atlas.market_analysis.v1",
            "status": "unavailable",
            "reason": "No observed price exists on or before the comparison date.",
            "price": None,
            "price_date": None,
            "accounting_period_end": None,
            "information_cutoff": (information_cutoff or "")[:10] or None,
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
