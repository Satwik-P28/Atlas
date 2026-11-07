"""Immutable market-observation identity and exact-revision pinning.

A market observation is a *specific provider's* statement about one security, one
listing venue and one trading session, at one revision. Provider, dataset, session and
revision are all part of its identity: a later import that corrects the same session is a
new observation, not a replacement for the one a saved analysis used.

The identity has two layers:

``content_hash``
    SHA-256 over the canonical observation payload (security, venue, session, OHLCV,
    currency, adjustment convention, source id). Recomputing it from a stored row is how
    a reader detects tampering or schema drift.

``observation_id``
    SHA-256 over the content hash *plus* the revision sequence and adjustment convention,
    prefixed ``MOB-``. Two corrections therefore never collide, and a correction that
    happens to repeat the earlier values (a revert) is still distinguishable.

Pinning is deliberately fail-closed. :func:`resolve_pinned` returns the exact revision or
an explicit ``exact_revision_unavailable`` status. It never substitutes the latest
observation, because "reopen my analysis with today's corrected price" is a different
research claim from "reopen my analysis".
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ..core.units import canonical_decimal
from ..storage.db import Database

OBSERVATION_SCHEMA = "atlas.market_observation.v1"
PIN_SCHEMA = "atlas.market_observation.pin.v1"

#: Reasons a pin cannot be replayed exactly. Every one of them is reported, never hidden.
PIN_STATUS_EXACT = "exact"
PIN_STATUS_MISSING = "exact_revision_unavailable"
PIN_STATUS_CONTENT_MISMATCH = "exact_revision_content_mismatch"
PIN_STATUS_INVALID = "pin_invalid"


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def observation_content_hash(
    *,
    security_id: str,
    mic: str,
    interval: str,
    session: str,
    open_price: str,
    high: str,
    low: str,
    close: str,
    volume: str | None,
    currency: str,
    adjustment: str,
    source_id: str,
) -> str:
    """Hash the observation payload itself, excluding its revision number."""
    payload = {
        "security_id": security_id,
        "mic": str(mic).upper(),
        "interval": interval,
        "session": session,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "currency": currency,
        "adjustment": adjustment,
        "source_id": source_id,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def observation_id(
    *,
    source_id: str,
    security_id: str,
    mic: str,
    interval: str,
    session: str,
    adjustment: str,
    revision_seq: int,
    content_hash: str,
) -> str:
    """Stable id for one revision of one observation."""
    canonical = _canonical(
        {
            "source_id": source_id,
            "security_id": security_id,
            "mic": str(mic).upper(),
            "interval": interval,
            "session": session,
            "adjustment": adjustment,
            "revision_seq": int(revision_seq),
            "content_hash": content_hash,
        }
    )
    return "MOB-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def observation_from_row(
    row: Mapping[str, Any],
    *,
    source_name: str | None = None,
    dataset: str | None = None,
    licence: str | None = None,
    redistribution: str | None = None,
) -> dict[str, Any]:
    """Build the immutable identity of a stored ``bar`` row."""
    close = canonical_decimal(row["close"])
    digest = observation_content_hash(
        security_id=row["security_id"],
        mic=row["mic"],
        interval=row["interval"],
        session=row["ts_utc"],
        open_price=canonical_decimal(row["open"]),
        high=canonical_decimal(row["high"]),
        low=canonical_decimal(row["low"]),
        close=close,
        volume=canonical_decimal(row["volume"]) if row["volume"] is not None else None,
        currency=row["currency"],
        adjustment=row["adjustment_status"],
        source_id=row["source_id"],
    )
    return {
        "schema": OBSERVATION_SCHEMA,
        "observation_id": observation_id(
            source_id=row["source_id"],
            security_id=row["security_id"],
            mic=row["mic"],
            interval=row["interval"],
            session=row["ts_utc"],
            adjustment=row["adjustment_status"],
            revision_seq=int(row["revision_seq"]),
            content_hash=digest,
        ),
        "content_hash": digest,
        "security_id": row["security_id"],
        "mic": row["mic"],
        "interval": row["interval"],
        "session": row["ts_utc"],
        "session_date": str(row["ts_utc"])[:10],
        "source_id": row["source_id"],
        "source_name": source_name,
        "dataset": dataset,
        "licence": licence,
        "redistribution": redistribution,
        "adjustment": row["adjustment_status"],
        "revision_seq": int(row["revision_seq"]),
        "supersedes_seq": row["supersedes_bar"],
        "currency": row["currency"],
        "close": close,
        "observed_at": row["observed_at"],
        "ingested_at": row["ingested_at"],
    }


def pin_from_row(
    row: Mapping[str, Any],
    *,
    source_name: str | None = None,
    dataset: str | None = None,
    licence: str | None = None,
    redistribution: str | None = None,
    embed_value: bool = False,
) -> dict[str, Any]:
    """Return a replayable pin for a stored observation.

    ``embed_value`` defaults to ``False``: a pin carries the lawful reference (identity,
    revision, retrieval metadata) rather than the price value, so a saved research object
    does not smuggle restricted vendor observations into a portable artefact.
    """
    observation = observation_from_row(
        row,
        source_name=source_name,
        dataset=dataset,
        licence=licence,
        redistribution=redistribution,
    )
    pin = {
        "schema": PIN_SCHEMA,
        "observation_id": observation["observation_id"],
        "content_hash": observation["content_hash"],
        "security_id": observation["security_id"],
        "mic": observation["mic"],
        "interval": observation["interval"],
        "session": observation["session"],
        "session_date": observation["session_date"],
        "source_id": observation["source_id"],
        "source_name": observation["source_name"],
        "dataset": observation["dataset"],
        "licence": observation["licence"],
        "redistribution": observation["redistribution"],
        "adjustment": observation["adjustment"],
        "revision_seq": observation["revision_seq"],
        "supersedes_seq": observation["supersedes_seq"],
        "value_embedded": bool(embed_value),
        "retrieval": {
            "observed_at": observation["observed_at"],
            "ingested_at": observation["ingested_at"],
            "retrieval_basis": "provider_observation",
        },
    }
    if embed_value:
        pin["close"] = observation["close"]
        pin["currency"] = observation["currency"]
    return pin


def resolve_pinned(db: Database, pin: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a pin to its exact revision, or report why it cannot be replayed.

    A pin is only satisfied by the *same* revision of the *same* source. If the revision
    is absent, the caller must reconnect to the permitted dataset; the latest revision is
    never substituted.
    """
    if not isinstance(pin, Mapping) or pin.get("schema") != PIN_SCHEMA:
        return {
            "schema": "atlas.market_observation.replay.v1",
            "status": PIN_STATUS_INVALID,
            "exact_replay": False,
            "reason": f"a market observation pin must declare schema {PIN_SCHEMA}",
            "observation": None,
            "price": None,
        }
    required = (
        "observation_id", "content_hash", "security_id", "mic", "interval", "session",
        "source_id", "revision_seq", "adjustment",
    )
    missing = [field for field in required if pin.get(field) in (None, "")]
    if missing:
        return {
            "schema": "atlas.market_observation.replay.v1",
            "status": PIN_STATUS_INVALID,
            "exact_replay": False,
            "reason": "pin is missing identity fields",
            "missing": missing,
            "observation": None,
            "price": None,
        }
    row = db.query_one(
        "SELECT b.*, s.name AS source_name FROM bar b LEFT JOIN source s ON s.source_id = b.source_id "
        "WHERE b.security_id = ? AND b.mic = ? AND b.interval = ? AND b.ts_utc = ? "
        "AND b.source_id = ? AND b.revision_seq = ?",
        (
            pin["security_id"], str(pin["mic"]).upper(), pin["interval"], pin["session"],
            pin["source_id"], int(pin["revision_seq"]),
        ),
    )
    if row is None:
        return {
            "schema": "atlas.market_observation.replay.v1",
            "status": PIN_STATUS_MISSING,
            "exact_replay": False,
            "reason": (
                "The pinned revision is not stored in this database. Atlas will not "
                "substitute a later revision or the latest price; reconnect the permitted "
                "source or re-derive the analysis from a new, explicitly chosen observation."
            ),
            "pin": dict(pin),
            "observation": None,
            "price": None,
        }
    observation = observation_from_row(row, source_name=row["source_name"])
    if observation["observation_id"] != pin["observation_id"] or observation["content_hash"] != pin["content_hash"]:
        return {
            "schema": "atlas.market_observation.replay.v1",
            "status": PIN_STATUS_CONTENT_MISMATCH,
            "exact_replay": False,
            "reason": (
                "A row exists at the pinned revision but its content no longer matches the "
                "pinned identity, so exact replay is refused."
            ),
            "pin": dict(pin),
            "observation": observation,
            "price": None,
        }
    if str(observation["adjustment"]) != str(pin["adjustment"]):
        return {
            "schema": "atlas.market_observation.replay.v1",
            "status": PIN_STATUS_CONTENT_MISMATCH,
            "exact_replay": False,
            "reason": "The pinned adjustment convention differs from the stored observation.",
            "pin": dict(pin),
            "observation": observation,
            "price": None,
        }
    return {
        "schema": "atlas.market_observation.replay.v1",
        "status": PIN_STATUS_EXACT,
        "exact_replay": True,
        "reason": "Exact pinned revision resolved from the stored observation.",
        "pin": dict(pin),
        "observation": observation,
        "price": {
            "date": observation["session_date"],
            "close": float(observation["close"]),
            "currency": observation["currency"],
            "mic": observation["mic"],
            "adjustment_semantics": observation["adjustment"],
            "source_id": observation["source_id"],
            "revision_seq": observation["revision_seq"],
            "observed_at": observation["observed_at"],
            "ingested_at": observation["ingested_at"],
        },
    }
