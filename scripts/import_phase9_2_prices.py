#!/usr/bin/env python
"""Import observed daily prices with explicit restricted redistribution terms.

This script imports local CSV rows only. It performs no network collection. Any file that
originated from a vendor remains restricted unless the user can point to terms that
authorize retention and analysis; redistribution is never granted by a ``restricted``
label. Research packages exclude these observations.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research.prices import import_price_series  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

MARKET = ROOT / "fixtures" / "market"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument("--tickers", default="JPM,GS,UNH,AAPL,AMZN")
    args = parser.parse_args()
    path = Path(args.db)
    if not path.is_absolute():
        path = ROOT / path
    manifest = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
    db = Database(path)
    db.migrate()
    results = []
    for ticker in [item.strip().upper() for item in args.tickers.split(",") if item.strip()]:
        csv_path = MARKET / f"nasdaq_{ticker}.csv"
        if not csv_path.exists():
            results.append({"ticker": ticker, "status": "fixture_missing"})
            continue
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        imported = import_price_series(
            db,
            ticker=ticker,
            rows=rows,
            source_name=f"Nasdaq quote history ({ticker})",
            licence=manifest["licence"],
            redistribution="restricted",
            adjustment_semantics=manifest["adjustment_semantics"],
            retrieved_at=manifest["retrieved_at"],
            currency="USD",
        )
        results.append({"ticker": ticker, **imported})
    print(json.dumps({
        "schema": "atlas.market_data.bootstrap.v1",
        "database": str(path),
        "results": results,
        "rights_note": (
            "Restricted observations remain local. They are not exported in research "
            "packages and must be reconnected from the provider by the user."
        ),
    }, indent=2, sort_keys=True))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
