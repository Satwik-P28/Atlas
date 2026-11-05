"""Scientific experiment engine for Phase 6.

Protocol: fit each candidate on the training interval, rank on validation, fit
probability calibration on validation, then evaluate the selected model exactly
once on the untouched test interval. Every attempted model is retained. The
test interval never influences selection.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Any

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow
from .audit import audit_result
from .features import (
    FEATURE_SPECS,
    TARGETS,
    build_rows,
    matrix,
    max_abs_correlation,
    normalise_features,
)
from .metrics import (
    brier_score,
    paired_block_bootstrap,
    summarize,
)
from .models import (
    MODEL_KEYS,
    artifact_fingerprint,
    fit_calibrator,
    fit_model,
    fit_return_model,
    model_metadata,
    predict,
    predict_return,
)
from .data import validate_panel

LEARNING_SCHEMA = "atlas.learning.run.v2"


def _hash(value: Any) -> str:
    import json
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _partition_rows(rows: list[dict[str, Any]], dates: list[str], *, embargo: int,
                    train_fraction: float, validation_fraction: float) -> dict[str, Any]:
    n = len(dates)
    train_end = max(40, int(n * train_fraction))
    val_start = min(n - 2, train_end + embargo)
    val_end = max(val_start + 20, int(n * (train_fraction + validation_fraction)))
    test_start = min(n - 1, val_end + embargo)
    if test_start >= n:
        raise ValidationError("no untouched test interval remains after embargo",
                              sessions=n, test_start=test_start)
    train_dates = set(dates[:train_end])
    validation_dates = set(dates[val_start:val_end])
    test_dates = set(dates[test_start:])
    train = [row for row in rows if row["date"] in train_dates]
    validation = [row for row in rows if row["date"] in validation_dates]
    test = [row for row in rows if row["date"] in test_dates]
    if min(len(train), len(validation), len(test)) < 20:
        raise ValidationError("each split needs at least twenty feature rows",
                              train=len(train), validation=len(validation), test=len(test))
    if max(train_dates) >= min(validation_dates):
        raise ValidationError("train and validation intervals overlap")
    if max(validation_dates) >= min(test_dates):
        raise ValidationError("validation and test intervals overlap")
    return {
        "train": train, "validation": validation, "test": test,
        "split": {
            "train": {"start": min(train_dates), "end": max(train_dates), "rows": len(train),
                      "sessions": len(train_dates)},
            "validation": {"start": min(validation_dates), "end": max(validation_dates),
                           "rows": len(validation), "sessions": len(validation_dates)},
            "test": {"start": min(test_dates), "end": max(test_dates), "rows": len(test),
                     "sessions": len(test_dates)},
            "embargo": embargo,
            "train_fraction": train_fraction,
            "validation_fraction": validation_fraction,
            "test_used_for_selection": False,
            "selection_metric": "validation Brier score (lower is better)",
        },
    }


def run_experiment(
    panel: dict[str, Any],
    *,
    models: list[str] | None = None,
    features: list[str] | None = None,
    target: str = "direction",
    seed: int = 20261105,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    embargo: int = 2,
    hypothesis: str = "Point-in-time price and volume features improve next-session probability forecasts over climatology.",
) -> dict[str, Any]:
    started = time.perf_counter()
    validate_panel(panel)
    if target != "direction":
        raise ValidationError("this release evaluates the binary direction target; "
                              "a continuous return companion is produced automatically",
                              target=target)
    requested = list(dict.fromkeys(models or ["climatology", "ridge", "logistic", "mlp"]))
    for key in requested:
        if key not in MODEL_KEYS:
            raise ValidationError("unknown model", model=key, supported=list(MODEL_KEYS))
    feature_keys = normalise_features(features)
    built = build_rows(panel, features=feature_keys, target=target)
    rows = built["rows"]
    dates = built["dates"]
    partition = _partition_rows(rows, dates, embargo=embargo,
                                train_fraction=train_fraction,
                                validation_fraction=validation_fraction)
    train, validation, test = partition["train"], partition["validation"], partition["test"]
    x_train, y_train = matrix(train, feature_keys)
    x_val, y_val = matrix(validation, feature_keys)
    x_test, y_test = matrix(test, feature_keys)
    if len(set(y_train)) < 2 or len(set(y_val)) < 2:
        raise ValidationError("training or validation target has no class variation")
    attempts: list[dict[str, Any]] = []
    fitted: dict[str, dict[str, Any]] = {}
    for key in requested:
        metadata = model_metadata(key)
        try:
            artifact = fit_model(key, x_train, y_train, seed=seed)
            validation_probabilities = predict(artifact, x_val, calibrated=False)
            validation_metrics = summarize(validation_probabilities, y_val)
            fitted[key] = artifact
            attempts.append({
                "model": key, "label": metadata["label"], "family": metadata["family"],
                "stage": "validation", "status": "succeeded",
                "metrics": validation_metrics, "artifact": artifact,
            })
        except Exception as exc:  # noqa: BLE001 - failure is evidence, not a reason to abort all candidates
            attempts.append({
                "model": key, "label": metadata["label"], "family": metadata["family"],
                "stage": "validation", "status": "failed", "error": str(exc),
                "metrics": None, "artifact": None,
            })
    candidates = [item for item in attempts if item["status"] == "succeeded"]
    if not candidates:
        raise ValidationError("every candidate failed validation", attempts=attempts)
    ranked = sorted(candidates, key=lambda item: item["metrics"]["brier"])
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    selected = ranked[0]
    artifact = fit_calibrator(
        selected["artifact"], x_val, y_val
    )
    selected["selected"] = True
    raw_test = predict(artifact, x_test, calibrated=False)
    calibrated_test = predict(artifact, x_test, calibrated=True)
    test_metrics = summarize(calibrated_test, y_test)
    raw_metrics = summarize(raw_test, y_test)
    prevalence = sum(y_train) / len(y_train)
    baseline_test = summarize([prevalence] * len(y_test), y_test)
    skill = 1.0 - test_metrics["brier"] / baseline_test["brier"] if baseline_test["brier"] > 0 else None
    test_metrics["brier_skill_vs_climatology"] = skill
    test_metrics["raw_brier"] = raw_metrics["brier"]
    test_metrics["raw_log_loss"] = raw_metrics["log_loss"]
    test_metrics["calibration_method"] = "platt" if artifact.get("calibrator") else "none"
    base_row_brier = [(p - y) ** 2 for p, y in zip([prevalence] * len(y_test), y_test)]
    model_row_brier = [(p - y) ** 2 for p, y in zip(calibrated_test, y_test)]
    uncertainty = {
        "test_brier_ci": __import__("atlas.learning.metrics", fromlist=["bootstrap_mean_ci"]).bootstrap_mean_ci(
            model_row_brier, seed=seed
        ),
        "paired_brier_difference": paired_block_bootstrap(
            base_row_brier, model_row_brier, seed=seed
        ),
        "note": "Intervals treat rows as ordered blocks; cross-sectional dependence is not fully removed.",
    }
    if selected["model"] == "climatology" or skill is None or skill <= 0:
        conclusion = "not_supported"
    elif uncertainty["paired_brier_difference"].get("low") is not None and uncertainty["paired_brier_difference"]["low"] <= 0:
        conclusion = "inconclusive"
    else:
        conclusion = "validation_supported_with_caveats"
    # Continuous companion: same split, independent ridge on returns.
    x_train_return = x_train
    y_train_return = [row["target_return"] for row in train]
    continuous_artifact = fit_return_model(x_train_return, y_train_return, seed=seed)
    continuous_predictions = predict_return(continuous_artifact, x_test)
    continuous_errors = [
        item["value"] - row["target_return"]
        for item, row in zip(continuous_predictions, test)
    ]
    continuous_metrics = {
        "observations": len(test),
        "rmse": math.sqrt(sum(value ** 2 for value in continuous_errors) / len(continuous_errors)),
        "mae": sum(abs(value) for value in continuous_errors) / len(continuous_errors),
        "mean_error": sum(continuous_errors) / len(continuous_errors),
        "interval_coverage": sum(
            1 for item, row in zip(continuous_predictions, test)
            if item["lower"] <= row["target_return"] <= item["upper"]
        ) / len(test),
        "interval": continuous_artifact["interval"],
    }
    forecasts = [
        {
            "security_id": row["security_id"], "date": row["date"],
            "target_date": row["target_date"], "probability": probability,
            "target": row["target"], "target_return": row["target_return"],
            "prediction_interval": next(
                (item for item, source in zip(continuous_predictions, test) if source is row), None
            ),
        }
        for row, probability in zip(test, calibrated_test)
    ]
    artifact_payload = {
        "schema": "atlas.learning.model.v2",
        "model_key": artifact["model_key"],
        "features": feature_keys,
        "artifact": artifact,
        "calibration": artifact.get("calibrator"),
        "target": built["target_definition"],
        "dataset_id": panel["dataset_id"],
        "panel_hash": panel["content_hash"],
        "seed": seed,
        "software": artifact.get("software"),
    }
    fingerprint = artifact_fingerprint(artifact_payload)
    result: dict[str, Any] = {
        "schema": LEARNING_SCHEMA,
        "run_id": f"LRUN-{_hash([panel['content_hash'], requested, feature_keys, seed])[:20]}",
        "created_at": iso(utcnow()),
        "hypothesis": hypothesis,
        "status": "succeeded",
        "conclusion": conclusion,
        "dataset": {
            "dataset_id": panel["dataset_id"], "source_id": panel["source_id"],
            "data_class": panel["data_class"], "rights": panel["rights"],
            "content_hash": panel["content_hash"], "securities": len(panel["instruments"]),
            "sessions": len(panel["dates"]), "start": panel["dates"][0], "end": panel["dates"][-1],
            "quality": panel.get("quality_summary"),
        },
        "features": feature_keys,
        "feature_metadata": [item for item in FEATURE_SPECS if item["key"] in feature_keys],
        "target": built["target_definition"],
        "target_key": target,
        "target_definition": built["target_definition"],
        "timing": built["timing"],
        "split": partition["split"],
        "attempts": attempts,
        "selection": {
            "selected_model": selected["model"],
            "selected_label": selected["label"],
            "selected_family": selected["family"],
            "brier": selected["metrics"]["brier"],
            "candidates": len(attempts),
            "failed": sum(1 for item in attempts if item["status"] == "failed"),
            "test_used_for_selection": False,
        },
        "test": test_metrics,
        "test_raw": raw_metrics,
        "baseline": baseline_test,
        "uncertainty": uncertainty,
        "continuous": {"metrics": continuous_metrics, "artifact": continuous_artifact},
        "model": {
            "schema": "atlas.learning.model.v2",
            "model_key": selected["model"],
            "fingerprint": fingerprint,
            "artifact": artifact,
            "artifact_payload_hash": fingerprint,
            "version": f"1.0.{abs(int(fingerprint[:6], 16)) % 100000}",
        },
        "forecasts": forecasts,
        "forecast_count": len(forecasts),
        "feature_correlation": None,
        "audit": None,
        "limitations": [
            "Price-only features do not include fundamentals or macro revisions.",
            "Raw closes do not include dividends; this is a price-direction experiment, not total return.",
            "Cross-sectional rows share market-wide shocks, so effective sample size is below row count.",
            "The untouched test result is evidence about this dataset and period, not a claim of persistent skill.",
            "A calibrated probability is not a portfolio rule until a separately declared threshold and cost model are applied.",
        ],
    }
    result["feature_correlation"] = max_abs_correlation(x_train)
    result["audit"] = audit_result(
        result, feature_correlation=result["feature_correlation"],
        train_rows=len(train), test_rows=len(test), selected_model=selected["model"],
        data_class=panel["data_class"], rights=panel["rights"],
    )
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


__all__ = ["LEARNING_SCHEMA", "run_experiment"]
