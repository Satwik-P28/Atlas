#!/usr/bin/env python3
"""Measure the Phase 7 economic research workload on the committed public panel.

The benchmark uses the real fixture, a temporary SQLite database and the same code paths as
the API. It records cold and warm wall-clock timings, Monte Carlo throughput and peak RSS.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.economic.service import EconomicService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402


def once(fn: Callable[[], Any]) -> tuple[Any, float]:
    gc.collect()
    started = time.perf_counter()
    value = fn()
    return value, round((time.perf_counter() - started) * 1000, 3)


def warm(fn: Callable[[], Any], repeats: int = 7) -> tuple[Any, dict[str, float]]:
    once(fn)
    samples = []
    value = None
    for _ in range(repeats):
        value, elapsed = once(fn)
        samples.append(elapsed)
    return value, {
        "median_ms": round(statistics.median(samples), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
        "samples": samples,
    }


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase7_benchmarks.json"))
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "phase7-benchmark.db"
        db = Database(path)
        _, migration_ms = once(db.migrate)
        ensure_default_sources(db)
        service = EconomicService(db)
        cold_started = time.perf_counter()
        service.bootstrap()
        cold_ingest_ms = round((time.perf_counter() - cold_started) * 1000, 3)

        catalog = service.catalog()
        panel_cold, panel_cold_ms = once(lambda: service.panel(as_of=iso(utcnow())))
        panel_warm, panel_warm_stats = warm(
            lambda: service.panel(as_of=iso(utcnow())), args.repeats
        )
        graph_cold, graph_cold_ms = once(lambda: service.graph(entity_id="EENT-REGION-ERCO", depth=2))
        graph_warm, graph_warm_stats = warm(
            lambda: service.graph(entity_id="EENT-REGION-ERCO", depth=2), args.repeats
        )
        _, geographic_ms = once(lambda: db.query(
            "SELECT o.series_id, COUNT(*) FROM economic_observation o "
            "JOIN economic_series s ON s.series_id = o.series_id "
            "JOIN economic_entity e ON e.geography_code = s.geography_code "
            "GROUP BY o.series_id"
        ))
        _, model_ms = once(lambda: service.analyze(as_of=iso(utcnow()), persist=False))
        run, persist_ms = once(lambda: service.analyze(as_of=iso(utcnow()), persist=True))
        scenario, scenario_ms = once(lambda: service.scenario(run["run_id"], draws=2000))

        def monte_carlo_10k() -> dict:
            return service.scenario(run["run_id"], draws=10_000)

        scenario_10k, scenario_10k_ms = once(monte_carlo_10k)
        _, sentinel_ms = once(service.sentinel_refresh)
        _, replay_ms = once(lambda: service.replay(run["run_id"], as_of=iso(utcnow())))
        _, memory_ms = once(service.memory)
        application, save_ms = once(lambda: service.save_application(
            run["run_id"], scenario_id=scenario["scenario_id"],
            name="Phase 7 benchmark application", purpose="measured restoration workload",
        ))
        _, restore_ms = once(lambda: service.objects.get(application["object_id"]))
        _, export_ms = once(lambda: service.objects.export_manifest(application["object_id"]))
        run_json = json.dumps(run, sort_keys=True, default=str)
        scenario_json = json.dumps(scenario, sort_keys=True, default=str)
        _, revision_ms = once(lambda: service.revise_observation(
            db.scalar(
                "SELECT observation_id FROM economic_observation "
                "WHERE series_id = 'ECON-NOAA-DFW-TMAX-D' AND period_start = '2023-06-30'"
            ),
            value=32.9, reason="benchmark invalidation measurement",
        ))
        _, stale_check_ms = once(lambda: service.get_run(run["run_id"]))
        _, memory_after_ms = once(service.memory)

        payload = {
            "schema": "atlas.phase7.benchmarks.v1",
            "measured_at": iso(utcnow()),
            "hardware": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor() or "not reported by OS",
                "cpu_count": os.cpu_count(),
                "python": platform.python_version(),
                "numpy": np.__version__,
                "sqlite": __import__("sqlite3").sqlite_version,
            },
            "workload": {
                "dataset": "fixtures/phase7/weather_demand_2023.csv",
                "days": 365,
                "observations": 1095,
                "series": 3,
                "entities": 12,
                "evidence_edges": 12,
                "analysis": "weather-demand chronological OLS",
                "scenario_draws": 2000,
                "large_scenario_draws": 10_000,
                "database_bytes": path.stat().st_size,
            },
            "cold": {
                "migrate_all_ms": migration_ms,
                "ingest_and_bootstrap_ms": cold_ingest_ms,
                "panel_query_ms": panel_cold_ms,
                "graph_indexed_traversal_ms": graph_cold_ms,
            },
            "warm": {
                "panel_query": panel_warm_stats,
                "graph_indexed_traversal": graph_warm_stats,
            },
            "operations": {
                "geographic_join_ms": geographic_ms,
                "model_fit_and_test_ms": model_ms,
                "model_fit_validate_test_and_persist_ms": persist_ms,
                "scenario_2000_draws_compile_and_persist_ms": scenario_ms,
                "scenario_10000_draws_compile_and_persist_ms": scenario_10k_ms,
                "sentinel_refresh_ms": sentinel_ms,
                "historical_replay_ms": replay_ms,
                "research_memory_ms": memory_ms,
                "application_save_ms": save_ms,
                "application_restore_ms": restore_ms,
                "application_export_ms": export_ms,
                "one_observation_revision_invalidation_ms": revision_ms,
                "stale_run_read_ms": stale_check_ms,
                "memory_after_invalidation_ms": memory_after_ms,
            },
            "throughput": {
                "monte_carlo_draws_per_second_10k": round(
                    10_000 / max(scenario_10k_ms / 1000, 1e-9), 1
                ),
                "scenarios_per_second_2k": round(1000 / max(scenario_ms, 1e-9), 2),
            },
            "serialized": {
                "analysis_json_bytes": len(run_json.encode()),
                "scenario_json_bytes": len(scenario_json.encode()),
                "catalog_json_bytes": len(json.dumps(catalog, default=str).encode()),
                "application_export_bytes": len(json.dumps(application, default=str).encode()),
            },
            "memory": {"peak_rss_mb": rss_mb()},
            "result": {
                "run_id": run["run_id"],
                "scenario_id": scenario["scenario_id"],
                "test_rmse_mw": run["test"]["rmse"],
                "baseline_rmse_mw": run["baseline"]["rmse"],
                "skill_vs_seasonal": run["skill_vs_seasonal"],
                "test_r2": run["test"]["r2"],
                "conclusion": run["conclusion"],
                "causal_status": run["causal_status"],
                "cost_delta_usd": scenario["financial"]["cost_delta_usd"],
                "stale_runs": 1,
            },
            "notes": [
                "The workload is CPU-only SQLite plus NumPy; timings are machine-specific.",
                "Warm timings are the median of repeated calls after one untimed warm-up.",
                "Scenario persistence is included; browser rendering is measured separately.",
                "A file-backed temporary database is used; the shipped database is not modified.",
                "The revision at the end intentionally mutates the temporary database only.",
            ],
        }
        db.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
