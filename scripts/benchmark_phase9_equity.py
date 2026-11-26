#!/usr/bin/env python3
"""Measure the Phase 9 equity workflow on the real SEC fixture.

Every number written here is measured on this machine with ``perf_counter``. Nothing is
extrapolated or estimated: if a step is slow, the artifact says so.

Usage::

    python scripts/benchmark_phase9_equity.py --db var/phase9.db \
        --out artifacts/phase9_benchmarks.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.applications.service import ApplicationService  # noqa: E402
from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.equity import EquityResearchService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402


def _measure(function: Callable[[], Any], repeats: int = 3) -> dict[str, Any]:
    samples: list[float] = []
    value = None
    for _ in range(repeats):
        started = time.perf_counter()
        value = function()
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "repeats": repeats,
        "median_ms": round(statistics.median(samples), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
        "samples_ms": [round(sample, 3) for sample in samples],
        "_value": value,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "var" / "phase9.db"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase9_benchmarks.json"))
    parser.add_argument("--identifier", default="AAPL")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    db = Database(db_path, create=False)
    service = EquityResearchService(db)

    coverage = _measure(service.coverage, repeats=1)
    workspace = _measure(lambda: service.workspace(args.identifier), repeats=3)
    analysis = _measure(lambda: service.analyse(args.identifier), repeats=3)
    package = _measure(lambda: service.create_package(args.identifier), repeats=2)

    payload = package["_value"]["payload"]
    with tempfile.TemporaryDirectory() as folder:
        clean = Database(Path(folder) / "clean.db")
        clean.migrate()
        ensure_default_sources(clean)
        applications = ApplicationService(clean)
        install = _measure(lambda: applications.install(payload), repeats=2)
        install_id = install["_value"]["install_id"]
        execute = _measure(lambda: applications.execute(install_id), repeats=3)
        clean.close()

    report = analysis["_value"]["report"]
    issuers = coverage["_value"]["issuers"]
    for item in (coverage, workspace, analysis, package, install, execute):
        item.pop("_value", None)

    artifact = {
        "schema": "atlas.phase9.benchmarks.v1",
        "generated_at": iso(utcnow()),
        "database": str(db_path),
        "identifier": args.identifier,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "unreported",
        },
        "workload": {
            "issuers": issuers,
            "evidence_records": db.scalar("SELECT COUNT(*) FROM evidence", default=0),
            "filings": db.scalar("SELECT COUNT(*) FROM filing", default=0),
            "report_characters": len(report),
            "report_lines": report.count("\n") + 1,
            "package_bytes": len(payload),
        },
        "timings_ms": {
            "coverage_all_issuers": coverage,
            "workspace": workspace,
            "analyse_report_scenarios_sensitivity": analysis,
            "create_package": package,
            "install_package_clean_db": install,
            "execute_package_clean_db": execute,
        },
        "notes": [
            "Coverage runs the DCF core for every eligible issuer; it is the heaviest call.",
            "analyse includes the report, scenarios and the 5x5 sensitivity grid.",
            "Package timings exclude disk I/O for the caller's write; the bytes are held in memory.",
            "These are single-machine measurements, not service-level guarantees.",
        ],
    }
    db.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(out), "timings_ms": {
        key: value["median_ms"] for key, value in artifact["timings_ms"].items()
    }}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
