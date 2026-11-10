"""Phase 9.3.1 memo and export benchmark.

Measures the cost the report path adds over the existing equity analysis: memo build, claim
verification, citation resolution, research-object save, reopen, the three exports and the
change check. Statements are counted by wrapping the database helpers; memory is the
tracemalloc peak of the measured call. Nothing here claims a speedup — there is no earlier
memo implementation to compare against.

Run: .venv/bin/python scripts/benchmark_research_memo.py --db var/phase9.db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research.memo import ResearchMemoService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

ITERATIONS = 5


def _wrap(db: Database) -> dict[str, int]:
    counter = {"statements": 0}
    for name in ("execute", "executemany", "query", "query_one"):
        original = getattr(db, name)

        def counted(*args, _original=original, **kwargs):
            counter["statements"] += 1
            return _original(*args, **kwargs)

        setattr(db, name, counted)
    return counter


def _measure(call: Callable[[], Any], counter: dict[str, int]) -> dict[str, Any]:
    timings, statements, peaks = [], [], []
    result = None
    for _ in range(ITERATIONS):
        before = counter["statements"]
        tracemalloc.start()
        started = time.perf_counter()
        result = call()
        elapsed = (time.perf_counter() - started) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        timings.append(elapsed)
        statements.append(counter["statements"] - before)
        peaks.append(peak / 1_048_576)
    ordered = sorted(timings)
    return {
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(ordered[max(0, int(round(0.95 * (len(ordered) - 1))))], 3),
        "min_ms": round(min(timings), 3),
        "max_ms": round(max(timings), 3),
        "sql_statements": max(statements),
        "peak_mib": round(max(peaks), 3),
        "iterations": ITERATIONS,
        "result": result,
    }


def _dataset(db: Database) -> dict[str, Any]:
    row = db.query_one("SELECT COUNT(*) AS n FROM evidence")
    return {
        "db": str(db.path),
        "evidence_records": int(row["n"]) if row else 0,
        "schema_version": int(db.query_one("SELECT MAX(version) AS v FROM schema_migration")["v"]),
    }


def _run(db_path: str, ticker: str) -> dict[str, Any]:
    db = Database(db_path)
    counter = _wrap(db)
    service = ResearchMemoService(db)
    cold = _measure(lambda: service.build(ticker), counter)
    memo = cold.pop("result")
    warm_service = ResearchMemoService(db)
    warm = _measure(lambda: ResearchMemoService(db).build(ticker), counter)
    warm.pop("result")

    base = int(time.time()) % 100000
    saved = service.save(memo, version=f"1.0.{base}")
    object_id = saved["object_id"]
    versions = {"n": 0}

    def save_once():
        # Each iteration stores a new immutable version: reusing a version is refused by design.
        versions["n"] += 1
        return service.save(memo, version=f"1.0.{base + versions['n']}")

    save_repeat = _measure(save_once, counter)
    save_repeat.pop("result")
    reopen = _measure(lambda: service.get(object_id), counter)
    reopen.pop("result")
    exports = {}
    for format in ("markdown", "html", "json"):
        measured = _measure(lambda f=format: service.export(object_id, format=f), counter)
        payload = measured.pop("result")
        exports[format] = {
            **measured,
            "bytes": len(payload["content"].encode("utf-8")),
            "content_sha256": hashlib.sha256(payload["content"].encode("utf-8")).hexdigest(),
        }
    changes = _measure(lambda: service.check_changes(object_id), counter)
    report = changes.pop("result")
    return {
        "ticker": ticker,
        "claims": len(memo["claims"]),
        "evidence_dependencies": len(memo["manifest"]["evidence_dependencies"]),
        "model_fingerprints": len(memo["manifest"]["model_fingerprints"]),
        "sections": len(memo["sections"]),
        "memo_content_hash": memo["content_hash"],
        "object_id": object_id,
        "build_cold": cold,
        "build_warm": warm,
        "save_repeat": save_repeat,
        "reopen": reopen,
        "export": exports,
        "change_check": {**changes, "status": report["status"],
                          "findings": len(report["findings"])},
        "_db": db,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument("--out", default="artifacts/research_memo_benchmark.json")
    args = parser.parse_args()

    probe = Database(args.db)
    dataset = _dataset(probe)
    results = []
    for ticker in ("JPM", "AAPL"):
        measured = _run(args.db, ticker)
        measured.pop("_db", None)
        results.append(measured)
        print(f"{ticker}: {measured['claims']} claims, build {measured['build_cold']['median_ms']} ms, "
              f"save {measured['save_repeat']['median_ms']} ms, "
              f"check {measured['change_check']['median_ms']} ms")

    payload = {
        "schema": "atlas.research_memo_benchmark.v1",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
        },
        "method": {
            "iterations": ITERATIONS,
            "statistics": "median and nearest-rank p95 of wall-clock milliseconds",
            "statements": "database helper calls per iteration",
            "memory": "tracemalloc peak per iteration",
            "warm_definition": "a new service instance over the same database and caches",
            "caveat": "no earlier memo implementation exists, so this is not a speedup claim",
        },
        "dataset": dataset,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"dataset": dataset, "out": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
