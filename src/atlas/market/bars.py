"""Immutable daily OHLCV bar storage.

Rules:

* A *raw* bar is exactly what the provider said, stored as decimal strings. Atlas
  never edits it. A provider correction is stored as ``revision_seq + 1`` with
  ``supersedes_bar`` pointing at the revision it replaces, so both versions survive
  and a point-in-time read can say which one it used.
* Derived series (split- or total-return adjusted) are computed on read and labelled
  with their ``adjustment_status``; they are never written back as raw bars.
* Suspicious observations (impossible OHLC, negative volume, non-session date) are
  flagged and logged as data-quality issues, not silently corrected or dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..core.units import canonical_decimal, parse_decimal
from ..storage.db import Database
from ..storage.quality import SEVERITY_ERROR, SEVERITY_WARNING, record_issue
from .calendar import TradingCalendar

INTERVAL_DAILY = "1d"
ADJUSTMENT_RAW = "raw"
ADJUSTMENT_SPLIT = "split_adjusted"
ADJUSTMENT_TOTAL_RETURN = "total_return_adjusted"


@dataclass(slots=True)
class Bar:
    """One OHLCV observation."""

    security_id: str
    mic: str
    ts_utc: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    currency: str
    source_id: str
    interval: str = INTERVAL_DAILY
    volume: Decimal | None = None
    trades: int | None = None
    vwap: Decimal | None = None
    adjustment_status: str = ADJUSTMENT_RAW
    observed_at: str | None = None
    ingested_at: str | None = None
    revision_seq: int = 1
    supersedes_bar: int | None = None
    quality_flags: tuple[str, ...] = ()

    @property
    def session_date(self) -> str:
        return iso_date(self.ts_utc)

    @property
    def ts(self):
        from ..core.temporal import parse_iso

        return parse_iso(self.ts_utc)

    def ohlcv(self) -> tuple[str, str, str, str, str | None]:
        return (
            canonical_decimal(self.open),
            canonical_decimal(self.high),
            canonical_decimal(self.low),
            canonical_decimal(self.close),
            canonical_decimal(self.volume) if self.volume is not None else None,
        )

    def structural_flags(self) -> list[tuple[str, str]]:
        """Return ``(code, detail)`` for violations of OHLC invariants."""
        issues: list[tuple[str, str]] = []
        o, h, l, c = self.open, self.high, self.low, self.close
        if min(o, h, l, c) <= 0:
            issues.append(("non_positive_price", f"non-positive price in {self.security_id} at {self.ts_utc}"))
        if h < max(o, c, l):
            issues.append(("high_below_other_prices", f"high {h} < max(open,low,close) at {self.ts_utc}"))
        if l > min(o, c, h):
            issues.append(("low_above_other_prices", f"low {l} > min(open,high,close) at {self.ts_utc}"))
        if self.volume is not None and self.volume < 0:
            issues.append(("negative_volume", f"negative volume {self.volume} at {self.ts_utc}"))
        if self.vwap is not None and not (l <= self.vwap <= h):
            issues.append(("vwap_outside_range", f"vwap {self.vwap} outside [{l}, {h}] at {self.ts_utc}"))
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "mic": self.mic,
            "interval": self.interval,
            "ts_utc": self.ts_utc,
            "session_date": self.session_date,
            "open": canonical_decimal(self.open),
            "high": canonical_decimal(self.high),
            "low": canonical_decimal(self.low),
            "close": canonical_decimal(self.close),
            "volume": canonical_decimal(self.volume) if self.volume is not None else None,
            "trades": self.trades,
            "vwap": canonical_decimal(self.vwap) if self.vwap is not None else None,
            "currency": self.currency,
            "adjustment_status": self.adjustment_status,
            "source_id": self.source_id,
            "observed_at": self.observed_at,
            "ingested_at": self.ingested_at,
            "revision_seq": self.revision_seq,
            "supersedes_bar": self.supersedes_bar,
            "quality_flags": list(self.quality_flags),
        }

    @classmethod
    def from_row(cls, row: Any) -> "Bar":
        return cls(
            security_id=row["security_id"],
            mic=row["mic"],
            ts_utc=row["ts_utc"],
            open=parse_decimal(row["open"]),
            high=parse_decimal(row["high"]),
            low=parse_decimal(row["low"]),
            close=parse_decimal(row["close"]),
            volume=parse_decimal(row["volume"]) if row["volume"] is not None else None,
            trades=row["trades"],
            vwap=parse_decimal(row["vwap"]) if row["vwap"] is not None else None,
            currency=row["currency"],
            adjustment_status=row["adjustment_status"],
            source_id=row["source_id"],
            observed_at=row["observed_at"],
            ingested_at=row["ingested_at"],
            interval=row["interval"],
            revision_seq=row["revision_seq"],
            supersedes_bar=row["supersedes_bar"],
            quality_flags=tuple(json.loads(row["quality_flags"])) if row["quality_flags"] else (),
        )


@dataclass(slots=True)
class BarIngestSummary:
    inserted: int = 0
    duplicates: int = 0
    revisions: int = 0
    rejected: int = 0
    flags: list[dict[str, Any]] = field(default_factory=list)

    def add(self, status: str, bar: Bar, flags: Sequence[str] = ()) -> None:
        if status == "inserted":
            self.inserted += 1
        elif status == "duplicate":
            self.duplicates += 1
        elif status == "revision":
            self.revisions += 1
        else:
            self.rejected += 1
        if flags:
            self.flags.append({"bar": bar.to_dict(), "flags": list(flags)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "revisions": self.revisions,
            "rejected": self.rejected,
            "flagged": len(self.flags),
        }


class BarStore:
    """Storage and validation of raw market observations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------- write
    def ingest(
        self,
        bars: Iterable[Bar],
        *,
        observed_at: str | None = None,
        flag_issues: bool = True,
    ) -> BarIngestSummary:
        summary = BarIngestSummary()
        observed = observed_at or iso(utcnow())
        ingested = iso(utcnow())
        with self.db.transaction():
            for bar in bars:
                if bar.adjustment_status != ADJUSTMENT_RAW:
                    raise ValidationError(
                        "only raw observations may be ingested; adjusted series are derived views",
                        adjustment_status=bar.adjustment_status,
                        security_id=bar.security_id,
                    )
                if self.db.query_one("SELECT 1 FROM security WHERE security_id = ?", (bar.security_id,)) is None:
                    raise ValidationError("unknown security for bar", security_id=bar.security_id)
                flags = [code for code, _ in bar.structural_flags()]
                if flag_issues:
                    for code, detail in bar.structural_flags():
                        record_issue(
                            self.db,
                            scope="market_bar",
                            subject_id=f"{bar.security_id}:{bar.ts_utc}",
                            code=code,
                            severity=SEVERITY_ERROR if code != "vwap_outside_range" else SEVERITY_WARNING,
                            detail=detail,
                        )
                previous = self.db.query_one(
                    "SELECT revision_seq, open, high, low, close, volume FROM bar WHERE security_id = ? AND "
                    "mic = ? AND interval = ? AND ts_utc = ? AND source_id = ? ORDER BY revision_seq DESC LIMIT 1",
                    (bar.security_id, bar.mic.upper(), bar.interval, iso(bar.ts_utc), bar.source_id),
                )
                if previous is None:
                    self._insert(bar, seq=1, observed=observed, ingested=ingested, flags=flags)
                    summary.add("inserted", bar, flags)
                    continue
                incoming = bar.ohlcv()
                stored = (previous["open"], previous["high"], previous["low"], previous["close"], previous["volume"])
                if incoming == stored:
                    summary.add("duplicate", bar)
                    continue
                seq = int(previous["revision_seq"]) + 1
                self._insert(bar, seq=seq, observed=observed, ingested=ingested, flags=flags + ["provider_revision"],
                             supersedes=seq - 1)
                record_issue(
                    self.db,
                    scope="market_bar",
                    subject_id=f"{bar.security_id}:{bar.ts_utc}",
                    code="provider_revision",
                    severity=SEVERITY_WARNING,
                    detail=f"provider restated {bar.ts_utc} from {stored[:4]} to {incoming[:4]} (revision {seq})",
                )
                summary.add("revision", bar, flags + ["provider_revision"])
        return summary

    def _insert(
        self,
        bar: Bar,
        *,
        seq: int,
        observed: str,
        ingested: str,
        flags: Sequence[str],
        supersedes: int | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO bar (security_id, mic, interval, ts_utc, revision_seq, open, high, low, close, volume, "
            "trades, vwap, currency, adjustment_status, source_id, observed_at, ingested_at, supersedes_bar, "
            "quality_flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                bar.security_id,
                bar.mic.upper(),
                bar.interval,
                iso(bar.ts_utc),
                seq,
                canonical_decimal(bar.open),
                canonical_decimal(bar.high),
                canonical_decimal(bar.low),
                canonical_decimal(bar.close),
                canonical_decimal(bar.volume) if bar.volume is not None else None,
                bar.trades,
                canonical_decimal(bar.vwap) if bar.vwap is not None else None,
                bar.currency,
                bar.adjustment_status,
                bar.source_id,
                observed,
                ingested,
                supersedes,
                json.dumps(sorted(set(flags))) if flags else None,
            ),
        )

    # -------------------------------------------------------------------- read
    def query(
        self,
        security_id: str,
        mic: str,
        start: str,
        end: str,
        *,
        interval: str = INTERVAL_DAILY,
        include_superseded: bool = False,
    ) -> list[Bar]:
        params: list[Any] = [security_id, mic.upper(), interval, iso_date(start), iso_date(end) + "T23:59:59Z"]
        sql = (
            "SELECT * FROM bar WHERE security_id = ? AND mic = ? AND interval = ? AND ts_utc BETWEEN ? AND ?"
        )
        if not include_superseded:
            sql += (
                " AND revision_seq = (SELECT MAX(b2.revision_seq) FROM bar b2 WHERE b2.security_id = bar.security_id "
                "AND b2.mic = bar.mic AND b2.interval = bar.interval AND b2.ts_utc = bar.ts_utc "
                "AND b2.source_id = bar.source_id)"
            )
        rows = self.db.query(sql + " ORDER BY ts_utc", params)
        return [Bar.from_row(row) for row in rows]

    def revisions(self, security_id: str, mic: str, ts_utc: str) -> list[Bar]:
        rows = self.db.query(
            "SELECT * FROM bar WHERE security_id = ? AND mic = ? AND ts_utc = ? ORDER BY revision_seq",
            (security_id, mic.upper(), iso(ts_utc)),
        )
        return [Bar.from_row(row) for row in rows]

    def latest_close(self, security_id: str, mic: str, on_or_before: str) -> Bar | None:
        # The previous correlated MAX(revision_seq) subquery was evaluated for every
        # candidate row, turning a newest-row lookup into a full scan (28 ms per call on
        # a 10k-row table). Ordering by (ts_utc, revision_seq) uses idx_bar_latest_v4 and
        # returns the newest revision directly.
        row = self.db.query_one(
            "SELECT * FROM bar WHERE security_id = ? AND mic = ? AND interval = '1d' AND ts_utc <= ? "
            "ORDER BY ts_utc DESC, revision_seq DESC LIMIT 1",
            (security_id, mic.upper(), iso_date(on_or_before) + "T23:59:59Z"),
        )
        return Bar.from_row(row) if row is not None else None

    def coverage(self, security_id: str, mic: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT MIN(ts_utc) AS first, MAX(ts_utc) AS last, COUNT(DISTINCT ts_utc) AS sessions, "
            "COUNT(*) AS rows FROM bar WHERE security_id = ? AND mic = ?",
            (security_id, mic.upper()),
        )
        return {
            "security_id": security_id,
            "mic": mic.upper(),
            "first_bar": row["first"] if row else None,
            "last_bar": row["last"] if row else None,
            "sessions": (row["sessions"] or 0) if row else 0,
            "rows": (row["rows"] or 0) if row else 0,
        }

    # -------------------------------------------------------------- validation
    def validate(
        self,
        security_id: str,
        mic: str,
        *,
        start: str | None = None,
        end: str | None = None,
        calendar: TradingCalendar | None = None,
        max_daily_move: Decimal = Decimal("0.5"),
        known_action_dates: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Validate a stored series; returns findings without modifying anything."""
        bars = self.query(security_id, mic, start or "1900-01-01", end or "2999-12-31")
        findings: list[dict[str, Any]] = []
        if not bars:
            return [{"code": "no_data", "severity": "warning", "detail": "no bars stored for the requested range"}]

        seen: dict[str, int] = {}
        for bar in bars:
            for code, detail in bar.structural_flags():
                findings.append({"code": code, "severity": "error", "detail": detail, "ts_utc": bar.ts_utc})
            seen[bar.session_date] = seen.get(bar.session_date, 0) + 1
        duplicates = [day for day, count in seen.items() if count > 1]
        if duplicates:
            findings.append(
                {"code": "duplicate_observations", "severity": "error",
                 "detail": f"{len(duplicates)} session(s) with multiple rows: {sorted(duplicates)[:5]}"}
            )

        ordered = sorted(bars, key=lambda b: b.ts_utc)
        for previous, current in zip(ordered, ordered[1:]):
            if current.close <= 0 or previous.close <= 0:
                continue
            move = (current.close - previous.close) / previous.close
            if abs(move) > max_daily_move:
                action_dates = known_action_dates or set()
                suspicious = current.session_date not in action_dates
                findings.append(
                    {
                        "code": "suspicious_price_move" if suspicious else "large_move_with_corporate_action",
                        "severity": "warning" if suspicious else "info",
                        "detail": (
                            f"{current.session_date}: close moved {move:.2%} from {previous.close} to {current.close}"
                            + ("" if suspicious else " (corporate action recorded on this date)")
                        ),
                        "ts_utc": current.ts_utc,
                    }
                )

        if calendar is not None:
            calendar.ensure_range(mic, ordered[0].session_date, ordered[-1].session_date)
            observed = set(seen)
            missing = calendar.missing_sessions(mic, observed, ordered[0].session_date, ordered[-1].session_date)
            if missing:
                findings.append(
                    {
                        "code": "missing_sessions",
                        "severity": "warning",
                        "detail": f"{len(missing)} session(s) without observations: {missing[:10]}",
                    }
                )
            off_calendar = sorted(observed - set(calendar.session_dates(mic, ordered[0].session_date, ordered[-1].session_date)))
            if off_calendar:
                findings.append(
                    {
                        "code": "bar_outside_calendar",
                        "severity": "error",
                        "detail": f"{len(off_calendar)} observation(s) on non-session dates: {off_calendar[:10]}",
                    }
                )
        return findings
