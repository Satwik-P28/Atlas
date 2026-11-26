"""Trading calendars.

A bar on a non-trading day is a data error, and a missing session inside a stored
range is a gap that must be shown rather than interpolated. Both checks need an
explicit calendar, so Atlas stores one instead of inferring sessions from prices.

Phase 1 implements the NYSE/Nasdaq (XNYS/XNAS) rule set: weekends, the standard
exchange holidays, and the short sessions that actually occur. The rules are version
dependent in reality (Juneteenth began in 2022, for example), so they are encoded as a
function of the year rather than assumed constant.

Known limitation: this is a rule-based calendar, not an official exchange calendar.
If an exchange declares an unscheduled closure (weather, national mourning), the
stored calendar will be wrong until the venue data is amended. :meth:`observed_gaps`
reports bars that fall outside the rule-based calendar so such cases surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..storage.db import Database


def _eastern() -> ZoneInfo:
    """Exchange calendars need the IANA database, which some platforms do not ship."""
    try:
        return ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - only on a platform without tzdata
        raise RuntimeError(
            "Atlas needs the IANA time zone database to build exchange calendars. Install the "
            "'tzdata' package (it is a declared dependency, so a wheel install already has it)."
        ) from exc


EASTERN = _eastern()

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

#: Venues Atlas knows how to build a calendar for.
CALENDAR_VENUES: dict[str, dict[str, str]] = {
    "XNYS": {"name": "New York Stock Exchange", "country": "US", "timezone": "America/New_York"},
    "XNAS": {"name": "Nasdaq Global Select Market", "country": "US", "timezone": "America/New_York"},
}


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """``n``-th (1-based) given weekday of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed(day: date, *, saturday_to_friday: bool) -> date:
    """Observed date for a fixed-date holiday.

    Saturday holidays are observed Friday only where the exchange does so; New Year's
    Day is the documented exception (no Friday close when 1 January falls on Saturday).
    """
    if day.weekday() == 5:
        return day - timedelta(days=1) if saturday_to_friday else day
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def us_equity_holidays(year: int) -> dict[date, str]:
    """NYSE/Nasdaq full-day closures for a calendar year."""
    holidays: dict[date, str] = {
        _observed(date(year, 1, 1), saturday_to_friday=False): "New Year's Day",
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        _easter(year) - timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, 0): "Memorial Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
        _observed(date(year, 7, 4), saturday_to_friday=True): "Independence Day",
        _observed(date(year, 12, 25), saturday_to_friday=True): "Christmas Day",
    }
    if year >= 2022:
        holidays[_observed(date(year, 6, 19), saturday_to_friday=True)] = "Juneteenth National Independence Day"
    # A Saturday-observed closure that lands on 31 December is not observed in that year
    # by the NYSE; it is simply not a session.
    return {day: name for day, name in holidays.items() if day.weekday() < 5}


def us_equity_early_closes(year: int) -> dict[date, str]:
    """Scheduled 13:00 ET closes."""
    holidays = us_equity_holidays(year)
    candidates: dict[date, str] = {}
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    candidates[thanksgiving + timedelta(days=1)] = "Day after Thanksgiving"
    july_3 = date(year, 7, 3)
    if july_3.weekday() < 5 and july_3 not in holidays:
        candidates[july_3] = "Independence Day eve"
    december_24 = date(year, 12, 24)
    if december_24.weekday() < 5 and december_24 not in holidays:
        candidates[december_24] = "Christmas Eve"
    return {day: name for day, name in candidates.items() if day.weekday() < 5 and day not in holidays}


@dataclass(frozen=True, slots=True)
class Session:
    mic: str
    session_date: str
    open_ts: str
    close_ts: str
    is_early_close: bool
    label: str | None = None

    @property
    def opens_at(self) -> datetime:
        from ..core.temporal import parse_iso

        return parse_iso(self.open_ts)

    @property
    def closes_at(self) -> datetime:
        from ..core.temporal import parse_iso

        return parse_iso(self.close_ts)


def _session_bounds(day: date, *, early: bool) -> tuple[datetime, datetime]:
    close = EARLY_CLOSE if early else REGULAR_CLOSE
    open_dt = datetime.combine(day, REGULAR_OPEN, tzinfo=EASTERN)
    close_dt = datetime.combine(day, close, tzinfo=EASTERN)
    return open_dt, close_dt


