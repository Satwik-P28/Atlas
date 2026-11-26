#!/usr/bin/env python
"""Build the Phase 6 learning database from authorized demo market records.

The five symbols below are the ones that resolved against EODHD's *documented demo*
token during the Phase 6 audit. Their bytes are cached under ``var/phase6-eodhd``
and are deliberately outside version control because the vendor's demo terms do
not grant redistribution. Re-running the script is the supported way to reproduce
the local demonstration; a clean checkout without network access has no vendor
rows and the Learning Lab reports that honestly.

The imported window starts after the last split in the sample (AMZN 2022-06,
TSLA 2022-08). Raw closes are used, so dividends are not included. The panel is
labelled ``observed`` but not ``point_in_time_verified``.

Usage:
    python scripts/build_phase6_db.py [--db var/atlas-phase6.db] [--force] [--offline]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.entities.master import SecurityMaster  # noqa: E402
from atlas.market.bars import Bar, BarStore  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import SourceRegistry  # noqa: E402

SOURCE_ID = "eodhd-demo"
START = "2023-01-01"
END = "2025-12-31"
MIC = "XNAS"
SYMBOLS = (
    ("AAPL.US", "Apple Inc.", "AAPL", "common_stock"),
    ("MSFT.US", "Microsoft Corporation", "MSFT", "common_stock"),
    ("TSLA.US", "Tesla, Inc.", "TSLA", "common_stock"),
    ("VTI.US", "Vanguard Total Stock Market ETF", "VTI", "etf"),
    ("AMZN.US", "Amazon.com, Inc.", "AMZN", "common_stock"),
)
URL = "https://eodhd.com/api/eod/{symbol}?api_token=demo&fmt=json&from={start}&to={end}"


def fetch(symbol: str, cache: Path, *, offline: bool) -> tuple[list[dict], Path]:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{symbol}.json"
    if not path.exists():
        if offline:
            raise SystemExit(f"missing cached demo data: {path}")
        request = urllib.request.Request(
            URL.format(symbol=symbol, start=START, end=END),
            headers={"User-Agent": "Atlas-Quant/0.3 Phase6 research contact local"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed vendor URL
            body = response.read()
        if not body.startswith(b"["):
            raise SystemExit(f"provider returned no rows for {symbol}: {body[:160]!r}")
        path.write_bytes(body)
        time.sleep(0.4)
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or len(rows) < 500:
        raise SystemExit(f"insufficient demo history for {symbol}: {len(rows) if isinstance(rows, list) else 'not a list'}")
    return rows, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "var" / "atlas-phase6.db"))
    parser.add_argument("--cache", default=str(ROOT / "var" / "phase6-eodhd"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    path = Path(args.db)
    if path.exists():
        if not args.force:
            print(f"database already exists: {path} (use --force)", file=sys.stderr)
            return 1
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    print(f"schema migrations: {db.migrate()}", flush=True)
    SourceRegistry(db).ensure_custom(
        "EODHD demo market observations",
        kind="market_data",
        homepage="https://eodhd.com/financial-apis/",
        licence="EODHD demo terms; local research only; no redistribution asserted",
        redistribution="restricted",
        notes="Five documented demo symbols cached locally; not a licensed full-market feed.",
        source_id=SOURCE_ID,
    )
    master = SecurityMaster(db)
    master.ensure_venue(MIC, "Nasdaq Global Select Market", country="US", timezone="America/New_York")
    bars_written = 0
    observed = iso(utcnow())
    for symbol, name, ticker, security_type in SYMBOLS:
        rows, cache_path = fetch(symbol, Path(args.cache), offline=args.offline)
        issuer = master.register_issuer(legal_name=name, source_id=SOURCE_ID)
        security = master.ensure_security(
            issuer, class_designation="common stock" if security_type == "common_stock" else "ETF shares",
            security_type=security_type, currency="USD", source_id=SOURCE_ID,
        )
        listing = master.ensure_listing(security, MIC, valid_from="2020-01-02", is_primary=True,
                                        source_id=SOURCE_ID)
        master.assign_ticker(listing, ticker, valid_from="2020-01-02", confidence=1.0,
                             status="confirmed", source_id=SOURCE_ID,
                             evidence_note="EODHD demo symbol mapping; demo entitlement")
        bars = []
        for row in rows:
            day = str(row.get("date", ""))
            if not day or day < START or day > END:
                continue
            try:
                open_, high, low, close = (Decimal(str(row[key])) for key in ("open", "high", "low", "close"))
                volume = Decimal(str(row.get("volume", 0)))
            except Exception as exc:  # noqa: BLE001 - malformed vendor row is a hard error
                raise SystemExit(f"bad row for {symbol} on {day}: {exc}") from exc
            bars.append(Bar(
                security_id=security, mic=MIC, ts_utc=f"{day}T21:00:00Z",
                open=open_, high=high, low=low, close=close, volume=volume,
                currency="USD", source_id=SOURCE_ID, observed_at=observed,
            ))
        summary = BarStore(db).ingest(bars, observed_at=observed)
        bars_written += summary.inserted
        print(f"  {symbol}: {summary.inserted} bars from {cache_path.name}", flush=True)
    counts = db.query_one(
        "SELECT COUNT(DISTINCT security_id) AS securities, COUNT(*) AS bars, "
        "MIN(ts_utc) AS first, MAX(ts_utc) AS last FROM bar WHERE source_id = ?", (SOURCE_ID,)
    )
    print(json.dumps({"database": str(path), "schema_version": db.schema_version(),
                      "source_id": SOURCE_ID, "bars_written": bars_written,
                      **dict(counts)}, indent=2))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
