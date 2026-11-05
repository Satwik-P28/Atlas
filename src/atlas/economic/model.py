"""Weather-demand research model.

This is deliberately an association study. Weather is not randomly assigned, the
station is not an area-weighted ERCOT temperature, and the model is a same-day
conditional relationship rather than a day-ahead forecast. The chronological split
keeps the final 55 days untouched for selection.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np

from ..core.temporal import iso, utcnow
from .contracts import continuous_forecast_document, digest

MODEL_SCHEMA = "atlas.economic.weather_demand.v1"
MODEL_VERSION = "1.0.0"
BASE_FEATURES = ["dow_1", "dow_2", "dow_3", "dow_4", "dow_5", "dow_6",
                 "sin_1", "cos_1", "sin_2", "cos_2", "sin_3", "cos_3"]
WEATHER_LINEAR = ["cdd_18c", "hdd_18c"]
WEATHER_CURVATURE = ["cdd_18c", "hdd_18c", "cdd_squared"]


def _fourier(day_of_year: int) -> list[float]:
    values = []
    for harmonic in (1, 2, 3):
        angle = 2.0 * math.pi * harmonic * day_of_year / 365.25
        values.extend([math.sin(angle), math.cos(angle)])
    return values


def feature_row(row: dict[str, Any]) -> dict[str, float]:
    day = date.fromisoformat(row["date"])
    weekday = day.weekday()
    features = {
        **{f"dow_{index + 1}": 1.0 if weekday == index else 0.0 for index in range(6)},
    }
    sin_cos = _fourier(day.timetuple().tm_yday)
    for index, key in enumerate(["sin_1", "cos_1", "sin_2", "cos_2", "sin_3", "cos_3"]):
        features[key] = sin_cos[index]
    cdd = float(row["cooling_degree_day_18c"])
    hdd = float(row["heating_degree_day_18c"])
    features.update({"cdd_18c": cdd, "hdd_18c": hdd, "cdd_squared": cdd * cdd})
    return features


def design(rows: list[dict[str, Any]], feature_names: list[str]) -> tuple[np.ndarray, np.ndarray, list[dict[str, float]]]:
    features = [feature_row(row) for row in rows]
    matrix = np.asarray([[1.0] + [item[name] for name in feature_names] for item in features], dtype=float)
    target = np.asarray([float(row["demand_mean_mw"]) for row in rows], dtype=float)
    return matrix, target, features


def _ols(matrix: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    if len(target) <= matrix.shape[1]:
        raise ValueError("not enough observations for the declared feature set")
    beta, _, rank, singular = np.linalg.lstsq(matrix, target, rcond=None)
    if rank < matrix.shape[1]:
        raise ValueError(f"design matrix is rank deficient ({rank} < {matrix.shape[1]})")
    fitted = matrix @ beta
    residual = target - fitted
    degrees = len(target) - matrix.shape[1]
    sigma_squared = float(residual @ residual / degrees)
    covariance = sigma_squared * np.linalg.pinv(matrix.T @ matrix)
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    return {
        "beta": beta,
        "covariance": covariance,
        "standard_errors": standard_errors,
        "fitted": fitted,
        "residual": residual,
        "residual_sigma": math.sqrt(max(sigma_squared, 0.0)),
        "sigma_squared": sigma_squared,
        "rank": int(rank),
        "condition_number": float(np.linalg.cond(matrix)),
        "singular_values": [float(value) for value in singular],
    }


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    residual = actual - predicted
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    mae = float(np.mean(np.abs(residual)))
    denominator = float(np.sum((actual - np.mean(actual)) ** 2))
    r2 = float(1.0 - np.sum(residual ** 2) / denominator) if denominator > 0 else 0.0
    return {
        "rmse": rmse,
        "mae": mae,
        "mean_error": float(np.mean(residual)),
        "r2": r2,
        "observations": int(len(actual)),
    }


def _durbin_watson(residual: np.ndarray) -> float:
    denominator = float(np.sum(residual ** 2))
    if denominator <= 0:
        return 0.0
    return float(np.sum(np.diff(residual) ** 2) / denominator)


def _reference_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if row["date"] == "2023-08-15":
            return row
    return max(rows, key=lambda row: float(row["temperature_mean_c"]))


def _effect_at_reference(model: dict[str, Any], reference: dict[str, float]) -> dict[str, Any]:
    names = model["feature_names"]
    beta = np.asarray(model["beta"], dtype=float)
    covariance = np.asarray(model["covariance"], dtype=float)
    gradient = np.zeros(len(names) + 1)
    gradient[1 + names.index("cdd_18c")] = 1.0
    if "cdd_squared" in names:
        gradient[1 + names.index("cdd_squared")] = 2.0 * reference["cdd_18c"]
    estimate = float(gradient @ beta)
    variance = float(gradient @ covariance @ gradient)
    standard_error = math.sqrt(max(variance, 0.0))
    return {
        "name": "change_in_mean_demand_per_1c_cdd_at_reference",
        "estimate_mw_per_c": estimate,
        "standard_error": standard_error,
        "interval_95": [estimate - 1.96 * standard_error, estimate + 1.96 * standard_error],
        "reference_cdd_18c": reference["cdd_18c"],
        "interpretation": "conditional association; not an identified causal effect",
    }


def _serialise_artifact(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "atlas.economic.model_artifact.v1",
        "family": model["family"],
        "feature_names": model["feature_names"],
        "coefficients": [float(value) for value in model["beta"]],
        "covariance": [[float(value) for value in row] for row in model["covariance"]],
        "standard_errors": [float(value) for value in model["standard_errors"]],
        "residual_sigma": model["residual_sigma"],
        "condition_number": model["condition_number"],
        "train_rows": model["train_rows"],
        "causal_status": "association",
        "identification": "none",
    }


def run_weather_demand(panel: dict[str, Any], *, seed: int = 20261105) -> dict[str, Any]:
    rows = panel["rows"]
    if len(rows) < 180:
        raise ValueError("at least 180 complete daily observations are required")
    train_end = int(len(rows) * 0.70)
    validation_end = int(len(rows) * 0.85)
    parts = {
        "train": rows[:train_end],
        "validation": rows[train_end:validation_end],
        "test": rows[validation_end:],
    }
    candidates = {
        "seasonal_baseline": BASE_FEATURES,
        "degree_day_linear": BASE_FEATURES + WEATHER_LINEAR,
        "degree_day_curvature": BASE_FEATURES + WEATHER_CURVATURE,
    }
    validation: dict[str, Any] = {}
    for key, feature_names in candidates.items():
        matrix, target, _ = design(parts["train"], feature_names)
        fit = _ols(matrix, target)
        val_matrix, val_target, _ = design(parts["validation"], feature_names)
        prediction = val_matrix @ fit["beta"]
        validation[key] = {
            "features": feature_names,
            "metrics": _metrics(val_target, prediction),
            "fit": fit,
        }
    selected_key = min(validation, key=lambda key: validation[key]["metrics"]["rmse"])
    selected = validation[selected_key]

    # Refit the selected model and the baseline on train+validation only. The test
    # interval has not been used for feature or model selection.
    fit_rows = rows[:validation_end]
    final_matrix, final_target, _ = design(fit_rows, selected["features"])
    final_fit = _ols(final_matrix, final_target)
    test_matrix, test_target, test_features = design(parts["test"], selected["features"])
    test_prediction = test_matrix @ final_fit["beta"]
    test_metrics = _metrics(test_target, test_prediction)

    baseline_matrix, baseline_target, _ = design(fit_rows, BASE_FEATURES)
    baseline_fit = _ols(baseline_matrix, baseline_target)
    baseline_test_matrix, _, _ = design(parts["test"], BASE_FEATURES)
    baseline_prediction = baseline_test_matrix @ baseline_fit["beta"]
    baseline_test = _metrics(test_target, baseline_prediction)

    alternatives = {}
    for key in ("degree_day_linear", "degree_day_curvature"):
        if key == selected_key:
            continue
        matrix, target, _ = design(fit_rows, candidates[key])
        fit = _ols(matrix, target)
        alternatives[key] = {
            "features": candidates[key],
            "coefficients": [float(value) for value in fit["beta"]],
            "covariance": [[float(value) for value in row] for row in fit["covariance"]],
            "residual_sigma": fit["residual_sigma"],
            "test": _metrics(test_target, design(parts["test"], candidates[key])[0] @ fit["beta"]),
        }

    reference_row = _reference_row(rows)
    reference_features = feature_row(reference_row)
    reference_vector = np.asarray([1.0] + [reference_features[name] for name in selected["features"]], dtype=float)
    reference_prediction = float(reference_vector @ final_fit["beta"])
    effect = _effect_at_reference({
        "feature_names": selected["features"],
        "beta": final_fit["beta"],
        "covariance": final_fit["covariance"],
    }, reference_features)
    forecast = continuous_forecast_document(
        as_of=iso(utcnow()), horizon_days=1, unit="MW",
        model_id=f"weather-demand:{selected_key}:{MODEL_VERSION}",
        point=reference_prediction,
        lower=reference_prediction - 1.645 * final_fit["residual_sigma"],
        upper=reference_prediction + 1.645 * final_fit["residual_sigma"],
        data_class=panel["rows"][0].get("data_class", "observed"),
        assumptions=[
            "Conditional same-day relationship using observed Dallas station temperature.",
            "The point forecast applies to the reference day, not an unknown future day.",
        ],
        limitations=[
            "No day-ahead weather forecast is used.",
            "Prediction interval uses training residual variance, not a posterior.",
            "Weather is not randomly assigned, so this is not a causal forecast.",
        ],
    )
    skill = 1.0 - test_metrics["rmse"] / baseline_test["rmse"] if baseline_test["rmse"] else 0.0
    forecast_status = "unstable" if test_metrics["r2"] < 0 else "supported"
    if skill > 0 and selected_key != "seasonal_baseline" and forecast_status == "unstable":
        conclusion = "association_supported_forecast_unstable"
    elif skill > 0 and selected_key != "seasonal_baseline":
        conclusion = "association_supported_with_caveats"
    else:
        conclusion = "not_supported"
    artifact = _serialise_artifact({
        "family": selected_key,
        "feature_names": selected["features"],
        "beta": final_fit["beta"],
        "covariance": final_fit["covariance"],
        "standard_errors": final_fit["standard_errors"],
        "residual_sigma": final_fit["residual_sigma"],
        "condition_number": final_fit["condition_number"],
        "train_rows": len(fit_rows),
    })
    fingerprint = digest({
        "panel": panel.get("row_count"), "start": panel.get("start"), "end": panel.get("end"),
        "artifact": artifact, "seed": seed, "selected": selected_key,
    })
    audit = {
        "overall_score": None,
        "findings": [
            {"finding_key": "observational_association", "severity": "warning",
             "summary": "Weather is not randomly assigned; the coefficient is an association, not an identified causal effect.",
             "limitation": "Omitted variables, simultaneity and measurement error are not resolved."},
            {"finding_key": "point_station_representativeness", "severity": "warning",
             "summary": "Dallas/Fort Worth airport is a point station, not an area-weighted temperature for ERCOT.",
             "limitation": "Spatial aggregation error is not quantified."},
            {"finding_key": "current_archive_not_vintage", "severity": "warning",
             "summary": "The panel uses a current public bulk archive with a retrieval availability proxy.",
             "limitation": "It is not a point-in-time as-issued historical vintage."},
            {"finding_key": "short_single_region_sample", "severity": "warning",
             "summary": f"The untouched test interval contains {test_metrics['observations']} days in one region and one year.",
             "limitation": "No claim of generalisation beyond this place and period."},
            {"finding_key": "test_regime_instability", "severity": "warning",
             "summary": f"Test R² is {test_metrics['r2']:.3f} and mean error is {test_metrics['mean_error']:.0f} MW; the model beats the seasonal baseline but not a constant test mean.",
             "limitation": "The late-year test window shows level bias; do not present this as a stable load forecast."},
            {"finding_key": "hypothetical_financial_exposure", "severity": "info",
             "summary": "The company exposure is explicitly hypothetical and is never used as observed operating data.",
             "limitation": "No corporate contract, facility load or power price is asserted."},
        ],
        "counts": {"error": 0, "warning": 5, "info": 1},
    }
    return {
        "schema": MODEL_SCHEMA,
        "model_version": MODEL_VERSION,
        "run_id": f"ERUN-{fingerprint[:16]}",
        "fingerprint": fingerprint,
        "generated_at": iso(utcnow()),
        "dataset": {
            "dataset_id": "ECODS-ERCOT-DALLAS-2023",
            "name": "ERCOT demand and Dallas weather, 2023",
            "source_ids": ["eia-930", "noaa-ghcn"],
            "data_class": "observed",
            "start": panel["start"], "end": panel["end"],
            "rows": panel["row_count"],
            "content_hash": digest(panel["rows"]),
            "rights": "U.S. Government public domain",
            "vintage": "current public archive, retrieval proxy; not point-in-time verified",
        },
        "split": {
            "scheme": "chronological 70/15/15",
            "train": {"start": parts["train"][0]["date"], "end": parts["train"][-1]["date"], "rows": len(parts["train"])},
            "validation": {"start": parts["validation"][0]["date"], "end": parts["validation"][-1]["date"], "rows": len(parts["validation"])},
            "test": {"start": parts["test"][0]["date"], "end": parts["test"][-1]["date"], "rows": len(parts["test"])},
            "test_used_for_selection": False,
            "embargo": 0,
        },
        "candidates": {
            key: {"features": item["features"], "validation": item["metrics"],
                  "test": (test_metrics if key == selected_key else (
                      baseline_test if key == "seasonal_baseline" else alternatives[key]["test"]))}
            for key, item in validation.items()
        },
        "selection": {"selected_model": selected_key, "criterion": "validation_rmse",
                      "validation_rmse": selected["metrics"]["rmse"]},
        "model": artifact,
        "reference": {
            "date": reference_row["date"],
            "temperature_mean_c": float(reference_row["temperature_mean_c"]),
            "cdd_18c": float(reference_row["cooling_degree_day_18c"]),
            "hdd_18c": float(reference_row["heating_degree_day_18c"]),
            "features": reference_features,
            "predicted_demand_mw": reference_prediction,
            "observed_demand_mw": float(reference_row["demand_mean_mw"]),
        },
        "alternatives": alternatives,
        "test": test_metrics,
        "baseline": baseline_test,
        "skill_vs_seasonal": skill,
        "forecast_status": forecast_status,
        "association_effect": effect,
        "continuous_forecast": forecast,
        "residual_diagnostics": {
            "durbin_watson": _durbin_watson(final_fit["residual"]),
            "condition_number": final_fit["condition_number"],
            "residual_sigma_mw": final_fit["residual_sigma"],
            "test_mean_error_mw": test_metrics["mean_error"],
        },
        "causal_status": "not_identified",
        "causal_claim": {
            "status": "association",
            "identification": "none",
            "question": "Does higher Dallas-area temperature cause higher ERCOT daily mean demand?",
            "why_not_causal": [
                "Weather is not randomly assigned.",
                "Economic activity, air-conditioning adoption and price response are omitted.",
                "A point station is not an area-weighted regional exposure.",
                "No exogenous shock or credible counterfactual is used.",
            ],
            "reported_quantity": "conditional association, not an identified causal effect",
        },
        "audit": audit,
        "conclusion": conclusion,
        "limitations": [
            "One year, one balancing authority and one primary station.",
            "Same-day conditional relationship; not a day-ahead load forecast.",
            "Current bulk archive; availability is a retrieval proxy, not a historical vintage.",
            "No causal identification and no claim of generalisation.",
            "Financial consequences use hypothetical firm exposure assumptions.",
        ],
    }
