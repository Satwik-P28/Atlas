"""Alpha Vantage daily-bar, split and dividend adapter.

Alpha Vantage's public API is an *authorized* vendor interface, but its free ``demo``
key is restricted to IBM. Atlas therefore archives the demo responses it actually
received (``fixtures/market/ibm_*_alphavantage.json``) and ingests them through this
adapter with a source row that states the restriction. Production use requires the
caller's own key; the parser is provider-shaped, not demo-shaped.

What this adapter does **not** claim:

* Alpha Vantage daily prices are end-of-day vendor observations, not exchange ticks.
  Atlas timestamps them at the session close and records the retrieval instant, because
  a daily bar is only knowable after its session.
* The demo feed provides no revision history. Re-fetching a changed value creates a new
  bar revision through :class:`~atlas.market.bars.BarStore`, not a silent overwrite.
* Split factors are vendor adjustments (IBM's 2021 1.046 event is a spin-off-related
  adjustment, not a round split). They are stored as actions with the vendor's terms,
  and adjusted views are always labelled as derived.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from ..core.errors import ValidationError
from ..core.temporal import iso
from ..core.units import parse_decimal
from ..market.actions import ActionType, CorporateAction
from ..market.bars import Bar
from ..storage.sources import SourceDefinition, SourceRegistry

# The calendar module already resolves the venue zone and reports a missing IANA database with
# an actionable message, so this importer reuses it instead of raising a bare import error.
from ..market.calendar import EASTERN
ALPHAVANTAGE_SOURCE = "alphavantage"

ALPHA_VANTAGE = SourceDefinition(
    source_id=ALPHAVANTAGE_SOURCE,
    name="Alpha Vantage (IBM demo feed)",
    kind="market_data",
    homepage="https://www.alphavantage.co/",
    licence="Alpha Vantage terms of service; free demo key is limited to IBM",
    redistribution="restricted",
    notes=(
        "Daily vendor observations archived from the authorized demo endpoint on "
        "2026-11-04. Not exchange data, not redistributable, and not a complete "
        "corporate-action history. Production deployments must use their own API key "
        "and the vendor's licensed terms."
    ),
)


def register_source(db_or_registry: Any) -> str:
    registry = db_or_registry if isinstance(db_or_registry, SourceRegistry) else SourceRegistry(db_or_registry)
    return registry.ensure(ALPHA_VANTAGE)


def _error(payload: dict[str, Any]) -> None:
    for key in ("Error Message", "Information", "Note"):
        if key in payload:
            raise ValidationError("Alpha Vantage returned no series", provider_message=str(payload[key])[:240])


def parse_daily(
    payload: dict[str, Any],
    *,
    security_id: str,
    mic: str,
    source_id: str = ALPHAVANTAGE_SOURCE,
    currency: str = "USD",
) -> list[Bar]:
    """Parse ``TIME_SERIES_DAILY`` into raw bars (one per session)."""
    _error(payload)
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        raise ValidationError("Alpha Vantage payload has no daily series")
    bars: list[Bar] = []
    for day_text, row in sorted(series.items()):
        try:
            day = date.fromisoformat(day_text)
        except ValueError as exc:
            raise ValidationError("invalid session date in provider payload", date=day_text) from exc
        try:
            close_time = datetime.combine(day, time(16, 0), tzinfo=EASTERN)
            bars.append(
                Bar(
                    security_id=security_id,
                    mic=mic.upper(),
                    ts_utc=iso(close_time),
                    open=parse_decimal(row["1. open"]),
                    high=parse_decimal(row["2. high"]),
                    low=parse_decimal(row["3. low"]),
                    close=parse_decimal(row["4. close"]),
                    volume=parse_decimal(row["5. volume"]) if row.get("5. volume") not in (None, "") else None,
                    currency=currency,
                    source_id=source_id,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("malformed Alpha Vantage daily row", date=day_text) from exc
    return bars


def parse_splits(
    payload: dict[str, Any], *, security_id: str, source_id: str = ALPHAVANTAGE_SOURCE
) -> list[CorporateAction]:
    """Parse ``SPLITS`` into comparable action records.

    The vendor's ``split_factor`` is the share-count multiplier. A factor above 1 is a
    forward split; below 1 is a reverse split. Non-integer factors are kept exactly and
    documented as vendor adjustments.
    """
    _error(payload)
    actions: list[CorporateAction] = []
    for entry in payload.get("data", []):
        try:
            factor = Decimal(str(entry["split_factor"]))
            effective = str(entry["effective_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("malformed Alpha Vantage split row", entry=entry) from exc
        if factor <= 0:
            raise ValidationError("split factor must be positive", factor=str(factor))
        actions.append(
            CorporateAction(
                security_id=security_id,
                action_type=(ActionType.SPLIT.value if factor > 1 else ActionType.REVERSE_SPLIT.value),
                source_id=source_id,
                ex_date=effective,
                effective_date=effective,
                ratio_from=Decimal("1"),
                ratio_to=factor if factor > 1 else Decimal("1") / factor,
                terms={"vendor_split_factor": str(factor), "vendor": "alphavantage"},
                notes=(
                    "Vendor share-count adjustment. Non-integer factors usually represent "
                    "spin-off or distribution adjustments, not a round split."
                ),
            )
        )
    return actions


def _optional(value: Any) -> str | None:
    """The vendor serialises absent dates as the string "None"; treat that as absent."""
    if value in (None, "", "None", "null"):
        return None
    return str(value)


def parse_dividends(
    payload: dict[str, Any], *, security_id: str, source_id: str = ALPHAVANTAGE_SOURCE
) -> list[CorporateAction]:
    _error(payload)
    actions: list[CorporateAction] = []
    for entry in payload.get("data", []):
        try:
            amount = Decimal(str(entry["amount"]))
            ex_date = str(entry["ex_dividend_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("malformed Alpha Vantage dividend row", entry=entry) from exc
        actions.append(
            CorporateAction(
                security_id=security_id,
                action_type=ActionType.CASH_DIVIDEND.value,
                source_id=source_id,
                ex_date=ex_date,
                record_date=_optional(entry.get("record_date")),
                payable_date=_optional(entry.get("payment_date")),
                cash_amount=amount,
                currency="USD",
                terms={"declaration_date": _optional(entry.get("declaration_date")), "vendor": "alphavantage"},
                notes="Cash dividend per share from the vendor feed.",
            )
        )
    return actions


def load_archived(
    directory: str | Path,
    *,
    security_id: str,
    mic: str,
    source_id: str = ALPHAVANTAGE_SOURCE,
    daily_filename: str = "daily_bars_alphavantage.json",
    dividends_filename: str = "dividends_alphavantage.json",
    splits_filename: str = "splits_alphavantage.json",
) -> dict[str, Any]:
    """Load three archived vendor documents that the *caller* retained lawfully.

    Atlas no longer ships vendor market archives: redistribution of a vendor feed is not
    ours to grant. A user who holds an entitlement points this adapter at their own files;
    the filenames are explicit so nothing is discovered by guesswork.
    """
    base = Path(directory)
    daily = json.loads((base / daily_filename).read_text())
    dividends = json.loads((base / dividends_filename).read_text())
    splits = json.loads((base / splits_filename).read_text())
    return {
        "bars": parse_daily(daily, security_id=security_id, mic=mic, source_id=source_id),
        "actions": parse_splits(splits, security_id=security_id, source_id=source_id)
        + parse_dividends(dividends, security_id=security_id, source_id=source_id),
        "meta": daily.get("Meta Data", {}),
        "synthetic": False,
    }


def load_synthetic_fixture(
    directory: str | Path,
    *,
    security_id: str,
    mic: str,
    source_id: str = "synthetic-market-fixture",
) -> dict[str, Any]:
    """Load the project-authored synthetic fixture through the provider-shaped parsers.

    The values are generated, not observed. The loader refuses a payload that is not
    explicitly labelled synthetic so a real vendor file can never be relabelled by
    accident, and the returned payload says ``synthetic: True`` so callers can label the
    UI and any export.
    """
    base = Path(directory)
    daily = json.loads((base / "synthetic_daily_bars.json").read_text())
    dividends = json.loads((base / "synthetic_dividends.json").read_text())
    splits = json.loads((base / "synthetic_splits.json").read_text())
    meta = daily.get("Meta Data") or {}
    if str(meta.get("6. Synthetic", "")).lower() != "true":
        raise ValidationError(
            "synthetic fixture is not labelled synthetic; refusing to ingest it as generated data"
        )
    if (dividends.get("synthetic") is not True) or (splits.get("synthetic") is not True):
        raise ValidationError("synthetic corporate-action fixtures must declare synthetic=true")
    return {
        "bars": parse_daily(daily, security_id=security_id, mic=mic, source_id=source_id),
        "actions": parse_splits(splits, security_id=security_id, source_id=source_id)
        + parse_dividends(dividends, security_id=security_id, source_id=source_id),
        "meta": meta,
        "synthetic": True,
    }
