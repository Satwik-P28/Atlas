"""Sentinel-style monitoring for saved learning models.

Monitoring reports observations with sample sizes. It never calls a model invalid
because a threshold was crossed and never retrains or deploys anything.
"""

from __future__ import annotations

import math
from statistics import mean, stdev
from typing import Any

from .features import build_rows
from .metrics import calibration_table


def feature_drift(panel: dict[str, Any], artifact: dict[str, Any], features: list[str],
                  *, recent_sessions: int = 20) -> dict[str, Any]:
    built = build_rows(panel, features=features, target="direction")
    rows = built["rows"]
    dates = built["dates"][-recent_sessions:]
    recent = [row for row in rows if row["date"] in set(dates)]
    scaler = artifact.get("scaler") or {}
    means, scales = scaler.get("mean") or [], scaler.get("scale") or []
    observations = []
    for index, key in enumerate(features):
        values = [row["features"][key] for row in recent]
        current = mean(values) if values else None
        training_mean = means[index] if index < len(means) else None
        scale = scales[index] if index < len(scales) else None
        z = ((current - training_mean) / scale
             if current is not None and training_mean is not None and scale not in (None, 0) else None)
        observations.append({
            "feature": key, "recent_mean": current, "training_mean": training_mean,
            "standardised_shift": z,
            "sessions": len(values),
            "interpretation": "large shift" if z is not None and abs(z) >= 2 else "within two training scales",
        })
    return {
        "schema": "atlas.learning.monitor.v1",
        "recent_sessions": len(dates),
        "features": observations,
        "automatic_action": None,
        "note": "A shift is an observation, not proof of model failure; sample size and regime context matter.",
    }


def realized_calibration(forecasts: list[dict[str, Any]], *, bins: int = 5) -> dict[str, Any]:
    completed = [item for item in forecasts if item.get("target") is not None]
    if not completed:
        return {"schema": "atlas.learning.monitor.v1", "completed": 0,
                "calibration": [], "note": "no realized outcomes are available"}
    probability = [float(item.get("probability", 0)) for item in completed]
    outcome = [float(item["target"]) for item in completed]
    table = calibration_table(probability, outcome, bins=bins)
    return {
        "schema": "atlas.learning.monitor.v1",
        "completed": len(completed),
        "calibration": table,
        "mean_probability": mean(probability),
        "observed_rate": mean(outcome),
        "gap": mean(probability) - mean(outcome),
        "note": "This diagnostic uses only outcomes known after each forecast date.",
    }


def compare_validation_to_test(validation: dict[str, Any], test: dict[str, Any]) -> dict[str, Any]:
    brier_change = None
    if validation.get("brier") is not None and test.get("brier") is not None:
        brier_change = test["brier"] - validation["brier"]
    return {
        "validation_brier": validation.get("brier"),
        "test_brier": test.get("brier"),
        "brier_change": brier_change,
        "warning": (None if brier_change is None or brier_change <= 0.05
                    else "Test Brier is materially worse than validation; investigate regime or overfitting."),
        "sample_sizes": {"validation": validation.get("observations"),
                         "test": test.get("observations")},
    }


__all__ = ["compare_validation_to_test", "feature_drift", "realized_calibration"]
