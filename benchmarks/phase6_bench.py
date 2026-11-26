#!/usr/bin/env python
"""Measure the Phase 6 research pipeline on the local real-data demo panel.

The benchmark is intentionally CPU-only. It reads the local, restricted demo
database, does not write vendor bytes, and does not use the network. Reported
numbers are medians of repeated runs with the fitted model and panel reused
where the stage allows it.

Usage:
    .venv/bin/python benchmarks/phase6_bench.py [--db var/atlas-phase6.db]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.learning.audit import audit_result  # noqa: E402
from atlas.learning.data import load_panel  # noqa: E402
from atlas.learning.discovery import discover  # noqa: E402
from atlas.learning.experiments import run_experiment  # noqa: E402
from atlas.learning.features import build_rows, matrix  # noqa: E402
from atlas.learning.metrics import summarize  # noqa: E402
from atlas.learning.models import predict  # noqa: E402
from atlas.learning.service import LearningService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

FEATURES = ["mom_5", "mom_20", "vol_20", "sma_gap_20", "cs_mom_20_rank"]
MODELS = ["climatology", "ridge", "logistic", "mlp"]


def timed(function, repeats: int = 3) -> tuple[float, float, object]:
    samples, value = [], None
    for _ in range(repeats):
        start = time.perf_counter()
        value = function()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), min(samples), value


def memory_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "var" / "atlas-phase6.db"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase6_benchmarks.json"))
    args = parser.parse_args()
    db = Database(args.db, create=False)
    report: dict[str, object] = {
        "schema": "atlas.phase6.benchmark.v1",
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or "not reported by platform",
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
            "accelerator": "CPU only",
        },
        "software": {},
        "dataset": {},
        "stages_ms": {},
        "notes": [
            "Medians of three runs unless marked single; timings include Python orchestration.",
            "The dataset contains restricted vendor demo rows stored only locally.",
            "No GPU, network request, or vendor byte redistribution occurs in this benchmark.",
        ],
    }
    try:
        import numpy
        import scipy
        import sklearn
        import pyarrow

        report["software"] = {
            "numpy": numpy.__version__, "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__, "pyarrow": pyarrow.__version__,
        }
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        report["software"] = {"error": f"optional scientific package missing: {exc}"}

    load_median, load_min, panel = timed(lambda: load_panel(db, dataset="eodhd-demo:all"))
    assert isinstance(panel, dict)
    report["dataset"] = {
        "dataset_id": panel["dataset_id"], "securities": panel["coverage"]["securities"],
        "sessions": panel["coverage"]["sessions"], "bars": panel["coverage"]["securities"] * panel["coverage"]["sessions"],
        "expected_weekdays": panel["coverage"]["expected_weekdays"],
        "missing_weekdays": panel["coverage"]["missing_weekdays"],
        "start": panel["coverage"]["start"], "end": panel["coverage"]["end"],
        "quality_errors": panel["quality_summary"]["errors"],
        "quality_warnings": panel["quality_summary"]["warnings"],
        "content_hash": panel["content_hash"],
    }
    build_median, build_min, built = timed(
        lambda: build_rows(panel, features=FEATURES, target="direction"))
    assert isinstance(built, dict)
    report["dataset"]["feature_rows"] = built["row_count"]
    report["dataset"]["features"] = len(FEATURES)
    report["stages_ms"]["dataset_load"] = {"median": load_median, "min": load_min}
    report["stages_ms"]["feature_generation"] = {"median": build_median, "min": build_min}

    exp_median, exp_min, result = timed(lambda: run_experiment(
        panel, models=MODELS, features=FEATURES, target="direction", seed=20261105), repeats=3)
    assert isinstance(result, dict)
    report["experiment"] = {
        "candidates": len(result["attempts"]), "selected_model": result["selection"]["selected_model"],
        "validation_brier": result["selection"]["brier"],
        "test_brier": result["test"]["brier"], "brier_skill": result["test"]["brier_skill_vs_climatology"],
        "test_rows": result["test"]["observations"],
        "forecasts": len(result["forecasts"]),
        "conclusion": result["conclusion"],
        "duration_reported_ms": result["duration_ms"],
    }
    report["stages_ms"]["train_validate_test_4_models"] = {"median": exp_median, "min": exp_min}

    test_start = result["split"]["test"]["start"]
    test_rows = [row for row in built["rows"] if row["date"] >= test_start]
    x_test, y_test = matrix(test_rows, FEATURES)
    artifact = result["model"]["artifact"]

    infer_median, infer_min, probabilities = timed(lambda: predict(artifact, x_test, calibrated=True))
    assert isinstance(probabilities, list)
    report["stages_ms"]["batch_inference"] = {
        "median": infer_median, "min": infer_min, "rows": len(x_test),
    }
    cal_median, cal_min, scored = timed(lambda: summarize(probabilities, y_test), repeats=10)
    assert isinstance(scored, dict)
    report["stages_ms"]["probability_scoring_and_calibration"] = {
        "median": cal_median, "min": cal_min, "bins": scored["bins"],
    }
    audit_median, audit_min, audit = timed(lambda: audit_result(
        result, feature_correlation=result["feature_correlation"],
        train_rows=result["split"]["train"]["rows"], test_rows=result["split"]["test"]["rows"],
        selected_model=result["selection"]["selected_model"],
        data_class=panel["data_class"], rights=panel["rights"],
    ), repeats=3)
    assert isinstance(audit, dict)
    report["stages_ms"]["model_audit"] = {
        "median": audit_median, "min": audit_min, "findings": len(audit["findings"]),
        "counts": audit["counts"],
    }
    discovery_start = time.perf_counter()
    discovery = discover(panel, budget=4, models=["ridge"], feature_sets=[["mom_5", "mom_20", "vol_20"]])
    discovery_ms = (time.perf_counter() - discovery_start) * 1000
    report["stages_ms"]["bounded_discovery_4_candidates"] = {
        "median": discovery_ms, "min": discovery_ms, "single_run": True,
    }
    report["discovery"] = {
        "evaluated": discovery["evaluated"], "budget": discovery["budget"],
        "test_used": discovery["test_used"],
        "best_validation_brier": discovery["recommendations"][0]["metrics"]["brier"],
    }

    service = LearningService(db)
    latest = service.list_runs(limit=1)
    if latest:
        run_id = latest[0]["run_id"]
        replay_median, replay_min, replay = timed(lambda: service.get_run(run_id), repeats=5)
        report["stages_ms"]["persisted_run_replay"] = {
            "median": replay_median, "min": replay_min,
            "run_id": run_id, "forecasts": len(replay["forecasts"]),
        }
        monitor_start = time.perf_counter()
        monitor = service.monitor(run_id)
        monitor_ms = (time.perf_counter() - monitor_start) * 1000
        report["stages_ms"]["monitor_snapshot"] = {
            "median": monitor_ms, "min": monitor_ms, "single_run": True,
            "forecasts": monitor["calibration"]["completed"],
        }

    report["process"] = {
        "peak_rss_mb": memory_mb(),
        "db_size_bytes": Path(args.db).stat().st_size,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
