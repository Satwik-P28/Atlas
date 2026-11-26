#!/usr/bin/env python
"""Measure package build, install, verification and execution on this machine.

No number is invented. The report records the workload, package hash, environment
and whether each operation ran against a fresh database (cold) or a reused one.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.applications.contracts import read_package  # noqa: E402
from atlas.applications.service import ApplicationService  # noqa: E402
from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.economic.service import EconomicService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402


def _fresh(path: Path) -> Database:
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    return db


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase8_benchmark.json"))
    args = parser.parse_args()
    iterations = max(1, min(args.iterations, 10))
    package_path = ROOT / "fixtures" / "phase8" / "flagship_weather_demand.atlas"
    payload = package_path.read_bytes()
    loaded = read_package(payload)

    with tempfile.TemporaryDirectory(prefix="atlas-phase8-bench-") as directory:
        root = Path(directory)
        source = Database(root / "source.db")
        source.migrate()
        ensure_default_sources(source)
        economic = EconomicService(source)
        economic.bootstrap()
        run = economic.analyze(as_of="2026-11-05T23:59:59Z", persist=True)
        scenario = economic.scenario(run["run_id"])
        builder = ApplicationService(source)
        applications = {
            "run_id": run["run_id"],
            "scenario_id": scenario["scenario_id"],
        }
        build_times = []
        build_digests = []
        for _ in range(iterations):
            started = time.perf_counter()
            built = builder.create_economic_package(
                run["run_id"], scenario_id=scenario["scenario_id"]
            )
            build_times.append(_ms(started))
            build_digests.append(built["package_sha256"])
        assert len(set(build_digests)) == 1, "same run and inputs must build identical bytes"
        source.close()

        install_times, verify_times, execute_times = [], [], []
        for index in range(iterations):
            db = _fresh(root / f"install-{index}.db")
            try:
                service = ApplicationService(db)
                started = time.perf_counter()
                installed = service.install(payload)
                install_times.append(_ms(started))
                started = time.perf_counter()
                service.verify(installed["install_id"])
                verify_times.append(_ms(started))
                started = time.perf_counter()
                result = service.execute(installed["install_id"])
                execute_times.append(_ms(started))
                assert result["reproduced"] is True
            finally:
                db.close()

    def stats(values):
        return {
            "runs": len(values),
            "min_ms": round(min(values), 3),
            "median_ms": round(statistics.median(values), 3),
            "max_ms": round(max(values), 3),
        }

    report = {
        "schema": "atlas.phase8.benchmark.v1",
        "generated_at": iso(utcnow()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "cpu_count": __import__("os").cpu_count(),
        },
        "workload": {
            "package": str(package_path.relative_to(ROOT)),
            "package_sha256": loaded["package_sha256"],
            "package_bytes": len(payload),
            "files": len(loaded["manifest"]["files"]),
            "iterations": iterations,
            "run_id": applications["run_id"],
            "scenario_id": applications["scenario_id"],
            "cold_install": "each iteration uses a new SQLite database",
            "execution": "installed runtime reproduces the packaged panel and FEC scenario",
            "repeated_build_sha256": build_digests[0],
            "same_as_pinned_release_fixture": build_digests[0] == loaded["package_sha256"],
            "note": "A fresh analysis legitimately carries a new generated_at timestamp; the pinned fixture is the release artifact.",
        },
        "build": stats(build_times),
        "install": stats(install_times),
        "verify": stats(verify_times),
        "execute": stats(execute_times),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        "note": "Timings are machine-specific and exclude process startup and browser rendering.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
