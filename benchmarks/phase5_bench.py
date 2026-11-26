#!/usr/bin/env python3
"""Deterministic Phase 5 measurements. No synthetic timing inflation or warm-up hiding."""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.finance.curves import analyse_bond, load_treasury_csv  # noqa: E402
from atlas.finance.options import bsm_greeks  # noqa: E402
from atlas.institutional.risk import optimize, portfolio_analysis  # noqa: E402
from atlas.institutional.universe import returns_matrix  # noqa: E402
from atlas.institutional.validation import walk_forward  # noqa: E402

CURVE = ROOT / "fixtures" / "phase5" / "treasury-par-yields-2024.csv"


def timed(function, repeats: int):
    values = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = function()
        values.append((time.perf_counter() - started) * 1000)
    return {
        "repeats": repeats,
        "median_ms": round(statistics.median(values), 4),
        "p95_ms": round(sorted(values)[max(0, int(0.95 * len(values)) - 1)], 4),
        "min_ms": round(min(values), 4),
        "max_ms": round(max(values), 4),
    }, result


def main() -> int:
    matrix = returns_matrix()
    equal = {security: 1 / len(matrix["securities"]) for security in matrix["securities"]}
    curve = load_treasury_csv(CURVE, observation_date="2024-06-28")
    report = {}
    report["curve_load"], _ = timed(lambda: load_treasury_csv(CURVE, observation_date="2024-06-28"), 30)
    report["bond_full_analytics"], _ = timed(lambda: analyse_bond(
        curve, settlement_date="2024-07-01", maturity_date="2029-06-30", coupon_rate=0.0425
    ), 200)
    report["option_greeks"], _ = timed(lambda: bsm_greeks(100, 100, 1, 0.05, 0.2, 0.0), 5000)
    report["risk_equal_weight_252"], _ = timed(
        lambda: portfolio_analysis(weights=equal, lookback=252), 100
    )
    report["risk_equal_weight_935"], _ = timed(
        lambda: portfolio_analysis(weights=equal, lookback=935), 100
    )
    report["optimize_three_asset_935"], _ = timed(lambda: optimize(weights=equal, max_weight=0.6), 25)
    report["walk_forward_2_folds"], _ = timed(lambda: walk_forward(
        folds=2, train=180, validation=40, test=40, step=40, embargo=5
    ), 3)
    report["walk_forward_3_folds"], _ = timed(lambda: walk_forward(
        folds=3, train=252, validation=63, test=63, step=63, embargo=5
    ), 1)
    payload = {
        "phase": 5,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dataset": {
            "universe_id": matrix["universe_id"],
            "data_class": matrix["data_class"],
            "observations": len(matrix["dates"]),
            "content_hash": matrix.get("content_hash"),
            "treasury_sha256": curve.source_sha256,
        },
        "measurements": report,
        "notes": [
            "Single-process CPU-only measurements; no concurrency, caching or database reads.",
            "Walk-forward includes train/validation selection, one untouched test pass, cost sensitivity and attempt logging.",
            "Latency does not establish predictive value or investment merit.",
        ],
    }
    target = ROOT / "artifacts" / "phase5_benchmarks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
