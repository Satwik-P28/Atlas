"""Typed forecast, model and experiment document contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow

LEARNING_SCHEMA = "atlas.learning.run.v2"
MODEL_SCHEMA = "atlas.learning.model.v2"
FORECAST_SCHEMA = "atlas.forecast.v1"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def validate_probability(value: Any, field: str = "probability") -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be numeric", value=value) from exc
    if not 0.0 <= number <= 1.0:
        raise ValidationError(f"{field} must be in [0,1]", value=number)
    return number


def forecast_document(
    *,
    model_id: str,
    security_id: str,
    as_of: str,
    horizon: int,
    probability: float,
    lower: float | None = None,
    upper: float | None = None,
    data_class: str = "observed",
) -> dict[str, Any]:
    p = validate_probability(probability)
    return {
        "schema": FORECAST_SCHEMA,
        "forecast_id": f"FCST-{digest([model_id, security_id, as_of, horizon, p])[:20]}",
        "model_id": model_id,
        "security_id": security_id,
        "as_of": as_of,
        "horizon_sessions": int(horizon),
        "kind": "binary_probability",
        "probability": p,
        "outcome_space": {"values": [0, 1], "definition": "price direction over the declared horizon"},
        "prediction_interval": None if lower is None or upper is None else {
            "lower": float(lower), "upper": float(upper), "level": 0.90,
            "method": "training residual approximation",
        },
        "data_class": data_class,
        "decision_rule": None,
        "limitations": [
            "A probability forecast is not a trading instruction.",
            "The outcome must be observed after as_of; it cannot be scored with information known at forecast time.",
        ],
    }


def continuous_forecast_document(
    *, model_id: str, security_id: str, as_of: str, horizon: int,
    value: float, lower: float, upper: float, data_class: str = "observed",
) -> dict[str, Any]:
    return {
        "schema": FORECAST_SCHEMA,
        "forecast_id": f"FCST-{digest([model_id, security_id, as_of, horizon, value])[:20]}",
        "model_id": model_id,
        "security_id": security_id,
        "as_of": as_of,
        "horizon_sessions": int(horizon),
        "kind": "continuous_return",
        "value": float(value),
        "units": "simple return",
        "prediction_interval": {"lower": float(lower), "upper": float(upper), "level": 0.90,
                                "method": "training residual approximation"},
        "data_class": data_class,
        "decision_rule": None,
        "limitations": ["The interval is an approximation, not a calibrated posterior distribution."],
    }


def model_document(
    *,
    name: str,
    version: str,
    artifact: dict[str, Any],
    result: dict[str, Any],
    source_ids: list[str],
) -> dict[str, Any]:
    metrics = result.get("test", {})
    return {
        "schema_version": "atlas.research_object.v1",
        "kind": "model",
        "name": name,
        "version": version,
        "status": "validated",
        "description": "Immutable Phase 6 calibrated probability model artifact.",
        "as_of": iso(utcnow()),
        "mode": "atlas_ingested",
        "evidence_ids": [],
        "source_ids": sorted(set(source_ids)),
        "object_ids": [],
        "assumptions": [
            "Features use session t information and labels use t+1.",
            "Scaling and calibration are fitted on training/validation rows only.",
        ],
        "limitations": result.get("limitations", []),
        "spec": {
            "inputs": result.get("features", []),
            "outputs": ["probability", "next_session_return"],
            "method": result.get("selected_model"),
            "assumptions": {"horizon_sessions": 1, "target": result.get("target")},
            "validation": {
                "brier": metrics.get("brier"),
                "log_loss": metrics.get("log_loss"),
                "brier_skill_vs_climatology": metrics.get("brier_skill_vs_climatology"),
                "test_used_for_selection": False,
            },
            "artifact": artifact,
            "artifact_fingerprint": result.get("model", {}).get("fingerprint"),
            "dataset_id": result.get("dataset", {}).get("dataset_id"),
            "data_class": result.get("dataset", {}).get("data_class"),
        },
    }


def experiment_document(
    *, name: str, run: dict[str, Any], model_object_id: str, source_ids: list[str]
) -> dict[str, Any]:
    return {
        "schema_version": "atlas.research_object.v1",
        "kind": "experiment",
        "name": name,
        "version": "1.0.0",
        "status": "validated",
        "description": "Chronological Phase 6 forecasting experiment with retained attempts.",
        "as_of": iso(utcnow()),
        "mode": "atlas_ingested",
        "evidence_ids": [],
        "source_ids": sorted(set(source_ids)),
        "object_ids": [model_object_id],
        "assumptions": ["The test interval is evaluated once after validation selection."],
        "limitations": run.get("limitations", []),
        "spec": {
            "hypothesis": run.get("hypothesis"),
            "method": "chronological train/validation/test with calibration and a frozen test interval",
            "metrics": run.get("test"),
            "run_id": run.get("run_id"),
            "attempts": run.get("attempts"),
            "audit": {
                "counts": (run.get("audit") or {}).get("counts"),
                "findings": [
                    {"finding_key": item.get("finding_key"), "severity": item.get("severity"),
                     "summary": item.get("summary")}
                    for item in ((run.get("audit") or {}).get("findings") or [])
                ],
                "overall_score": None,
            },
        },
    }


__all__ = [
    "FORECAST_SCHEMA",
    "LEARNING_SCHEMA",
    "MODEL_SCHEMA",
    "canonical",
    "continuous_forecast_document",
    "digest",
    "experiment_document",
    "forecast_document",
    "model_document",
    "validate_probability",
]
