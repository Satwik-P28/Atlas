"""Measure read-path scaling across issuer/security universes.

This builds disposable in-memory databases with N issuers, one security each and a
deterministic price history, then times the company list (cold and cached), a screener
run and a market series. It deliberately contains no financial facts, so the screener
numbers measure read-model/kernel overhead rather than the cost of real evidence; the
Phase 2.1 readiness report states that limitation.

Usage: python scripts/benchmark_scale.py [--out artifacts/bench_phase21.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from atlas.entities.master import SecurityMaster
from atlas.market.bars import Bar, BarStore
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal import cache, read_models, screener

UNIVERSES = (5, 25, 100, 300)


def build(n: int) -> Database:
    db = Database(":memory:")
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq Global Select Market", country="US")
    start = date(2025, 1, 2)
    for index in range(n):
        issuer = master.register_issuer(
            legal_name=f"Scale Company {index:04d}",
            cik=f"{index + 1:010d}",
            source_id="atlas-synthetic",
        )
        security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
        listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01", is_primary=True)
        master.assign_ticker(
            listing, f"S{index:04d}", valid_from="2020-01-01", confidence=0.5,
            status="probable", source_id="atlas-synthetic",
        )
        bars = []
        price = Decimal("50") + Decimal(index % 97)
        for offset in range(180):
            day = start + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            drift = Decimal("1") + Decimal((offset % 7) - 3) / Decimal("500")
            price = max(Decimal("1"), price * drift)
            bars.append(
                Bar(
                    security_id=security,
                    mic="XNAS",
                    ts_utc=f"{day.isoformat()}T21:00:00Z",
                    open=price, high=price + 1, low=price - 1, close=price,
                    volume=Decimal("1000000"), currency="USD",
                    source_id="atlas-synthetic", observed_at=f"{day.isoformat()}T21:05:00Z",
                )
            )
        BarStore(db).ingest(bars)
    return db


def timed(callable_, repeats: int = 3) -> tuple[list[float], object]:
    samples = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = callable_()
        samples.append(round((time.perf_counter() - started) * 1000, 1))
    return samples, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "bench_phase21.json"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    results = []
    for n in UNIVERSES:
        built = time.perf_counter()
        db = build(n)
        build_ms = round((time.perf_counter() - built) * 1000, 1)
        cache.clear()
        cold, companies = timed(lambda: read_models.list_companies(db, limit=500), repeats=1)
        warm, _ = timed(lambda: read_models.list_companies(db, limit=500), repeats=args.repeats)
        screen, screen_result = timed(lambda: screener.run_screener(db, limit=50), repeats=1)
        first_security = companies[0]["securities"][0]["security_id"]
        market, market_result = timed(
            lambda: read_models.market_series(db, first_security, range_key="6M"), repeats=1
        )
        results.append(
            {
                "issuers": n,
                "securities": sum(len(company["securities"]) for company in companies),
                "bars": int(db.scalar("SELECT COUNT(*) FROM bar") or 0),
                "build_ms": build_ms,
                "companies_cold_ms": cold[0],
                "companies_cached_ms": round(statistics.median(warm), 1),
                "screener_ms": screen[0],
                "screen_rows": screen_result["matched"],
                "market_startup_ms": market[0],
                "market_bar_rows": len(market_result["bars"]),
                "db_bytes": int(db.scalar("PRAGMA page_count") or 0)
                * int(db.scalar("PRAGMA page_size") or 0),
            }
        )
        db.close()
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "notes": [
            "Disposable in-memory databases; one security per issuer; 180 calendar days of synthetic bars.",
            "No financial facts are inserted, so screener time measures read-model and kernel overhead, not evidence selection.",
            "Cold company list clears the process cache first; cached is the median of repeated runs.",
        ],
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
