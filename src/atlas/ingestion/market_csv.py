"""CSV / Parquet market-bar import.

Provider-independent by design: the importer understands a small set of column
aliases, requires an explicit security and venue (it will not guess identity), and
refuses to treat an adjusted column as a raw price.

Two behaviours matter for research integrity:

* A file that only offers ``Adj Close`` (a derived, dividend-adjusted series) is
  rejected rather than stored as a raw close. Storing it would silently mix
  adjustment bases in one table.
* Rows that cannot be parsed, or that duplicate a session inside the same file, are
  reported as issues and skipped. Atlas never fills a gap with an interpolated or
  carried-forward value.

Daily bars are timestamped at the session close (from the stored calendar when
available, otherwise 16:00 America/New_York), because a daily bar is only knowable at
the end of its session.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..core.errors import NotSupportedError, ValidationError
from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..core.units import canonical_decimal
from ..market.bars import Bar
from ..market.calendar import EASTERN, TradingCalendar

DATE_COLUMNS = ("date", "datetime", "timestamp", "time", "session_date", "day")
OPEN_COLUMNS = ("open", "o")
HIGH_COLUMNS = ("high", "h")
LOW_COLUMNS = ("low", "l")
CLOSE_COLUMNS = ("close", "c", "last")
VOLUME_COLUMNS = ("volume", "vol", "v", "shares")
VWAP_COLUMNS = ("vwap",)
TRADES_COLUMNS = ("trades", "trade_count")
ADJUSTED_COLUMNS = ("adj close", "adjusted close", "adj_close", "adjusted_close", "adjclose")


@dataclass(slots=True)
class CsvImportResult:
    bars: list[Bar] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    rows_read: int = 0
    rows_skipped: int = 0
    columns: dict[str, str] = field(default_factory=dict)
    source_columns: list[str] = field(default_factory=list)
    adjusted_columns_ignored: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_read": self.rows_read,
            "rows_skipped": self.rows_skipped,
            "bars": len(self.bars),
            "columns": self.columns,
            "source_columns": self.source_columns,
            "adjusted_columns_ignored": self.adjusted_columns_ignored,
            "issues": self.issues,
        }


def _normalise_header(name: str) -> str:
    return " ".join(name.strip().lower().replace("_", " ").split())


def _match(header_map: Mapping[str, str], aliases: Sequence[str]) -> str | None:
    for alias in aliases:
        if alias in header_map:
            return header_map[alias]
    return None


def _to_decimal(value: str | None, *, field_name: str, row_number: int, issues: list[dict[str, Any]]) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        issues.append(
            {
                "code": "unparsable_number",
                "severity": "error",
                "row": row_number,
                "field": field_name,
                "value": value,
                "detail": f"row {row_number}: {field_name} is not a number",
            }
        )
        return None


def _parse_timestamp(raw: str, *, row_number: int, issues: list[dict[str, Any]]) -> datetime | None:
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            day = datetime.strptime(text, fmt).date()
            return datetime.combine(day, time(0, 0), tzinfo=EASTERN)
        except ValueError:
            continue
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        issues.append(
            {
                "code": "unparsable_timestamp",
                "severity": "error",
                "row": row_number,
                "value": text,
                "detail": f"row {row_number}: cannot parse timestamp {text!r}",
            }
        )
        return None
    if parsed.tzinfo is None:
        # A naive timestamp in a market file is exchange-local time; that assumption is
        # recorded in the issue log rather than silently applied.
        issues.append(
            {
                "code": "naive_timestamp_assumed_eastern",
                "severity": "info",
                "row": row_number,
                "value": text,
                "detail": f"row {row_number}: naive timestamp interpreted as America/New_York",
            }
        )
        parsed = parsed.replace(tzinfo=EASTERN)
    return parsed


def import_csv_bars(
    path: str | Path,
    *,
    security_id: str,
    mic: str,
    source_id: str,
    currency: str = "USD",
    calendar: TradingCalendar | None = None,
    default_session_close: time = time(16, 0),
) -> CsvImportResult:
    """Read an OHLCV CSV into raw :class:`Bar` objects."""
    file_path = Path(path)
    if not file_path.exists():
        raise ValidationError("CSV file does not exist", path=str(file_path))
    result = CsvImportResult()
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValidationError("CSV has no header row", path=str(file_path))
        result.source_columns = list(reader.fieldnames)
        header_map = {_normalise_header(name): name for name in reader.fieldnames}
        columns = {
            "date": _match(header_map, DATE_COLUMNS),
            "open": _match(header_map, OPEN_COLUMNS),
            "high": _match(header_map, HIGH_COLUMNS),
            "low": _match(header_map, LOW_COLUMNS),
            "close": _match(header_map, CLOSE_COLUMNS),
            "volume": _match(header_map, VOLUME_COLUMNS),
            "vwap": _match(header_map, VWAP_COLUMNS),
            "trades": _match(header_map, TRADES_COLUMNS),
        }
        adjusted = [name for key, name in header_map.items() if key in ADJUSTED_COLUMNS]
        result.adjusted_columns_ignored = adjusted
        if adjusted:
            result.issues.append(
                {
                    "code": "adjusted_column_ignored",
                    "severity": "warning",
                    "detail": (
                        f"ignored adjusted column(s) {adjusted}: Atlas stores raw closes only and "
                        "derives adjusted series from corporate actions"
                    ),
                }
            )
        # A file that offers *only* a derived price series is refused with a specific
        # error, before the generic "missing columns" message can obscure why: storing
        # Adj Close as a raw close would silently mix adjustment bases.
        price_columns = ("open", "high", "low", "close")
        if adjusted and all(columns[key] is None for key in price_columns):
            raise NotSupportedError(
                "file offers only an adjusted price column; import a raw OHLC series instead",
                adjusted_columns=adjusted,
            )
        missing = [key for key in ("date", "open", "high", "low", "close") if columns[key] is None]
        if missing:
            raise ValidationError(
                "CSV is missing required columns", missing=missing, found=result.source_columns
            )
        result.columns = {key: value for key, value in columns.items() if value}

        seen: dict[str, int] = {}
        for row_number, row in enumerate(reader, start=2):
            result.rows_read += 1
            raw_ts = row.get(columns["date"]) if columns["date"] else None
            if raw_ts is None:
                result.rows_skipped += 1
                result.issues.append(
                    {"code": "missing_date", "severity": "error", "row": row_number,
                     "detail": f"row {row_number}: missing date"}
                )
                continue
            parsed_ts = _parse_timestamp(raw_ts, row_number=row_number, issues=result.issues)
            if parsed_ts is None:
                result.rows_skipped += 1
                continue

            values: dict[str, Decimal | None] = {}
            for field_name in ("open", "high", "low", "close"):
                column = columns[field_name]
                values[field_name] = _to_decimal(
                    row.get(column) if column else None,
                    field_name=field_name,
                    row_number=row_number,
                    issues=result.issues,
                )
            if any(values[name] is None for name in ("open", "high", "low", "close")):
                result.rows_skipped += 1
                result.issues.append(
                    {"code": "missing_ohlc", "severity": "error", "row": row_number,
                     "detail": f"row {row_number}: incomplete OHLC values"}
                )
                continue
            volume = _to_decimal(
                row.get(columns["volume"]) if columns["volume"] else None,
                field_name="volume",
                row_number=row_number,
                issues=result.issues,
            )
            vwap = _to_decimal(
                row.get(columns["vwap"]) if columns["vwap"] else None,
                field_name="vwap",
                row_number=row_number,
                issues=result.issues,
            )
            trades_raw = row.get(columns["trades"]) if columns["trades"] else None
            trades = None
            if trades_raw not in (None, ""):
                try:
                    trades = int(str(trades_raw).strip())
                except ValueError:
                    result.issues.append(
                        {"code": "unparsable_trades", "severity": "warning", "row": row_number,
                         "value": trades_raw, "detail": f"row {row_number}: trades is not an integer"}
                    )

            day = parsed_ts.date()
            if parsed_ts.time() == time(0, 0):
                ts = _session_close_instant(day, mic=mic, calendar=calendar, default_close=default_session_close)
            else:
                ts = parsed_ts

            day_key = day.isoformat()
            if day_key in seen:
                result.rows_skipped += 1
                result.issues.append(
                    {
                        "code": "duplicate_row_in_source",
                        "severity": "error",
                        "row": row_number,
                        "detail": (
                            f"row {row_number}: {day_key} already present at row {seen[day_key]}; "
                            "duplicate rows in one file are a source defect, not two observations"
                        ),
                    }
                )
                continue
            seen[day_key] = row_number
            result.bars.append(
                Bar(
                    security_id=security_id,
                    mic=mic.upper(),
                    ts_utc=iso(ts),
                    open=values["open"],  # type: ignore[arg-type]
                    high=values["high"],  # type: ignore[arg-type]
                    low=values["low"],  # type: ignore[arg-type]
                    close=values["close"],  # type: ignore[arg-type]
                    volume=volume,
                    vwap=vwap,
                    trades=trades,
                    currency=currency,
                    source_id=source_id,
                )
            )
    return result


def _session_close_instant(
    day: date, *, mic: str, calendar: TradingCalendar | None, default_close: time
) -> datetime:
    if calendar is not None:
        rows = calendar.sessions(mic, day.isoformat(), day.isoformat())
        if rows:
            from ..core.temporal import parse_iso

            return parse_iso(rows[0].close_ts)
    return datetime.combine(day, default_close, tzinfo=EASTERN)


def import_parquet_bars(
    path: str | Path,
    *,
    security_id: str,
    mic: str,
    source_id: str,
    currency: str = "USD",
    calendar: TradingCalendar | None = None,
) -> CsvImportResult:
    """Parquet path. Requires the optional ``pyarrow`` dependency."""
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise NotSupportedError(
            "Parquet import requires the optional 'pyarrow' dependency",
            hint="pip install 'atlas-quant[columnar]'",
        ) from exc
    file_path = Path(path)
    if not file_path.exists():
        raise ValidationError("Parquet file does not exist", path=str(file_path))
    table = pq.read_table(file_path)
    rows = table.to_pylist()
    import tempfile

    result = CsvImportResult()
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as handle:
        if not rows:
            raise ValidationError("Parquet file is empty", path=str(file_path))
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})
        temp_path = handle.name
    try:
        result = import_csv_bars(
            temp_path,
            security_id=security_id,
            mic=mic,
            source_id=source_id,
            currency=currency,
            calendar=calendar,
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)
    result.columns["format"] = "parquet"
    return result
