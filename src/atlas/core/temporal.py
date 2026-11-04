"""Time semantics.

Atlas keeps four distinct notions of time apart, because conflating them is the
single most common source of look-ahead bias in financial research:

===================  ==============================================================
Concept              Meaning
===================  ==============================================================
event / valid time   When the economic fact was true (e.g. a share split became
                     effective, a price was observed).
reporting period     The accounting interval a fact describes (FY2020, Q3 2021).
public availability  When the information became publicly obtainable. Evidenced for
                     SEC filings by ``acceptanceDateTime``; otherwise a documented
                     conservative upper bound, flagged ``date`` precision.
system observation   When Atlas actually ingested the record (``observed_at``).
===================  ==============================================================

A point-in-time query must select on availability (Question A: what could a
researcher have known?) or on observation (Question B: what had Atlas ingested?).
Those answers legitimately differ; the API makes the choice explicit and never
defaults silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum

from .errors import TemporalError, ValidationError

UTC = timezone.utc
_DT_FMT = "%Y-%m-%dT%H:%M:%SZ"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class AvailabilityPrecision(str, Enum):
    """How well the public-availability time is evidenced."""

    EXACT = "exact"        # e.g. SEC acceptanceDateTime: an instant is documented
    DATE = "date"          # only a calendar date is evidenced; treated as end of day
    UNKNOWN = "unknown"    # no usable timing evidence: excluded from as-of results


class AsOfMode(str, Enum):
    """Which temporal question an as-of query answers."""

    PUBLIC_AVAILABLE = "public_available"
    ATLAS_INGESTED = "atlas_ingested"

    @property
    def column(self) -> str:
        return "availability_time" if self is AsOfMode.PUBLIC_AVAILABLE else "observed_at"

    @property
    def description(self) -> str:
        if self is AsOfMode.PUBLIC_AVAILABLE:
            return "information publicly available at or before the requested instant"
        return "information Atlas had ingested at or before the requested instant"


class PeriodType(str, Enum):
    DURATION = "duration"  # flow: revenue over a quarter
    INSTANT = "instant"    # stock: total assets at a balance-sheet date


def utcnow() -> datetime:
    """Current UTC time truncated to whole seconds (storage precision)."""
    return datetime.now(UTC).replace(microsecond=0)


def to_utc(value: datetime | date | str) -> datetime:
    """Coerce to an aware UTC datetime, truncating to seconds.

    Naive datetimes are *assumed* UTC. That is a documented assumption, not a
    silent conversion: every stored timestamp in Atlas is UTC, so a naive value
    that was actually local time is a caller bug rather than a platform default.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).replace(microsecond=0)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        return parse_iso(value)
    raise ValidationError("cannot interpret value as a timestamp", value=value)


def iso(dt: datetime | date | str) -> str:
    """Serialize to the canonical storage form ``YYYY-MM-DDTHH:MM:SSZ``."""
    if isinstance(dt, str):
        return iso(parse_iso(dt))
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.isoformat()
    return to_utc(dt).strftime(_DT_FMT)


def iso_date(value: date | datetime | str) -> str:
    """Serialize a calendar date as ``YYYY-MM-DD``."""
    if isinstance(value, datetime):
        return to_utc(value).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if _DATE_RE.match(text):
        return text
    return to_utc(text).date().isoformat()


