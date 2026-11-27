#!/usr/bin/env python3
"""Benchmark representative research workloads on a built columnar dataset.

Runs against whatever dataset root it is given, so the same script measures the
500-company comparison set and the full SEC universe. It reports cold (first query in
the process) and warm latencies separately, because DuckDB and the OS page cache make
the first read the honest cold number.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.open_data.columnar import ColumnarEvidence, totals  # noqa: E402


def _timed(call):
    started = time.perf_counter()
    value = call()
    return value, (time.perf_counter() - started) * 1000.0


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "count": len(samples),
        "mean_ms": round(statistics.fmean(samples), 3),
        "p50_ms": round(ordered[len(ordered) // 2], 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max_ms": round(ordered[-1], 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="columnar dataset root")
    parser.add_argument("--out", default="artifacts/open_data_full_universe.json")
    parser.add_argument("--companies", type=int, default=20, help="random company lookups")
    parser.add_argument("--fiscal-year", type=int, default=2024)
    parser.add_argument("--seed", type=int, default=20261126)
    args = parser.parse_args(argv)

    root = Path(args.root)
    started = time.perf_counter()
    evidence = ColumnarEvidence(root)
    open_ms = (time.perf_counter() - started) * 1000.0
    stored = totals(root)

    ciks = evidence.conn.execute(
        "SELECT DISTINCT cik FROM fact ORDER BY cik").fetchall()
    ciks = [row[0] for row in ciks]
    random.Random(args.seed).shuffle(ciks)
    sample = ciks[:args.companies]

    company_times: list[float] = []
    rows_seen = 0
    for cik in sample:
        rows, millis = _timed(lambda c=cik: evidence.company(c))
        rows_seen += len(rows)
        company_times.append(millis)

    repeat_times: list[float] = []
    for index, cik in enumerate(sample):
        if index % 4:
            continue
        _, millis = _timed(lambda c=cik: evidence.company(c))
        repeat_times.append(millis)

    statement_times: list[float] = []
    statements = 0
    for cik in sample:
        rows = evidence.company(cik)
        if not rows:
            continue
        result, millis = _timed(lambda c=cik, p=rows[0]["period_end"]:
                                evidence.statement(c, period_end=p))
        statements += bool(result.get("concepts"))
        statement_times.append(millis)

    screen, screen_ms = _timed(lambda: evidence.screen(
        concept="revenue", fiscal_year=args.fiscal_year, limit=100))

    pit_times: list[float] = []
    for cik in sample[:5]:
        _, millis = _timed(lambda c=cik: evidence.point_in_time(c, "2023-01-01T00:00:00Z"))
        pit_times.append(millis)

    restatement_times: list[float] = []
    for cik in sample[:5]:
        _, millis = _timed(lambda c=cik: evidence.restatements(c))
        restatement_times.append(millis)

    evidence.close()

    payload = {
        "schema": "atlas.open_data.full_universe_benchmark.v1",
        "generated_at": iso(utcnow()),
        "root": str(root),
        "stored": stored,
        "open_ms": round(open_ms, 3),
        "ciks": len(ciks),
        "companies_queried": len(sample),
        "rows_returned": rows_seen,
        "company_lookup": _summary(company_times),
        "company_lookup_warm": _summary(repeat_times) if repeat_times else None,
        "statement": _summary(statement_times) if statement_times else None,
        "statements_with_concepts": statements,
        "screen": {"concept": "revenue", "fiscal_year": args.fiscal_year,
                   "rows": len(screen), "ms": round(screen_ms, 3),
                   "top": screen[:5]},
        "point_in_time": _summary(pit_times) if pit_times else None,
        "restatements": _summary(restatement_times) if restatement_times else None,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