class TradingCalendar:
    """Stored venue calendars with gap detection."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_venue(self, mic: str) -> str:
        code = mic.upper()
        if code not in CALENDAR_VENUES:
            raise ValidationError("no calendar rule set for venue", mic=mic)
        meta = CALENDAR_VENUES[code]
        self.db.execute(
            "INSERT INTO venue (mic, name, country, timezone) VALUES (?,?,?,?) "
            "ON CONFLICT(mic) DO UPDATE SET name=excluded.name, country=excluded.country, "
            "timezone=excluded.timezone",
            (code, meta["name"], meta["country"], meta["timezone"]),
        )
        return code

    def build(self, mic: str, start: date | str, end: date | str, *, source_id: str | None = None) -> int:
        """Generate and store sessions for an inclusive date range (idempotent)."""
        code = self.ensure_venue(mic)
        first, last = parse_date(start), parse_date(end)
        if last < first:
            raise ValidationError("calendar range ends before it starts", start=str(first), end=str(last))
        rows: list[tuple[str, str, str, str, int, str | None]] = []
        day = first
        holidays_by_year: dict[int, dict[date, str]] = {}
        early_by_year: dict[int, dict[date, str]] = {}
        while day <= last:
            if day.weekday() < 5:
                if day.year not in holidays_by_year:
                    holidays_by_year[day.year] = us_equity_holidays(day.year)
                    early_by_year[day.year] = us_equity_early_closes(day.year)
                if day not in holidays_by_year[day.year]:
                    early = day in early_by_year[day.year]
                    open_dt, close_dt = _session_bounds(day, early=early)
                    rows.append(
                        (code, day.isoformat(), iso(open_dt), iso(close_dt), int(early), source_id)
                    )
            day += timedelta(days=1)
        before = len(rows)
        self.db.executemany(
            "INSERT INTO trading_session (mic, session_date, open_ts, close_ts, is_early_close, source_id) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(mic, session_date) DO UPDATE SET "
            "open_ts=excluded.open_ts, close_ts=excluded.close_ts, is_early_close=excluded.is_early_close",
            rows,
        )
        return before

    def ensure_range(self, mic: str, start: str, end: str) -> None:
        """Guarantee stored sessions for the range, building only what is missing."""
        code = mic.upper()
        first, last = parse_date(start), parse_date(end)
        existing = self.db.query(
            "SELECT MIN(session_date) AS lo, MAX(session_date) AS hi FROM trading_session WHERE mic = ?", (code,)
        )
        if existing and existing[0]["lo"] and existing[0]["hi"]:
            lo, hi = existing[0]["lo"], existing[0]["hi"]
            if lo <= first.isoformat() and hi >= last.isoformat():
                return
        self.build(code, first, last)

    # ------------------------------------------------------------------ queries
    def sessions(self, mic: str, start: str, end: str) -> list[Session]:
        rows = self.db.query(
            "SELECT mic, session_date, open_ts, close_ts, is_early_close FROM trading_session "
            "WHERE mic = ? AND session_date BETWEEN ? AND ? ORDER BY session_date",
            (mic.upper(), iso_date(start), iso_date(end)),
        )
        return [
            Session(
                mic=row["mic"],
                session_date=row["session_date"],
                open_ts=row["open_ts"],
                close_ts=row["close_ts"],
                is_early_close=bool(row["is_early_close"]),
            )
            for row in rows
        ]

    def session_dates(self, mic: str, start: str, end: str) -> list[str]:
        return [s.session_date for s in self.sessions(mic, start, end)]

    def is_session(self, mic: str, day: str | date) -> bool:
        value = iso_date(day)
        row = self.db.query_one(
            "SELECT 1 AS ok FROM trading_session WHERE mic = ? AND session_date = ?", (mic.upper(), value)
        )
        return row is not None

    def previous_session(self, mic: str, day: str | date) -> str | None:
        value = iso_date(day)
        row = self.db.query_one(
            "SELECT MAX(session_date) AS d FROM trading_session WHERE mic = ? AND session_date < ?",
            (mic.upper(), value),
        )
        return row["d"] if row is not None else None

    def next_session(self, mic: str, day: str | date) -> str | None:
        value = iso_date(day)
        row = self.db.query_one(
            "SELECT MIN(session_date) AS d FROM trading_session WHERE mic = ? AND session_date > ?",
            (mic.upper(), value),
        )
        return row["d"] if row is not None else None

    def missing_sessions(self, mic: str, observed: set[str], start: str, end: str) -> list[str]:
        """Sessions inside ``[start, end]`` with no observation."""
        return [s for s in self.session_dates(mic, start, end) if s not in observed]

    def coverage(self, mic: str) -> dict[str, object]:
        row = self.db.query_one(
            "SELECT MIN(session_date) AS first, MAX(session_date) AS last, COUNT(*) AS n, "
            "SUM(is_early_close) AS early FROM trading_session WHERE mic = ?",
            (mic.upper(),),
        )
        return {
            "mic": mic.upper(),
            "first_session": row["first"] if row else None,
            "last_session": row["last"] if row else None,
            "sessions": row["n"] if row else 0,
            "early_closes": (row["early"] or 0) if row else 0,
        }
