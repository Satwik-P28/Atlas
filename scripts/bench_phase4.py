"""Reproducible Phase 4 measurements for the compiler, features and simulator."""

from __future__ import annotations

import json
import platform
import statistics
import time
import tracemalloc
from pathlib import Path

from atlas.fec import compile_model
from atlas.quant.features import FeatureEngine
from atlas.quant.lab import QuantLab, template_spec, universe
from atlas.quant.simulator import SimulationConfig, run_simulation
from atlas.storage.db import Database


def median_ms(fn, repeats: int = 3) -> float:
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        values.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(values), 3)


def graph_spec(size: int) -> dict:
    nodes = [{"id": "n0", "op": "add", "inputs": ["x", "x"]}]
    for index in range(1, size):
        nodes.append({"id": f"n{index}", "op": "add", "inputs": [f"n{index - 1}", "x"]})
    return {
        "schema_version": "atlas.model.v1", "name": f"bench-{size}", "interface": "graph",
        "inputs": [{"name": "x", "type": "Scalar"}], "nodes": nodes,
        "outputs": {"value": f"n{size - 1}"},
    }


def main() -> None:
    db = Database("var/atlas.db", create=False)
    instruments = universe(db)
    ibm = next(item for item in instruments if item.get("ticker") == "IBM")
    lab = QuantLab(db)
    report: dict = {
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_model": next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), "unknown"),
        },
        "dataset": {"security_id": ibm["security_id"], "sessions": ibm["sessions"],
                    "first_bar": ibm["first_bar"], "last_bar": ibm["last_bar"],
                    "source_ids": ibm["source_ids"]},
    }
    report["compiler"] = []
    # 2,000 is the validated compiler node limit; 1,900 measures near the ceiling
    # without bypassing the guardrail.
    for size in (10, 100, 1000, 1900):
        tracemalloc.start()
        compiled = compile_model(graph_spec(size))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        report["compiler"].append({
            "nodes": size,
            "compile_ms_median": median_ms(lambda size=size: compile_model(graph_spec(size)), 3),
            "compile_peak_mib": round(peak / 1024 / 1024, 2),
            "plan_nodes": len(compiled.order),
        })
    features = [
        {"name": "close", "kind": "price", "window": 1},
        {"name": "ret", "kind": "return", "window": 2},
        {"name": "sma20", "kind": "sma", "window": 20},
        {"name": "mom60", "kind": "momentum", "window": 60},
        {"name": "vol20", "kind": "volatility", "window": 20},
        {"name": "volume_z", "kind": "volume_zscore", "window": 20},
    ]
    feature_result = FeatureEngine(db).compute(ibm["security_id"], ibm["mic"], features,
                                               start="2015-01-02", end="2026-11-03",
                                               as_of="2026-11-03", persist=False)
    report["features"] = {
        "definitions": len(features), "points": len(feature_result.points),
        "first": feature_result.points[0]["date"] if feature_result.points else None,
        "last": feature_result.points[-1]["date"] if feature_result.points else None,
        "compute_ms_median": median_ms(lambda: FeatureEngine(db).compute(
            ibm["security_id"], ibm["mic"], features, start="2015-01-02", end="2026-11-03",
            as_of="2026-11-03", persist=False), 3),
    }
    config = SimulationConfig(as_of="2026-11-03", start="2015-01-02", end="2026-11-03",
                              initial_capital=100_000)
    report["simulator"] = []
    for template in lab.builtin_templates():
        spec = template_spec(template, ibm, name=f"Benchmark {template['key']}")
        tracemalloc.start()
        result = run_simulation(db, spec, config=config)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        report["simulator"].append({
            "strategy": template["key"],
            "sessions": result["period"]["sessions"],
            "trades": len(result["trades"]),
            "duration_ms": result["duration_ms"],
            "sessions_per_second": round(result["period"]["sessions"] / max(result["duration_ms"] / 1000, 1e-9), 1),
            "peak_mib": round(peak / 1024 / 1024, 2),
            "total_return": result["metrics"]["total_return"],
            "max_drawdown": result["metrics"]["max_drawdown"],
            "reconciled": result["reconciliation"]["reconciled"],
            "result_fingerprint": result["result_fingerprint"][:16],
        })
    db.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
