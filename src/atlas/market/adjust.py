"""Derived price views: split adjustment and total return.

Conventions (documented because they are choices, not facts):

**Split adjustment.**
A split with ratio ``to/from`` (4-for-1 -> 4) multiplies the share count by that
factor on its ex-date. Prices before the ex-date are therefore divided by the
cumulative factor of all splits whose ex-date is *after* the bar, and volumes are
multiplied by it. The most recent bar is unchanged, so the adjusted series and the
raw series agree on the reference date.

**Total return.**
Atlas produces a *total return index* (base 1.0 at the first bar), not an
"adjusted price". A dividend with amount ``d`` on ex-date ``t`` is reinvested at that
session's close:

    TR[t] = TR[t-1] * (adj_close[t] + d_adj[t]) / adj_close[t-1]

where ``adj_close`` is the split-adjusted close and ``d_adj`` is the dividend divided
by the split factor applicable on its ex-date (so both are in reference-date units).
Labelling a dividend-adjusted number a "price" invites the exact mistake this
codebase forbids: presenting unadjusted or partially adjusted values as total return.

**Never twice.**
Only bars with ``adjustment_status = 'raw'`` may be adjusted. Asking to adjust an
already-adjusted series raises instead of silently compounding factors.

**What was known.**
Adjustments can be restricted to actions with ``availability_time <= knowledge_as_of``.
Actions withheld by that filter are reported, so a backtest cannot quietly use a
split announced after its decision date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ..core.errors import UnsupportedActionError, ValidationError
from ..core.temporal import iso_date
from ..core.units import canonical_decimal, parse_decimal
from .actions import ActionType, CorporateAction, SPLIT_TYPES
from .bars import ADJUSTMENT_RAW, Bar

MODE_SPLIT = "split"
MODE_TOTAL_RETURN = "total_return"


@dataclass(slots=True)
class AdjustedBar:
    session_date: str
    ts_utc: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    split_factor: Decimal
    dividend: Decimal
    source_revision_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date,
            "ts_utc": self.ts_utc,
            "open": canonical_decimal(self.open),
            "high": canonical_decimal(self.high),
            "low": canonical_decimal(self.low),
            "close": canonical_decimal(self.close),
            "volume": canonical_decimal(self.volume) if self.volume is not None else None,
            "split_factor": canonical_decimal(self.split_factor),
            "dividend": canonical_decimal(self.dividend),
            "revision_seq": self.source_revision_seq,
        }


@dataclass(slots=True)
class AdjustedSeries:
    security_id: str
    mic: str
    mode: str
    reference_date: str
    knowledge_as_of: str | None
    bars: list[AdjustedBar] = field(default_factory=list)
    total_return_index: list[tuple[str, str]] = field(default_factory=list)
    actions_applied: list[dict[str, Any]] = field(default_factory=list)
    actions_withheld: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def adjustment_status(self) -> str:
        return "split_adjusted" if self.mode == MODE_SPLIT else "total_return_adjusted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "mic": self.mic,
            "mode": self.mode,
            "adjustment_status": self.adjustment_status,
            "reference_date": self.reference_date,
            "knowledge_as_of": self.knowledge_as_of,
            "bars": [bar.to_dict() for bar in self.bars],
            "total_return_index": [{"session_date": d, "index": v} for d, v in self.total_return_index],
            "actions_applied": self.actions_applied,
            "actions_withheld": self.actions_withheld,
            "warnings": self.warnings,
            "count": len(self.bars),
        }


def _split_actions(actions: Iterable[CorporateAction]) -> list[CorporateAction]:
    return [a for a in actions if a.action_type in SPLIT_TYPES]


def _dividend_actions(actions: Iterable[CorporateAction]) -> list[CorporateAction]:
    return [a for a in actions if a.action_type == ActionType.CASH_DIVIDEND.value]


def _reject_non_computable(actions: Iterable[CorporateAction]) -> None:
    for action in actions:
        if action.action_type in {
            ActionType.MERGER.value,
            ActionType.SPIN_OFF.value,
            ActionType.DISTRIBUTION.value,
        }:
            raise UnsupportedActionError(
                "Atlas does not compute adjustments for this action type in Phase 1",
                action_type=action.action_type,
                action_id=action.action_id,
            )


def _ensure_raw(bars: Sequence[Bar]) -> None:
    for bar in bars:
        if bar.adjustment_status != ADJUSTMENT_RAW:
            raise ValidationError(
                "refusing to adjust a non-raw series (adjustments must never be applied twice)",
                adjustment_status=bar.adjustment_status,
                ts_utc=bar.ts_utc,
            )


def split_factor_for(session_date: str, splits: Sequence[CorporateAction]) -> Decimal:
    """Cumulative factor of every split with an ex-date strictly after the bar."""
    factor = Decimal(1)
    for action in splits:
        if action.ex_date and action.ex_date > session_date:
            factor *= action.split_factor
    return factor


def split_adjust(
    bars: Sequence[Bar],
    actions: Sequence[CorporateAction],
    *,
    knowledge_as_of: str | None = None,
    reference_date: str | None = None,
    include_dividends: bool = True,
) -> AdjustedSeries:
    """Split-adjust a raw series, optionally with a total-return index attached."""
    _ensure_raw(bars)
    if not bars:
        raise ValidationError("cannot adjust an empty series")

    ordered = sorted(bars, key=lambda b: b.ts_utc)
    reference = iso_date(reference_date) if reference_date else ordered[-1].session_date
    splits = _split_actions(actions)
    dividends = _dividend_actions(actions) if include_dividends else []
    _reject_non_computable(actions)

    if knowledge_as_of:
        cutoff = iso_date(knowledge_as_of)
        withheld = [
            a.to_dict() for a in list(splits) + list(dividends)
            if a.availability_time is None or iso_date(a.availability_time) > cutoff
        ]
        splits = [a for a in splits if a.availability_time and iso_date(a.availability_time) <= cutoff]
        dividends = [a for a in dividends if a.availability_time and iso_date(a.availability_time) <= cutoff]
    else:
        withheld = []

    applied_splits = [a for a in splits if a.ex_date and a.ex_date <= reference]
    applied_dividends = [a for a in dividends if a.ex_date and a.ex_date <= reference]

    warnings: list[str] = []
    if reference < ordered[-1].session_date:
        warnings.append(
            f"reference date {reference} precedes the last bar {ordered[-1].session_date}; "
            "later bars still appear in the series but factors ignore splits after the reference"
        )

    adjusted: list[AdjustedBar] = []
    for bar in ordered:
        factor = split_factor_for(bar.session_date, applied_splits)
        dividend = Decimal(0)
        for action in applied_dividends:
            if action.ex_date == bar.session_date and action.cash_amount is not None:
                dividend += parse_decimal(action.cash_amount) / factor
        adjusted.append(
            AdjustedBar(
                session_date=bar.session_date,
                ts_utc=bar.ts_utc,
                open=bar.open / factor,
                high=bar.high / factor,
                low=bar.low / factor,
                close=bar.close / factor,
                volume=(bar.volume * factor) if bar.volume is not None else None,
                split_factor=factor,
                dividend=dividend,
                source_revision_seq=bar.revision_seq,
            )
        )

    series = AdjustedSeries(
        security_id=ordered[0].security_id,
        mic=ordered[0].mic,
        mode=MODE_SPLIT,
        reference_date=reference,
        knowledge_as_of=iso_date(knowledge_as_of) if knowledge_as_of else None,
        bars=adjusted,
        actions_applied=[a.to_dict() for a in applied_splits + applied_dividends],
        actions_withheld=withheld,
        warnings=warnings,
    )
    return series


def total_return(
    bars: Sequence[Bar],
    actions: Sequence[CorporateAction],
    *,
    knowledge_as_of: str | None = None,
    reference_date: str | None = None,
) -> AdjustedSeries:
    """Split-adjusted series plus a dividend-reinvested total return index."""
    series = split_adjust(
        bars,
        actions,
        knowledge_as_of=knowledge_as_of,
        reference_date=reference_date,
        include_dividends=True,
    )
    index: list[tuple[str, str]] = []
    level = Decimal(1)
    previous: AdjustedBar | None = None
    for bar in series.bars:
        if previous is None:
            index.append((bar.session_date, canonical_decimal(level)))
            if bar.dividend != 0:
                series.warnings.append(
                    f"dividend on the first bar ({bar.session_date}) cannot be reinvested and is excluded from the index"
                )
            previous = bar
            continue
        if previous.close == 0:
            series.warnings.append(f"zero close on {previous.session_date}; total return carries forward unchanged")
            index.append((bar.session_date, canonical_decimal(level)))
            previous = bar
            continue
        growth = (bar.close + bar.dividend) / previous.close
        level *= growth
        index.append((bar.session_date, canonical_decimal(level)))
        previous = bar
    series.mode = MODE_TOTAL_RETURN
    series.total_return_index = index
    return series


def verify_split_continuity(
    raw: Sequence[Bar], adjusted: AdjustedSeries
) -> list[str]:
    """Sanity-check a split adjustment against the raw series.

    Returns a list of human-readable discrepancies (empty when the adjustment is
    coherent): the reference-date bar must be unchanged and every pre-split close
    must equal ``raw_close / cumulative_factor``.
    """
    discrepancies: list[str] = []
    raw_by_date = {bar.session_date: bar for bar in raw}
    for bar in adjusted.bars:
        original = raw_by_date.get(bar.session_date)
        if original is None:
            discrepancies.append(f"adjusted bar {bar.session_date} has no raw counterpart")
            continue
        expected = original.close / bar.split_factor
        if expected != bar.close:
            discrepancies.append(
                f"{bar.session_date}: expected adjusted close {expected}, stored {bar.close}"
            )
        if bar.session_date == adjusted.reference_date and bar.split_factor != 1:
            discrepancies.append(
                f"reference bar {bar.session_date} should have factor 1, found {bar.split_factor}"
            )
    return discrepancies
