"""Provider-independent market-data layer.

Atlas does not redistribute market prices. The research below found no provider whose
terms permit unrestricted public redistribution of exchange OHLCV, so the registry keeps
``market.equity_ohlcv`` restricted and this module provides the two lawful paths:

1. a **local import** of a file the user is authorised to hold, stored as a source with
   ``redistribution=user_responsibility`` and never packaged for release;
2. an **API adapter** the user authorises with their own credentials.

Synthetic, simulated or demo prices are refused for production observations. They may be
loaded only into an explicitly labelled demonstration database with ``allow_synthetic``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ingestion.market_csv import import_csv_bars, import_parquet_bars
from ..market.bars import BarStore
from ..market.calendar import TradingCalendar
from ..storage.db import Database, open_database
from ..storage.sources import SourceRegistry

SYNTHETIC_MARKERS = ("synthetic", "simulated", "simulation", "mock", "fake", "demo", "fixture")


@dataclass(frozen=True, slots=True)
class MarketProvider:
    id: str
    name: str
    homepage: str
    rights_class: str
    redistribution: bool
    commercial_use: bool
    requires_key: bool
    status: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "homepage": self.homepage,
            "rights_class": self.rights_class, "redistribution": self.redistribution,
            "commercial_use": self.commercial_use, "requires_key": self.requires_key,
            "status": self.status, "notes": self.notes,
        }


PROVIDERS: tuple[MarketProvider, ...] = (
    MarketProvider(
        id="local-import", name="User-authorised local file", homepage="",
        rights_class="local_use_only", redistribution=False, commercial_use=True,
        requires_key=False, status="implemented",
        notes=("CSV or Parquet the user already has the right to use. Atlas records the "
               "declared licence and never includes the bars in a public package."),
    ),
    MarketProvider(
        id="alphavantage", name="Alpha Vantage", homepage="https://www.alphavantage.co/",
        rights_class="restricted", redistribution=False, commercial_use=False,
        requires_key=True, status="adapter-available",
        notes=("Existing Atlas ingestion adapter. Use requires the user's own API key and "
               "acceptance of the provider terms; bars stay local."),
    ),
    MarketProvider(
        id="stooq", name="Stooq", homepage="https://stooq.com/",
        rights_class="unverified", redistribution=False, commercial_use=False,
        requires_key=False, status="not-adopted",
        notes=("Downloadable end-of-day files, but no explicit redistribution grant was found. "
               "Not used for production observations or release packages."),
    ),
    MarketProvider(
        id="exchange-direct", name="Exchange direct feed", homepage="",
        rights_class="restricted", redistribution=False, commercial_use=False,
        requires_key=True, status="requires-licence",
        notes=("Exchange and SIP feeds are licensed per user and forbid redistribution; "
               "Atlas has no licence and does not mirror them."),
    ),
)


def provider_catalog() -> dict[str, Any]:
    return {
        "schema": "atlas.open_data.market_providers.v1",
        "finding": (
            "No investigated provider establishes unrestricted public redistribution of "
            "equity OHLCV, dividends, splits or delisting histories. Atlas therefore "
            "implements a provider-independent local/authorised layer and does not publish "
            "price data."
        ),
        "redistributable_provider_found": False,
        "providers": [provider.to_dict() for provider in PROVIDERS],
    }


def _contains_synthetic(*values: str | None) -> str | None:
    for value in values:
        text = str(value or "").lower()
        for marker in SYNTHETIC_MARKERS:
            if marker in text:
                return marker
    return None


def import_local(
    atlas_db: str | Path,
    file: str | Path,
    *,
    security_id: str,
    mic: str,
    currency: str = "USD",
    source_name: str = "user-authorised local market import",
    licence: str | None = None,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """Import raw OHLCV bars, keeping provenance and refusing fake production prices."""
    path = Path(file)
    if not path.exists():
        raise FileNotFoundError(f"market file does not exist: {path}")
    marker = _contains_synthetic(source_name, licence, path.name)
    if marker and not allow_synthetic:
        raise ValueError(
            f"refusing synthetic market data ({marker!r}) as a production observation; "
            "pass allow_synthetic only for an explicitly labelled demonstration"
        )
    db = open_database(atlas_db)
    try:
        source_id = SourceRegistry(db).ensure_custom(
            source_name,
            kind="csv_import" if path.suffix.lower() != ".parquet" else "parquet_import",
            licence=licence,
            redistribution="user_responsibility",
            notes="provider-independent market import; not redistributed by Atlas",
        )
        calendar = TradingCalendar(db)
        try:
            calendar.ensure_venue(mic)
        except Exception:  # noqa: BLE001 - unknown venue is recorded, not invented
            calendar = None
        importer = import_parquet_bars if path.suffix.lower() == ".parquet" else import_csv_bars
        result = importer(path, security_id=security_id, mic=mic, source_id=source_id,
                          currency=currency, calendar=calendar)
        summary = BarStore(db).ingest(result.bars)
        return {
            "schema": "atlas.open_data.market_import.v1",
            "file": str(path),
            "security_id": security_id,
            "mic": mic.upper(),
            "source_id": source_id,
            "synthetic": bool(marker),
            "bars_parsed": len(result.bars),
            "bars_ingested": getattr(summary, "inserted", None),
            "rejected": getattr(summary, "rejected", None),
            "redistribution": "user_responsibility",
            "release_eligible": False,
            "licence": licence,
        }
    finally:
        db.close()
