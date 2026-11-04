"""Reproducible Phase 1 benchmarks.

Every number this script prints is measured in the current environment; nothing is
estimated. Run it with:

    .venv/bin/python benchmarks/bench.py --json benchmarks/out/bench.json

The script reports the median of repeated runs, plus min/max, so variance is visible.
Hardware and dataset sizes are captured with the results because a latency figure
without them is not a measurement.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import availability_from_instant  # noqa: E402
from atlas.entities.master import SecurityMaster  # noqa: E402
from atlas.evidence.kernel import EvidenceKernel  # noqa: E402
from atlas.ingestion.sec_sync import SecIngestor  # noqa: E402
from atlas.market.bars import Bar, BarStore  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402

FIXTURES = ROOT / "fixtures"
APPLE_CIK = "0000320193"


def hardware() -> dict[str, object]:
    cpu = "unknown"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    memory_kb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal"):
                    memory_kb = int(line.split()[1])
                    break
    except OSError:
        pass
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
        "memory_gb": round(memory_kb / 1024 / 1024, 1) if memory_kb else None,
        "storage": "local filesystem, SQLite WAL, synchronous=FULL",
    }


def timed(fn, *, repeats: int, warmup: int = 1) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "median_ms": round(statistics.median(samples), 2),
        "min_ms": round(min(samples), 2),
        "max_ms": round(max(samples), 2),
        "repeats": repeats,
    }


def fresh_db(directory: Path, name: str) -> Database:
    path = directory / name
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    database = Database(path)
    database.migrate()
    ensure_default_sources(database)
    return database


def synthetic_bars(security_id: str, count: int) -> list[Bar]:
    bars: list[Bar] = []
    day = date(2019, 1, 2)
    price = Decimal("100")
    index = 0
    while len(bars) < count:
        if day.weekday() < 5:
            price = price + Decimal("0.05")
            bars.append(
                Bar(
                    security_id=security_id,
                    mic="XNAS",
                    ts_utc=f"{day.isoformat()}T20:00:00Z",
                    open=price,
                    high=price + Decimal("0.10"),
                    low=price - Decimal("0.10"),
                    close=price,
                    volume=Decimal("100000") + index,
                    currency="USD",
                    source_id="atlas-synthetic",
                )
            )
            index += 1
        day += timedelta(days=1)
    return bars


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    results: dict[str, object] = {"hardware": hardware(), "benchmarks": {}, "datasets": {}}
    with tempfile.TemporaryDirectory(prefix="atlas-bench-") as tmp:
        directory = Path(tmp)

        # ---------------------------------------------------------------- SEC ingestion
        submissions = json.loads((FIXTURES / "sec" / "submissions_CIK0000320193.json").read_text())
        facts = json.loads((FIXTURES / "sec" / "companyfacts_CIK0000320193.json").read_text())

        def ingest_sec() -> None:
            database = fresh_db(directory, "sec.db")
            try:
                SecIngestor(database).sync_payloads(
                    APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts
                )
            finally:
                database.close()

        results["benchmarks"]["sec_ingest_companyfacts"] = timed(ingest_sec, repeats=min(args.repeats, 3))

        database = fresh_db(directory, "query.db")
        try:
            report = SecIngestor(database).sync_payloads(
                APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts
            )
            kernel = EvidenceKernel(database)
            results["datasets"]["sec_facts_ingested"] = kernel.count()
            results["datasets"]["filings"] = report.filings_written
            results["datasets"]["filings_in_payload"] = len(submissions["filings"]["recent"]["accessionNumber"])

            results["benchmarks"]["statement_query_4_concepts"] = timed(
                lambda: kernel.as_of(
                    report.issuer_id, "2026-01-01T00:00:00Z",
                    concepts=["revenue", "net_income", "assets", "operating_cash_flow"],
                ),
                repeats=args.repeats,
            )
            # Two independent implementations of the same selection policy. Measured
            # side by side so an engine is only adopted on evidence, not intuition.
            results["benchmarks"]["selection_python_all_concepts"] = timed(
                lambda: kernel.as_of(report.issuer_id, "2022-06-30T00:00:00Z", engine="python"),
                repeats=args.repeats,
            )
            results["benchmarks"]["selection_sql_all_concepts"] = timed(
                lambda: kernel.as_of(report.issuer_id, "2022-06-30T00:00:00Z", engine="sql"),
                repeats=args.repeats,
            )
            results["benchmarks"]["selection_python_four_concepts"] = timed(
                lambda: kernel.as_of(
                    report.issuer_id,
                    "2026-01-01T00:00:00Z",
                    concepts=["revenue", "net_income", "assets", "operating_cash_flow"],
                    engine="python",
                ),
                repeats=args.repeats,
            )
            results["benchmarks"]["selection_sql_four_concepts"] = timed(
                lambda: kernel.as_of(
                    report.issuer_id,
                    "2026-01-01T00:00:00Z",
                    concepts=["revenue", "net_income", "assets", "operating_cash_flow"],
                    engine="sql",
                ),
                repeats=args.repeats,
            )
            results["benchmarks"]["history_single_concept"] = timed(
                lambda: kernel.history(report.issuer_id, "revenue"), repeats=args.repeats
            )
            sample = database.query_one(
                "SELECT evidence_id FROM evidence WHERE entity_id = ? AND concept = 'revenue' "
                "ORDER BY period_end DESC LIMIT 1",
                (report.issuer_id,),
            )
            results["benchmarks"]["provenance_traversal"] = timed(
                lambda: kernel.provenance(sample["evidence_id"]), repeats=args.repeats
            )

            # ----------------------------------------------------------- market bars
            master = SecurityMaster(database)
            issuer = master.register_issuer(legal_name="Benchmark Corp", cik="1930001")
            security = master.ensure_security(issuer, class_designation="common stock")
            master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
            bars = synthetic_bars(security, 1250)
            store = BarStore(database)
            results["datasets"]["bars"] = len(bars)
            results["benchmarks"]["market_bar_load_1250"] = timed(
                lambda: store.ingest(bars, flag_issues=False), repeats=1, warmup=0
            )
            results["benchmarks"]["multi_year_bar_query"] = timed(
                lambda: store.query(security, "XNAS", "2019-01-01", "2023-12-31"),
                repeats=args.repeats,
            )

            # ------------------------------------------------------ entity resolution
            for index in range(500):
                resolved_issuer = master.register_issuer(
                    legal_name=f"Bench Issuer {index}", cik=f"18{index:06d}"
                )
                resolved_security = master.ensure_security(resolved_issuer, class_designation="common stock")
                listing = master.ensure_listing(resolved_security, "XNAS", valid_from="2020-01-01")
                master.assign_ticker(listing, f"BN{index:04d}", valid_from="2020-01-01", status="confirmed")
            results["datasets"]["securities"] = 501
            results["benchmarks"]["entity_resolution_500_tickers"] = timed(
                lambda: [master.resolve_ticker(f"BN{index:04d}", as_of="2021-01-01") for index in range(500)],
                repeats=1,
                warmup=0,
            )
        finally:
            database.close()

    anthropic = results["benchmarks"]
    print("Atlas Phase 1 benchmarks")
    print("=" * 78)
    for key, value in results["hardware"].items():
        print(f"{key:14} {value}")
    print()
    print(f"{'benchmark':44} {'median':>10} {'min':>9} {'max':>9}  n")
    print("-" * 78)
    for name, measurement in anthropic.items():
        print(
            f"{name:44} {measurement['median_ms']:>10} {measurement['min_ms']:>9} "
            f"{measurement['max_ms']:>9}  {measurement['repeats']}"
        )
    print()
    print("datasets:", json.dumps(results["datasets"], indent=2))

    if args.json_path:
        output = Path(args.json_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
