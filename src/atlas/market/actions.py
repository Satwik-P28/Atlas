"""Corporate actions.

Phase 1 implements the subset it can compute correctly and tests exhaustively:

* ``split`` / ``reverse_split`` - share-count changes with an exact ratio.
* ``cash_dividend`` - a cash amount per share with an ex-date.
* ``ticker_change`` - an identity event recorded alongside the master-data change.

``merger``, ``spin_off`` and ``distribution`` are declared in the type system and the
schema so callers can record that an event happened, but Atlas does **not** pretend
to know their economics: :data:`COMPUTABLE_ACTION_TYPES` excludes them and the
adjustment engine refuses them with :class:`UnsupportedActionError`.

Every action carries its own public-availability record, because adjusting a
historical series with an action announced later is itself a look-ahead error.
Corrections are append-only: a corrected action is a new row whose ``supersedes``
points at the row it replaces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Sequence

from ..core.errors import UnsupportedActionError, ValidationError
from ..core.ids import action_id as make_action_id
from ..core.temporal import Availability, iso, iso_date, utcnow
from ..core.units import canonical_decimal, parse_decimal
from ..storage.db import Database


class ActionType(str, Enum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    CASH_DIVIDEND = "cash_dividend"
    TICKER_CHANGE = "ticker_change"
    MERGER = "merger"
    SPIN_OFF = "spin_off"
    DISTRIBUTION = "distribution"


#: Action types whose quantitative effect Atlas can compute and test.
COMPUTABLE_ACTION_TYPES = frozenset(
    {ActionType.SPLIT.value, ActionType.REVERSE_SPLIT.value, ActionType.CASH_DIVIDEND.value}
)

SPLIT_TYPES = frozenset({ActionType.SPLIT.value, ActionType.REVERSE_SPLIT.value})

STATUS_ANNOUNCED = "announced"
STATUS_CONFIRMED = "confirmed"
STATUS_CORRECTED = "corrected"
STATUS_CANCELLED = "cancelled"
STATUS_PROVISIONAL = "provisional"

_VALID_STATUS = {STATUS_ANNOUNCED, STATUS_CONFIRMED, STATUS_CORRECTED, STATUS_CANCELLED, STATUS_PROVISIONAL}


@dataclass(slots=True)
class CorporateAction:
    security_id: str
    action_type: str
    source_id: str
    ex_date: str | None = None
    effective_date: str | None = None
    record_date: str | None = None
    payable_date: str | None = None
    ratio_from: Decimal | None = None
    ratio_to: Decimal | None = None
    cash_amount: Decimal | None = None
    currency: str | None = None
    terms: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_CONFIRMED
    confidence: float = 1.0
    notes: str | None = None
    observed_at: str | None = None
    action_id: str | None = None
    availability_time: str | None = None
    availability_precision: str | None = None
    availability_basis: str | None = None
    supersedes: str | None = None
    evidence_id: str | None = None

    def validate(self) -> None:
        if self.action_type not in {t.value for t in ActionType}:
            raise ValidationError("unknown corporate action type", action_type=self.action_type)
        if self.status not in _VALID_STATUS:
            raise ValidationError("invalid corporate action status", status=self.status)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValidationError("confidence must be within [0, 1]", confidence=self.confidence)
        if self.action_type in SPLIT_TYPES:
            if self.ex_date is None:
                raise ValidationError("splits require an ex-date", action_type=self.action_type)
            if not self.ratio_from or not self.ratio_to:
                raise ValidationError("splits require ratio_from and ratio_to", action_type=self.action_type)
            if self.ratio_from <= 0 or self.ratio_to <= 0:
                raise ValidationError("split ratios must be positive", ratio_from=str(self.ratio_from))
            if self.action_type == ActionType.SPLIT.value and self.ratio_to <= self.ratio_from:
                raise ValidationError(
                    "a forward split must increase the share count (ratio_to > ratio_from); "
                    "use reverse_split otherwise",
                    ratio_from=str(self.ratio_from),
                    ratio_to=str(self.ratio_to),
                )
            if self.action_type == ActionType.REVERSE_SPLIT.value and self.ratio_to >= self.ratio_from:
                raise ValidationError(
                    "a reverse split must reduce the share count (ratio_to < ratio_from)",
                    ratio_from=str(self.ratio_from),
                    ratio_to=str(self.ratio_to),
                )
        elif self.action_type == ActionType.CASH_DIVIDEND.value:
            if self.ex_date is None:
                raise ValidationError("cash dividends require an ex-date")
            if self.cash_amount is None or self.cash_amount < 0:
                raise ValidationError("cash dividends require a non-negative cash amount")
            if not self.currency or len(self.currency) != 3:
                raise ValidationError("cash dividends require a currency")
        elif self.action_type == ActionType.TICKER_CHANGE.value:
            if not self.terms.get("new_ticker"):
                raise ValidationError("ticker changes require terms.new_ticker")
            if self.effective_date is None and self.ex_date is None:
                raise ValidationError("ticker changes require an effective date")

    @property
    def split_factor(self) -> Decimal:
        """Multiplier converting a *pre-action* share count into post-action units."""
        if self.action_type not in SPLIT_TYPES or not self.ratio_from or not self.ratio_to:
            raise UnsupportedActionError(
                "split_factor is only defined for split actions", action_type=self.action_type
            )
        return parse_decimal(self.ratio_to) / parse_decimal(self.ratio_from)

    def terms_key(self) -> str:
        payload = {
            "type": self.action_type,
            "ratio_from": canonical_decimal(self.ratio_from) if self.ratio_from is not None else None,
            "ratio_to": canonical_decimal(self.ratio_to) if self.ratio_to is not None else None,
            "cash": canonical_decimal(self.cash_amount) if self.cash_amount is not None else None,
            "currency": self.currency,
            "terms": self.terms,
        }
        return json.dumps(payload, sort_keys=True, default=str)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "security_id": self.security_id,
            "action_type": self.action_type,
            "ex_date": self.ex_date,
            "effective_date": self.effective_date,
            "record_date": self.record_date,
            "payable_date": self.payable_date,
            "ratio_from": canonical_decimal(self.ratio_from) if self.ratio_from is not None else None,
            "ratio_to": canonical_decimal(self.ratio_to) if self.ratio_to is not None else None,
            "cash_amount": canonical_decimal(self.cash_amount) if self.cash_amount is not None else None,
            "currency": self.currency,
            "terms": self.terms,
            "status": self.status,
            "confidence": self.confidence,
            "source_id": self.source_id,
            "evidence_id": self.evidence_id,
            "availability_time": self.availability_time,
            "availability_precision": self.availability_precision,
            "availability_basis": self.availability_basis,
            "observed_at": self.observed_at,
            "supersedes": self.supersedes,
            "notes": self.notes,
            "computable": self.action_type in COMPUTABLE_ACTION_TYPES,
        }

    @classmethod
    def from_row(cls, row: Any) -> "CorporateAction":
        terms = json.loads(row["terms_json"]) if row["terms_json"] else {}
        return cls(
            security_id=row["security_id"],
            action_type=row["action_type"],
            source_id=row["source_id"],
            ex_date=row["ex_date"],
            effective_date=row["effective_date"],
            record_date=row["record_date"],
            payable_date=row["payable_date"],
            ratio_from=parse_decimal(row["ratio_from"]) if row["ratio_from"] is not None else None,
            ratio_to=parse_decimal(row["ratio_to"]) if row["ratio_to"] is not None else None,
            cash_amount=parse_decimal(row["cash_amount"]) if row["cash_amount"] is not None else None,
            currency=row["currency"],
            terms=json.loads(row["terms_json"]) if row["terms_json"] else {},
            status=row["status"],
            confidence=float(row["confidence"]),
            notes=row["notes"],
            observed_at=row["observed_at"],
            action_id=row["action_id"],
            availability_time=row["availability_time"],
            availability_precision=row["availability_precision"],
            supersedes=row["supersedes"],
            evidence_id=row["evidence_id"],
        )


class ActionStore:
    """Persistence for corporate actions with correction chains."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, action: CorporateAction, *, availability: Availability | None = None) -> str:
        action.validate()
        if self.db.query_one("SELECT 1 FROM security WHERE security_id = ?", (action.security_id,)) is None:
            raise ValidationError("unknown security for corporate action", security_id=action.security_id)
        observed = action.observed_at or iso(utcnow())
        identifier = action.action_id or make_action_id(
            action.security_id, action.action_type, action.ex_date or action.effective_date or "", action.terms_key()
        )
        availability_time = availability.iso if availability is not None else action.availability_time
        availability_precision = (
            availability.precision.value if availability is not None else action.availability_precision
        )
        availability_basis = availability.basis if availability is not None else action.availability_basis
        self.db.execute(
            "INSERT INTO corporate_action (action_id, security_id, action_type, ex_date, effective_date, "
            "record_date, payable_date, ratio_from, ratio_to, cash_amount, currency, terms_json, status, "
            "confidence, source_id, evidence_id, availability_time, availability_precision, observed_at, "
            "supersedes, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(action_id) DO UPDATE SET status=excluded.status, confidence=excluded.confidence, "
            "availability_time=excluded.availability_time, availability_precision=excluded.availability_precision, "
            "notes=excluded.notes",
            (
                identifier,
                action.security_id,
                action.action_type,
                iso_date(action.ex_date) if action.ex_date else None,
                iso_date(action.effective_date) if action.effective_date else None,
                iso_date(action.record_date) if action.record_date else None,
                iso_date(action.payable_date) if action.payable_date else None,
                canonical_decimal(action.ratio_from) if action.ratio_from is not None else None,
                canonical_decimal(action.ratio_to) if action.ratio_to is not None else None,
                canonical_decimal(action.cash_amount) if action.cash_amount is not None else None,
                action.currency,
                json.dumps(action.terms, sort_keys=True, default=str) if action.terms else None,
                action.status,
                action.confidence,
                action.source_id,
                action.evidence_id,
                availability_time,
                availability_precision,
                observed,
                action.supersedes,
                action.notes,
            ),
        )
        action.action_id = identifier
        action.observed_at = observed
        action.availability_time = availability_time
        action.availability_precision = availability_precision
        action.availability_basis = availability_basis
        return identifier

    def correct(self, original_id: str, corrected: CorporateAction, *, reason: str) -> str:
        """Append a correcting action; the original row is preserved untouched."""
        original = self.get(original_id)
        if original is None:
            raise ValidationError("cannot correct an unknown action", action_id=original_id)
        corrected.supersedes = original_id
        corrected.status = STATUS_CORRECTED
        with self.db.transaction():
            new_id = self.add(corrected)
            self.db.execute(
                "UPDATE corporate_action SET notes = COALESCE(notes, '') || ? WHERE action_id = ?",
                (f" [corrected by {new_id}: {reason}]", original_id),
            )
        return new_id

    def get(self, action_id: str) -> CorporateAction | None:
        row = self.db.query_one("SELECT * FROM corporate_action WHERE action_id = ?", (action_id,))
        return CorporateAction.from_row(row) if row is not None else None

    def list(
        self,
        security_id: str,
        *,
        knowledge_as_of: str | None = None,
        action_types: Sequence[str] | None = None,
        include_superseded: bool = False,
        computable_only: bool = False,
    ) -> list[CorporateAction]:
        sql = "SELECT * FROM corporate_action WHERE security_id = ?"
        params: list[Any] = [security_id]
        if action_types:
            sql += f" AND action_type IN ({', '.join('?' for _ in action_types)})"
            params.extend(action_types)
        if computable_only:
            sql += f" AND action_type IN ({', '.join('?' for _ in COMPUTABLE_ACTION_TYPES)})"
            params.extend(sorted(COMPUTABLE_ACTION_TYPES))
        if knowledge_as_of:
            sql += " AND availability_time IS NOT NULL AND availability_time <= ?"
            params.append(iso(knowledge_as_of))
        sql += " ORDER BY COALESCE(ex_date, effective_date, '9999-12-31'), action_id"
        actions = [CorporateAction.from_row(row) for row in self.db.query(sql, params)]
        if not include_superseded:
            superseded = {
                row["supersedes"]
                for row in self.db.query(
                    "SELECT supersedes FROM corporate_action WHERE security_id = ? AND supersedes IS NOT NULL",
                    (security_id,),
                )
            }
            actions = [a for a in actions if a.action_id not in superseded]
        return actions

    def suppression_map(self, security_id: str) -> dict[str, str]:
        rows = self.db.query(
            "SELECT action_id, supersedes FROM corporate_action WHERE security_id = ? AND supersedes IS NOT NULL",
            (security_id,),
        )
        return {row["supersedes"]: row["action_id"] for row in rows}

    def coverage(self, security_id: str) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT action_type, COUNT(*) AS n FROM corporate_action WHERE security_id = ? GROUP BY action_type",
            (security_id,),
        )
        by_type = {row["action_type"]: row["n"] for row in rows}
        span = self.db.query_one(
            "SELECT MIN(COALESCE(ex_date, effective_date)) AS first, MAX(COALESCE(ex_date, effective_date)) AS last "
            "FROM corporate_action WHERE security_id = ?",
            (security_id,),
        )
        return {
            "security_id": security_id,
            "actions": sum(by_type.values()),
            "by_type": by_type,
            "first_action": span["first"] if span else None,
            "last_action": span["last"] if span else None,
            "computable_types": sorted(COMPUTABLE_ACTION_TYPES),
            "declared_not_computed": sorted({t.value for t in ActionType} - COMPUTABLE_ACTION_TYPES),
        }
