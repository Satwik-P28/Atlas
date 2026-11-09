"""The authoritative market-evidence contract.

Before this module, "the price of a security" was decided in several places: the price
module selected one provider with an explicit policy, the terminal read models took the
newest row for a venue regardless of provider, and the issuer metrics took the newest row
again. Each path could return a different observation for the same security and date, and
none of them carried the observation's identity back to the caller. Two accepted defects
in Phase 9.2.4 were consequences of exactly that duplication.

There is now one selection engine and three typed records:

``MarketObservation``
    One provider's statement about one security, one venue, one session and one revision.
    Immutable. It carries the raw OHLCV as ``Decimal`` (canonical decimal text feeds the
    content hash), the adjustment convention, provider/dataset, rights classification and
    the immutable ``observation_id``/``content_hash`` computed by
    :mod:`atlas.research.observations`.

``PriceSelection``
    The *decision* to use one observation, including the policy and its version, the
    information cutoff, the constraints that were applied, the competing observations that
    were rejected, the rationale, and whether exact replay is possible. A selection never
    claims "latest price": it states which session, provider and revision it chose and why.

``MarketComparison``
    A model output compared with a selected observation, with the date gap, currency
    check, source restrictions and uncertainty recorded rather than implied.

Precision is deliberate: values are ``Decimal`` inside the contract and are converted to
JSON numbers only at the existing serialization boundaries, so public response types do
not change. The canonical decimal text used for hashing is unchanged, so persisted
observation ids and saved pins stay valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from ..core.units import canonical_decimal, parse_decimal
from ..storage.db import Database
from ..research.observations import (
    PIN_SCHEMA,
    PIN_STATUS_EXACT,
    observation_from_row,
    resolve_pinned,
)

CONTRACT_VERSION = "atlas.market_evidence.v1"

#: Version of the canonical-selection contract. v2 makes the *basis* of the choice
#: explicit (latest session, latest imported revision, explicit source, or a saved pin),
#: records the observation identity, and never mixes providers inside one series.
SELECTION_POLICY_VERSION = "atlas.market_price.selection.v2"
LEGACY_SELECTION_POLICIES = {"atlas.market_price.selection.v1"}
POLICIES = ("latest_session", "latest_revision", "explicit_source", "pinned")

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

#: ``9999-12-31`` is the sentinel meaning "no information cutoff". It is never reported as
#: a real cutoff date, because a caller must not believe a research run was bounded by it.
NO_CUTOFF = "2999-12-31"

#: Right classes whose bytes may travel inside a portable artefact.
REDISTRIBUTABLE = {"public_domain", "project_authored", "permitted"}

MISSING_NO_OBSERVATION = "no_authorised_observation_at_or_before_cutoff"
MISSING_FILTERED = "no_observation_matching_requested_constraints"


class PolicyError(ValueError):
    """A selection policy is unknown or was given constraints it cannot answer."""


@dataclass(frozen=True, slots=True)
class MarketObservation:
    """One immutable provider observation, with its identity and rights."""

    security_id: str
    mic: str
    interval: str
    session: str
    revision_seq: int
    supersedes_seq: int | None
    currency: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    adjustment: str
    source_id: str
    source_name: str | None
    dataset: str | None
    licence: str | None
    redistribution: str | None
    source_kind: str | None
    observed_at: str | None
    ingested_at: str | None
    observation_id: str
    content_hash: str

    # ------------------------------------------------------------------ derived
    @property
    def session_date(self) -> str:
        return str(self.session)[:10]

    @property
    def close_decimal_text(self) -> str:
        """Canonical decimal text, exactly what the content hash was computed over."""
        return canonical_decimal(self.close)

    @property
    def export_allowed(self) -> bool:
        return (self.redistribution or "") in REDISTRIBUTABLE

    @property
    def rights_class(self) -> str:
        return self.redistribution or "unknown"

    def identity(self) -> dict[str, Any]:
        """The lawful reference to this observation, without its value."""
        return {
            "observation_id": self.observation_id,
            "content_hash": self.content_hash,
            "security_id": self.security_id,
            "mic": self.mic,
            "interval": self.interval,
            "session": self.session,
            "source_id": self.source_id,
            "revision_seq": self.revision_seq,
            "adjustment": self.adjustment,
            "currency": self.currency,
            "rights": self.rights_class,
        }

    def to_pin(self) -> dict[str, Any]:
        """A replayable reference to this revision, without embedding its value."""
        return {
            "schema": PIN_SCHEMA,
            "observation_id": self.observation_id,
            "content_hash": self.content_hash,
            "security_id": self.security_id,
            "mic": self.mic,
            "interval": self.interval,
            "session": self.session,
            "session_date": self.session_date,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "dataset": self.dataset,
            "licence": self.licence,
            "redistribution": self.redistribution,
            "adjustment": self.adjustment,
            "revision_seq": self.revision_seq,
            "supersedes_seq": self.supersedes_seq,
            "value_embedded": False,
            "retrieval": {
                "observed_at": self.observed_at,
                "ingested_at": self.ingested_at,
                "retrieval_basis": "provider_observation",
            },
        }

    def to_dict(self) -> dict[str, Any]:
        payload = observation_from_row(
            {
                "security_id": self.security_id,
                "mic": self.mic,
                "interval": self.interval,
                "ts_utc": self.session,
                "revision_seq": self.revision_seq,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "volume": self.volume,
                "currency": self.currency,
                "adjustment_status": self.adjustment,
                "source_id": self.source_id,
                "observed_at": self.observed_at,
                "ingested_at": self.ingested_at,
                "supersedes_bar": self.supersedes_seq,
            },
            source_name=self.source_name,
            dataset=self.dataset,
            licence=self.licence,
            redistribution=self.redistribution,
        )
        payload["source_kind"] = self.source_kind
        payload["export_allowed"] = self.export_allowed
        return payload

    @classmethod
    def from_row(cls, row: Any, **metadata: Any) -> "MarketObservation":
        observation = observation_from_row(
            row,
            source_name=metadata.get("source_name"),
            dataset=metadata.get("dataset"),
            licence=metadata.get("licence"),
            redistribution=metadata.get("redistribution"),
        )
        return cls(
            security_id=row["security_id"],
            mic=str(row["mic"]).upper(),
            interval=row["interval"],
            session=row["ts_utc"],
            revision_seq=int(row["revision_seq"]),
            supersedes_seq=row["supersedes_bar"],
            currency=row["currency"],
            open=parse_decimal(row["open"]),
            high=parse_decimal(row["high"]),
            low=parse_decimal(row["low"]),
            close=parse_decimal(row["close"]),
            volume=parse_decimal(row["volume"]) if row["volume"] is not None else None,
            adjustment=row["adjustment_status"],
            source_id=row["source_id"],
            source_name=metadata.get("source_name"),
            dataset=metadata.get("dataset"),
            licence=metadata.get("licence"),
            redistribution=metadata.get("redistribution"),
            source_kind=metadata.get("source_kind"),
            observed_at=row["observed_at"],
            ingested_at=row["ingested_at"],
            observation_id=observation["observation_id"],
            content_hash=observation["content_hash"],
        )


@dataclass(frozen=True, slots=True)
class PriceSelection:
    """The recorded decision to use (or not use) one market observation."""

    policy: str
    requested_policy: str
    label: str
    information_cutoff: str | None
    observation: MarketObservation | None
    alternatives: tuple[Mapping[str, Any], ...] = ()
    requested_source_id: str | None = None
    rationale: str = ""
    missing_status: str | None = None
    pinned: bool = False
    exact_replay: bool | None = None
    conflict: bool = False
    selection_status: str | None = None
    reason: str | None = None
    requested_mic: str | None = None
    legacy_dimensions: Mapping[str, str] | None = None
    legacy_conflict_resolution: str = ""
    legacy_provider_consistency: str = "single_provider"

    # ------------------------------------------------------------------ derived
    @property
    def security_id(self) -> str | None:
        return self.observation.security_id if self.observation else None

    @property
    def selected_source_id(self) -> str | None:
        return self.observation.source_id if self.observation else None

    @property
    def export_allowed(self) -> bool:
        return bool(self.observation and self.observation.export_allowed)

    @property
    def exact_replay_eligible(self) -> bool:
        """Only an exact stored revision can be replayed; a search result never can."""
        return self.observation is not None and self.exact_replay is not False

    def identity(self) -> dict[str, Any] | None:
        return self.observation.identity() if self.observation else None

    def to_legacy(self) -> dict[str, Any]:
        """Serialise exactly as the v2 selection contract always has.

        Consumers and API clients depend on this shape; the typed fields above are the
        authority and this method is the only translation point.
        """
        observation = self.observation.to_dict() if self.observation else None
        if self.pinned:
            payload: dict[str, Any] = {
                "policy": SELECTION_POLICY_VERSION,
                "requested_policy": "pinned",
                "policy_label": POLICY_LABELS["pinned"],
            }
            if self.observation is not None:
                payload["requested_source_id"] = self.observation.source_id
            payload.update(
                {
                    "selected_source_id": self.selected_source_id,
                    "price_date": self.observation.session_date if self.observation else None,
                    "revision_seq": self.observation.revision_seq if self.observation else None,
                    "observation_id": self.observation.observation_id if self.observation else None,
                    "content_hash": self.observation.content_hash if self.observation else None,
                    "observation": observation,
                    "pinned": True,
                    "exact_replay": bool(self.exact_replay),
                }
            )
            if self.exact_replay:
                payload["selection_status"] = PIN_STATUS_EXACT
                payload["conflict_resolution"] = "saved_observation_pin"
                payload["dimensions"] = dict(self.legacy_dimensions or {})
                payload["alternatives"] = [dict(item) for item in self.alternatives]
                payload["conflict"] = self.conflict
                payload["provider_consistency"] = self.legacy_provider_consistency
            else:
                payload["selection_status"] = self.selection_status
                payload["reason"] = self.reason
                payload["conflict_resolution"] = self.legacy_conflict_resolution
                payload["alternatives"] = []
                payload["conflict"] = self.conflict
            return payload
        return {
            "policy": SELECTION_POLICY_VERSION,
            "requested_policy": self.requested_policy,
            "policy_label": self.label,
            "requested_source_id": self.requested_source_id,
            "selected_source_id": self.selected_source_id,
            "price_date": self.observation.session_date if self.observation else None,
            "session": self.observation.session if self.observation else None,
            "ingested_at": self.observation.ingested_at if self.observation else None,
            "revision_seq": self.observation.revision_seq if self.observation else None,
            "observation_id": self.observation.observation_id if self.observation else None,
            "content_hash": self.observation.content_hash if self.observation else None,
            "observation": observation,
            "pinned": False,
            "exact_replay": None,
            "information_cutoff": self.information_cutoff,
            "dimensions": dict(self.legacy_dimensions or {}),
            "conflict_resolution": self.legacy_conflict_resolution,
            "alternatives": [dict(item) for item in self.alternatives],
            "conflict": self.conflict,
            "provider_consistency": self.legacy_provider_consistency,
        }


@dataclass(frozen=True, slots=True)
class MarketComparison:
    """A model output against one selected observation, with every caveat explicit."""

    status: str
    selection: PriceSelection | None
    model_value_per_share: float | None
    accounting_period_end: str | None
    information_cutoff: str | None
    currency: str | None
    valuation_date: str | None
    model_version: str | None
    mixed_date: bool
    date_gap_days: int
    lookahead_safe: bool
    implied: Mapping[str, Any]
    uncertainty: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def price_close(self) -> Decimal | None:
        return self.selection.observation.close if self.selection and self.selection.observation else None


def normalize_policy(
    policy: str,
    *,
    source_id: str | None,
    has_pin: bool,
) -> str:
    """Resolve a requested policy name without inventing a basis for the choice."""
    if policy in LEGACY_SELECTION_POLICIES:
        policy = "latest_session"
    if policy == SELECTION_POLICY_VERSION:
        policy = "explicit_source" if source_id else "latest_session"
    if policy not in POLICIES:
        raise PolicyError(f"unknown market-price selection policy {policy!r}")
    if policy == "explicit_source" and not source_id:
        raise PolicyError("the explicit_source policy requires a source_id")
    if policy == "pinned" and not has_pin:
        raise PolicyError("the pinned policy requires a stored observation pin")
    return policy


def _row_observation(row: Any) -> MarketObservation:
    return MarketObservation.from_row(
        row,
        source_name=row["name"],
        dataset=row["name"],
        licence=row["licence"],
        redistribution=row["redistribution"],
        source_kind=row["source_kind"] if "source_kind" in row.keys() else None,
    )


def _pinned(
    db: Database,
    security_id: str,
    pin: Mapping[str, Any],
    *,
    mic: str | None,
) -> PriceSelection:
    """Resolve a saved pin to its exact revision, never to the latest price."""
    replay = resolve_pinned(db, pin)
    if replay["status"] != PIN_STATUS_EXACT or replay["observation"] is None:
        return PriceSelection(
            policy=SELECTION_POLICY_VERSION,
            requested_policy="pinned",
            label=POLICY_LABELS["pinned"],
            information_cutoff=None,
            observation=None,
            pinned=True,
            exact_replay=False,
            selection_status=replay["status"],
            reason=replay["reason"],
            requested_source_id=pin.get("source_id"),
            requested_mic=mic,
            legacy_conflict_resolution="saved_observation_pin",
        )
    observation = replay["observation"]
    if mic and str(mic).upper() != str(observation["mic"]).upper():
        raise PolicyError(
            f"pinned observation is on {observation['mic']}, not the requested venue {mic.upper()}"
        )
    if observation["security_id"] != security_id:
        raise PolicyError(
            "pinned observation belongs to a different security; refusing to re-use it"
        )
    # The replay payload serialises the close as a JSON number; recover its decimal
    # value from that representation rather than re-reading a float.
    pinned_close = Decimal(str(observation["close"]))
    selected = MarketObservation(
        security_id=observation["security_id"],
        mic=str(observation["mic"]).upper(),
        interval=observation["interval"],
        session=observation["session"],
        revision_seq=int(observation["revision_seq"]),
        supersedes_seq=observation.get("supersedes_seq"),
        currency=observation["currency"],
        open=pinned_close,
        high=pinned_close,
        low=pinned_close,
        close=pinned_close,
        volume=None,
        adjustment=observation["adjustment"],
        source_id=observation["source_id"],
        source_name=pin.get("source_name"),
        dataset=pin.get("dataset"),
        licence=pin.get("licence"),
        redistribution=pin.get("redistribution"),
        source_kind=None,
        observed_at=observation["observed_at"],
        ingested_at=observation["ingested_at"],
        observation_id=observation["observation_id"],
        content_hash=observation["content_hash"],
    )
    return PriceSelection(
        policy=SELECTION_POLICY_VERSION,
        requested_policy="pinned",
        label=POLICY_LABELS["pinned"],
        information_cutoff=None,
        observation=selected,
        alternatives=(),
        requested_source_id=selected.source_id,
        rationale="the exact revision recorded by a saved observation pin",
        pinned=True,
        exact_replay=True,
        conflict=False,
        legacy_dimensions={
            "market_session": "pinned_session",
            "provider": "pinned_provider",
            "revision": "pinned_revision",
            "adjustment": "raw_observation_only",
        },
        legacy_conflict_resolution="saved_observation_pin",
    )


_ORDERING = {
    "latest_session": "b.ts_utc DESC, b.revision_seq DESC, b.source_id ASC, b.mic ASC",
    "latest_revision": "b.ingested_at DESC, b.ts_utc DESC, b.revision_seq DESC, b.source_id ASC",
    "explicit_source": "b.ts_utc DESC, b.revision_seq DESC, b.mic ASC",
}

_LATEST_REVISION_SQL = (
    "b.revision_seq=(SELECT MAX(b2.revision_seq) FROM bar b2 WHERE "
    "b2.security_id=b.security_id AND b2.mic=b.mic AND b2.interval=b.interval "
    "AND b2.ts_utc=b.ts_utc AND b2.source_id=b.source_id)"
)


def select_price(
    db: Database,
    security_id: str,
    date_text: str,
    *,
    source_id: str | None = None,
    mic: str | None = None,
    policy: str = SELECTION_POLICY_VERSION,
    pin: Mapping[str, Any] | None = None,
) -> PriceSelection:
    """Select one observation under a stated policy — the only selection path."""
    resolved = normalize_policy(policy, source_id=source_id, has_pin=pin is not None)
    if resolved == "pinned":
        assert pin is not None
        return _pinned(db, security_id, pin, mic=mic)
    where = [
        "b.security_id=?",
        "b.interval='1d'",
        "substr(b.ts_utc,1,10)<=?",
        _LATEST_REVISION_SQL,
    ]
    params: list[Any] = [security_id, str(date_text)[:10]]
    if source_id:
        where.append("b.source_id=?")
        params.append(source_id)
    if mic:
        where.append("b.mic=?")
        params.append(mic.upper())
    row = db.query_one(
        "SELECT b.*, s.name, s.licence, s.redistribution, s.kind AS source_kind FROM bar b "
        "LEFT JOIN source s ON s.source_id=b.source_id WHERE "
        + " AND ".join(where)
        + f" ORDER BY {_ORDERING[resolved]} LIMIT 1",
        params,
    )
    cutoff = str(date_text)[:10]
    observation = _row_observation(row) if row is not None else None
    alternatives: tuple[dict[str, Any], ...] = ()
    conflict = False
    if row is not None:
        alternatives = tuple(
            {
                "source_id": alt["source_id"],
                "mic": alt["mic"],
                "close": float(alt["close"]),
                "ingested_at": alt["ingested_at"],
                "revision_seq": alt["revision_seq"],
            }
            for alt in db.query(
                "SELECT b.source_id, b.mic, b.close, b.ingested_at, b.revision_seq FROM bar b "
                "WHERE b.security_id=? AND b.interval='1d' AND b.ts_utc=? AND "
                + _LATEST_REVISION_SQL
                + " ORDER BY b.source_id, b.mic",
                (security_id, row["ts_utc"]),
            )
            if alt["source_id"] != row["source_id"] or alt["mic"] != row["mic"]
        )
        closes = {round(float(row["close"]), 10)} | {round(item["close"], 10) for item in alternatives}
        conflict = len(closes) > 1
    missing = None if observation is not None else (
        MISSING_FILTERED if (source_id or mic) else MISSING_NO_OBSERVATION
    )
    return PriceSelection(
        policy=SELECTION_POLICY_VERSION,
        requested_policy=resolved,
        label=POLICY_LABELS[resolved],
        information_cutoff=None if cutoff >= NO_CUTOFF else cutoff,
        observation=observation,
        alternatives=alternatives,
        requested_source_id=source_id,
        requested_mic=mic.upper() if mic else None,
        rationale=(
            POLICY_LABELS[resolved] if observation is not None else
            "no stored observation satisfies the requested policy and constraints"
        ),
        missing_status=missing,
        pinned=False,
        exact_replay=None,
        conflict=conflict,
        legacy_dimensions={
            "market_session": (
                "explicitly_requested_source_latest_session" if source_id else
                "latest_session_at_or_before_cutoff"
            ),
            "provider": (
                "explicit_source" if source_id else
                "single_provider_selected_then_held_constant"
            ),
            "revision": (
                "latest_ingested_revision" if resolved == "latest_revision"
                else "latest_revision_of_selected_session"
            ),
            "adjustment": "raw_observation_only",
        },
        legacy_conflict_resolution=(
            "explicit_source_filter" if source_id else
            "latest_session_then_latest_revision_then_source_id"
        ),
    )


def latest_observation(
    db: Database,
    security_id: str,
    *,
    mic: str | None = None,
    source_id: str | None = None,
    as_of: str | None = None,
) -> PriceSelection:
    """The most recent observation at or before ``as_of`` under ``latest_session``."""
    return select_price(
        db, security_id, as_of or NO_CUTOFF, source_id=source_id, mic=mic,
    )


def compare_model_to_market(
    *,
    selection: PriceSelection | None,
    value_per_share: float | None,
    accounting_period_end: str | None,
    information_cutoff: str | None,
    model_version: str | None = None,
    implied: Mapping[str, Any] | None = None,
) -> MarketComparison:
    """Compare a model value with a selected observation, refusing look-ahead.

    The comparison never reaches for a different observation when the selected one is
    unusable: an unavailable price stays unavailable and the reason is reported.
    """
    cutoff = str(information_cutoff or "")[:10] or None
    if selection is None or selection.observation is None:
        return MarketComparison(
            status="unavailable",
            selection=selection,
            model_value_per_share=value_per_share,
            accounting_period_end=None,
            information_cutoff=cutoff,
            currency=None,
            valuation_date=None,
            model_version=model_version,
            mixed_date=False,
            date_gap_days=0,
            lookahead_safe=True,
            implied={},
            reason="No observed price exists on or before the comparison date.",
        )
    observation = selection.observation
    price_date = observation.session_date
    if cutoff and price_date > cutoff:
        return MarketComparison(
            status="rejected_lookahead",
            selection=selection,
            model_value_per_share=value_per_share,
            accounting_period_end=None,
            information_cutoff=cutoff,
            currency=observation.currency,
            valuation_date=price_date,
            model_version=model_version,
            mixed_date=False,
            date_gap_days=0,
            lookahead_safe=False,
            implied=dict(implied or {}),
            reason=(
                f"The selected price {price_date} is after the research information cutoff {cutoff}. "
                "Atlas refuses to compare a model with a future price unless the caller labels it "
                "as a hypothetical."
            ),
        )
    accounting = str(accounting_period_end or "")[:10]
    mixed = bool(accounting and accounting != price_date)
    uncertainty: list[str] = []
    if mixed:
        uncertainty.append(
            "The price date differs from the accounting period end. This is a mixed-date "
            "comparison, not a point-in-time valuation."
        )
    if not observation.export_allowed:
        uncertainty.append(
            "The observation is not redistributable; derived metrics may be exported but its "
            "value and provider reference may not."
        )
    return MarketComparison(
        status="available",
        selection=selection,
        model_value_per_share=value_per_share,
        accounting_period_end=accounting or None,
        information_cutoff=cutoff,
        currency=observation.currency,
        valuation_date=price_date,
        model_version=model_version,
        mixed_date=mixed,
        date_gap_days=(
            (datetime.fromisoformat(price_date) - datetime.fromisoformat(accounting)).days
            if mixed else 0
        ),
        lookahead_safe=True,
        implied=dict(implied or {}),
        uncertainty=tuple(uncertainty),
    )


__all__ = [
    "CONTRACT_VERSION",
    "SELECTION_POLICY_VERSION",
    "POLICIES",
    "POLICY_LABELS",
    "NO_CUTOFF",
    "MarketObservation",
    "PriceSelection",
    "MarketComparison",
    "PolicyError",
    "select_price",
    "latest_observation",
    "compare_model_to_market",
    "normalize_policy",
]
