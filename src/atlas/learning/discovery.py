"""Controlled model discovery.

This is deliberately not an autonomous agent. It enumerates a finite, declared
grid, evaluates candidates on a discovery split, keeps failures, and returns
recommendations only. The final untouched test interval is not used or exposed by
this loop; a recommendation must be confirmed by a fresh experiment.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .features import DEFAULT_FEATURES, build_rows, matrix
from .metrics import summarize
from .models import fit_model, predict

DISCOVERY_SCHEMA = "atlas.learning.discovery.v1"


def candidates(
    models: list[str] | None = None,
    feature_sets: list[list[str]] | None = None,
    thresholds: list[float] | None = None,
) -> list[dict[str, Any]]:
    model_keys = models or ["ridge", "logistic", "mlp"]
    sets = feature_sets or [
        ["mom_20", "vol_20"],
        list(DEFAULT_FEATURES),
        ["mom_5", "mom_20", "mom_60", "vol_20", "cs_mom_20_rank"],
    ]
    threshold_values = thresholds or [0.50, 0.55]
    result = []
    for model in model_keys:
        for features in sets:
            for threshold in threshold_values:
                result.append({"model": model, "features": list(features), "threshold": threshold})
    return result


def discover(panel: dict[str, Any], *, budget: int = 6, seed: int = 20261105,
             models: list[str] | None = None, feature_sets: list[list[str]] | None = None) -> dict[str, Any]:
    if budget < 1 or budget > 24:
        raise ValueError("discovery budget must be in [1,24]")
    grid = candidates(models=models, feature_sets=feature_sets)[:budget]
    attempts = []
    for candidate in grid:
        try:
            built = build_rows(panel, features=candidate["features"], target="direction")
            rows = built["rows"]
            dates = built["dates"]
            discovery_end = max(40, int(len(dates) * 0.70))
            embargo = 2
            train_dates = set(dates[:discovery_end])
            validation_dates = set(dates[discovery_end + embargo:])
            train = [row for row in rows if row["date"] in train_dates]
            validation = [row for row in rows if row["date"] in validation_dates]
            x_train, y_train = matrix(train, candidate["features"])
            x_val, y_val = matrix(validation, candidate["features"])
            artifact = fit_model(candidate["model"], x_train, y_train, seed=seed)
            probabilities = predict(artifact, x_val, calibrated=False)
            metrics = summarize(probabilities, y_val)
            attempts.append({**candidate, "status": "succeeded", "metrics": metrics,
                             "artifact_fingerprint": hashlib.sha256(
                                 json.dumps(artifact, sort_keys=True, default=str).encode()
                             ).hexdigest()})
        except Exception as exc:  # noqa: BLE001 - failed candidates are retained
            attempts.append({**candidate, "status": "failed", "error": str(exc), "metrics": None})
    completed = sorted(
        (item for item in attempts if item["status"] == "succeeded"),
        key=lambda item: item["metrics"]["brier"],
    )
    for rank, item in enumerate(completed, start=1):
        item["rank"] = rank
    return {
        "schema": DISCOVERY_SCHEMA,
        "method": "bounded grid over declared model/feature/threshold candidates",
        "budget": budget,
        "evaluated": len(attempts),
        "selection_metric": "validation Brier score",
        "test_used": False,
        "attempts": attempts,
        "recommendations": completed[:3],
        "stop_reason": "budget exhausted; recommendations require a fresh confirmatory experiment",
        "limitations": [
            "This is hyperparameter/feature selection, not open-ended scientific discovery.",
            "The discovery split is not a replacement for a later untouched test.",
        ],
    }


__all__ = ["DISCOVERY_SCHEMA", "candidates", "discover"]
