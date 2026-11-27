#!/usr/bin/env python3
"""Benchmark SEC company-facts integration against the stored archive.

Measures throughput, peak resident memory, database and index growth, and query
latency for the staged integration limits. Every figure is measured in this
process, so the artifact can be regenerated rather than trusted.

The checkpoint is the contract between stages: each run resumes from the number
of issuers already committed. ``--restart`` ignores it; ``--max-seconds`` stops
cleanly so a resume can be demonstrated.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.engine import AcquisitionEngine  # noqa: E402
from atlas.open_data.integration import integrate_companyfacts  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    total = path.stat().st_size
    for suffix in ("-wal", "-shm"):
        companion = Path(str(path) + suffix)
        if companion.exists():
            total += companion.stat().st_size
    return total


def _timed(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> dict:
    started = time.perf_counter()
    rows = connection.execute(sql, params).fetchall()
    return {"ms": round((time.perf_counter() - started) * 1000, 3), "rows": len(rows)}


def _queries(atlas_db: Path) -> dict:
    if not atlas_db.exists():
        return {}
    connection = sqlite3.connect(f"file:{atlas_db}?mode=ro", uri=True)
    try:
        results = {
            "count_evidence": _timed(connection, "SELECT COUNT(*) FROM evidence"),
            "issuer_facts": _timed(
                connection,
                "SELECT entity_id, COUNT(*) FROM evidence GROUP BY entity_id "
                "ORDER BY COUNT(*) DESC LIMIT 25"),
            "recent_facts": _timed(
                connection,
                "SELECT entity_id, period_end, value_numeric FROM evidence "
                "ORDER BY period_end DESC LIMIT 100"),
            "restatements": _timed(
                connection,
                "SELECT COUNT(*) FROM evidence WHERE supersedes IS NOT NULL "
                "AND supersedes != ''"),
        }
    except sqlite3.Error as exc:
        results["error"] = str(exc)
    finally:
        connection.close()
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-root", default="/tmp/atlas_open_data")
    parser.add_argument("--open-db", default="/tmp/atlas_open_data/index.db")
    parser.add_argument("--atlas-db", default="var/atlas.db")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--out", default="artifacts/open_data_integration_bench.json")
    args = parser.parse_args(argv)

    atlas_db = Path(args.atlas_db)
    before = _size(atlas_db)
    engine = AcquisitionEngine(store_root=args.open_root, index_path=args.open_db)
    try:
        started = time.perf_counter()
        result = integrate_companyfacts(
            engine, str(atlas_db), limit=args.limit, batch_size=args.batch_size,
            restart=args.restart, max_seconds=args.max_seconds,
        )
        elapsed = time.perf_counter() - started
    finally:
        engine.close()
    after = _size(atlas_db)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    inserted = int(result.get("evidence_inserted_total") or 0)
    issuers = int(result.get("eligible_total") or 0)
    payload = {
        "schema": "atlas.open_data.integration_bench.v1",
        "generated_at": utcnow(),
        "limit": args.limit,
        "batch_size": args.batch_size,
        "restart": args.restart,
        "max_seconds": args.max_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "peak_rss_mb": round(peak, 1),
        "atlas_db_bytes_before": before,
        "atlas_db_bytes_after": after,
        "atlas_db_growth_bytes": after - before,
        "evidence_rows_reported": inserted,
        "issuers_reported": issuers,
        "companies_processed": result.get("companies_total"),
        "records_parsed": result.get("records_parsed_total"),
        "duplicates": result.get("evidence_duplicates_total"),
        "rejected": result.get("evidence_rejected_total"),
        "supersessions": result.get("supersessions_total"),
        "stopped_reason": result.get("stopped_reason"),
        "resumed_from": result.get("resumed_from"),
        "facts_per_second": round(inserted / elapsed, 1) if elapsed else None,
        "issuers_per_second": round(issuers / elapsed, 3) if elapsed else None,
        "result": result,
        "queries": _queries(atlas_db),
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                      encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "elapsed_seconds", "peak_rss_mb", "atlas_db_growth_bytes",
        "evidence_rows_reported", "issuers_reported", "facts_per_second")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