def parse_iso(value: str | datetime) -> datetime:
    """Parse a stored timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        return to_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise TemporalError("empty timestamp", value=value)
    text = value.strip()
    if _DATE_RE.match(text):
        return datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]), tzinfo=UTC)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TemporalError("unparseable timestamp", value=value) from exc
    return to_utc(parsed)


def parse_date(value: str | date | datetime) -> date:
    """Parse a calendar date (date-only strings are accepted)."""
    if isinstance(value, datetime):
        return to_utc(value).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if _DATE_RE.match(text):
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    return to_utc(text).date()


@dataclass(frozen=True, slots=True)
class Availability:
    """Evidenced public availability of a piece of information."""

    time: datetime | None
    precision: AvailabilityPrecision
    basis: str

    @property
    def known(self) -> bool:
        return self.time is not None and self.precision is not AvailabilityPrecision.UNKNOWN

    @property
    def iso(self) -> str | None:
        return iso(self.time) if self.time is not None else None

    def require_known(self, context: str = "value") -> datetime:
        if not self.known or self.time is None:
            raise TemporalError(
                "public availability time is unknown; refusing to invent one",
                context=context,
                basis=self.basis,
            )
        return self.time

    def __post_init__(self) -> None:
        if self.precision is AvailabilityPrecision.UNKNOWN and self.time is not None:
            raise TemporalError(
                "unknown-precision availability must not carry a timestamp",
                time=self.iso,
            )
        if self.precision is not AvailabilityPrecision.UNKNOWN and self.time is None:
            raise TemporalError("evidenced availability requires a timestamp")


def availability_from_instant(when: datetime | str, basis: str) -> Availability:
    """Availability evidenced to the second (e.g. an SEC acceptance timestamp)."""
    if not basis or not str(basis).strip():
        raise TemporalError("availability evidence basis is required")
    return Availability(time=to_utc(when), precision=AvailabilityPrecision.EXACT, basis=basis)


def availability_from_date(
    when: date | str,
    basis: str,
    *,
    end_of_day: time = time(23, 59, 59),
) -> Availability:
    """Availability known only to a calendar date.

    The instant is pinned to the **end** of that day in UTC. That is deliberately
    conservative: an as-of query for that day will not return the fact, so the
    platform can never claim information was available earlier than it can prove.
    """
    if not basis or not str(basis).strip():
        raise TemporalError("availability evidence basis is required")
    day = parse_date(when)
    moment = datetime(day.year, day.month, day.day, end_of_day.hour, end_of_day.minute, end_of_day.second, tzinfo=UTC)
    return Availability(time=moment, precision=AvailabilityPrecision.DATE, basis=basis)


def unknown_availability(basis: str) -> Availability:
    """Availability that the source cannot establish.

    Records carrying this are excluded from point-in-time results by default, and
    the exclusion is reported so the user knows the reconstruction is incomplete.
    """
    return Availability(time=None, precision=AvailabilityPrecision.UNKNOWN, basis=basis or "no timing evidence")


@dataclass(frozen=True, slots=True)
class ReportingPeriod:
    """The accounting interval a fact describes."""

    end: date
    start: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    period_type: PeriodType = PeriodType.DURATION

    def __post_init__(self) -> None:
        if self.start is not None and self.start > self.end:
            raise TemporalError(
                "reporting period start is after its end", start=self.start.isoformat(), end=self.end.isoformat()
            )
        if self.period_type is PeriodType.INSTANT and self.start is not None:
            raise TemporalError("instant periods must not define a start date", end=self.end.isoformat())

    @property
    def duration_days(self) -> int | None:
        if self.start is None:
            return None
        return (self.end - self.start).days

    @property
    def is_approximate_year(self) -> bool:
        """True for a period close to twelve months (annual-flow heuristic)."""
        days = self.duration_days
        return days is not None and 350 <= days <= 380

    @property
    def is_approximate_quarter(self) -> bool:
        days = self.duration_days
        return days is not None and 75 <= days <= 105

    def label(self) -> str:
        if self.period_type is PeriodType.INSTANT:
            return f"@{self.end.isoformat()}"
        return f"{self.start.isoformat()}..{self.end.isoformat()}" if self.start else self.end.isoformat()

    def shifted(self, days: int) -> "ReportingPeriod":
        return ReportingPeriod(
            end=self.end + timedelta(days=days),
            start=self.start + timedelta(days=days) if self.start else None,
            fiscal_year=self.fiscal_year,
            fiscal_period=self.fiscal_period,
            period_type=self.period_type,
        )
