"""Small, auditable forecasting model library.

Artifacts are JSON dictionaries, never pickles. That keeps model loading free of
arbitrary code execution and makes a saved coefficient inspectable. The neural
network is intentionally tiny: its purpose is to test whether a learned nonlinear
boundary beats an honest linear baseline, not to imitate a foundation model.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from ..core.errors import NotSupportedError, ValidationError

MODEL_ARTIFACT_VERSION = "atlas.learning.model_artifact.v1"

MODEL_LIBRARY: tuple[dict[str, Any], ...] = (
    {
        "key": "climatology",
        "label": "Climatology baseline",
        "family": "baseline",
        "description": "Training prevalence assigned to every forecast.",
        "dependencies": ["numpy"],
    },
    {
        "key": "ridge",
        "label": "Regularised linear probability",
        "family": "linear",
        "description": "Ridge regression on the 0/1 target, clipped to [0,1].",
        "dependencies": ["numpy", "scikit-learn"],
    },
    {
        "key": "logistic",
        "label": "Logistic regression",
        "family": "generalised_linear",
        "description": "L2 logistic classifier with a training-only scaler.",
        "dependencies": ["numpy", "scikit-learn"],
    },
    {
        "key": "mlp",
        "label": "Small multilayer perceptron",
        "family": "neural_network",
        "description": "8-unit ReLU hidden layer; deterministic seed; JSON weights.",
        "dependencies": ["numpy", "scikit-learn"],
    },
)
MODEL_KEYS = tuple(item["key"] for item in MODEL_LIBRARY)


def require_scientific() -> tuple[Any, Any]:
    try:
        import numpy as np  # type: ignore
        from sklearn.linear_model import LogisticRegression, Ridge  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only in minimal installs
        raise NotSupportedError(
            "the Phase 6 learning runtime requires numpy and scikit-learn; "
            "install the `learning` extra",
            missing=str(exc),
        ) from exc
    return np, (LogisticRegression, Ridge)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _scaler(x: list[list[float]]) -> dict[str, list[float]]:
    if not x:
        raise ValidationError("cannot fit a scaler on no rows")
    columns = list(zip(*x))
    means = [sum(column) / len(column) for column in columns]
    scales = []
    for column, average in zip(columns, means):
        variance = sum((value - average) ** 2 for value in column) / max(1, len(column) - 1)
        scales.append(math.sqrt(variance) or 1.0)
    return {"mean": means, "scale": scales}


def _scale_row(row: list[float], scaler: dict[str, list[float]]) -> list[float]:
    return [(float(value) - mean) / scale
            for value, mean, scale in zip(row, scaler["mean"], scaler["scale"])]


def _scale(x: list[list[float]], scaler: dict[str, list[float]]) -> list[list[float]]:
    return [_scale_row(row, scaler) for row in x]


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -700.0))
    return z / (1.0 + z)


def _sigmoid_array(values: Any, np: Any) -> Any:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -50.0, 50.0)))


def fit_model(model_key: str, x: list[list[float]], y: list[float], *, seed: int = 20261105) -> dict[str, Any]:
    """Fit one model and return a portable JSON artifact."""
    if model_key not in MODEL_KEYS:
        raise ValidationError("unknown learning model", model=model_key, supported=list(MODEL_KEYS))
    if not x or len(x) != len(y):
        raise ValidationError("training rows and targets are not aligned")
    if len(set(y)) < 2:
        raise ValidationError("target has only one class; a probability model is not identifiable")
    np, (LogisticRegression, Ridge) = require_scientific()
    scaler = _scaler(x)
    scaled = np.asarray(_scale(x, scaler), dtype=float)
    target = np.asarray(y, dtype=float)
    artifact: dict[str, Any] = {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "model_key": model_key,
        "features": len(x[0]),
        "rows": len(x),
        "prevalence": float(target.mean()),
        "scaler": scaler,
        "seed": seed,
        "calibrator": None,
        "software": {"numpy": np.__version__, "scikit_learn": __import__("sklearn").__version__},
    }
    if model_key == "climatology":
        artifact["kind"] = "constant"
        artifact["intercept"] = float(target.mean())
        return artifact
    if model_key == "ridge":
        estimator = Ridge(alpha=1.0).fit(scaled, target)
        artifact.update({"kind": "linear", "coef": [float(v) for v in estimator.coef_.ravel()],
                         "intercept": float(estimator.intercept_)})
        return artifact
    if model_key == "logistic":
        estimator = LogisticRegression(C=1.0, max_iter=1000, random_state=seed).fit(scaled, target)
        artifact.update({"kind": "linear", "coef": [float(v) for v in estimator.coef_.ravel()],
                         "intercept": float(estimator.intercept_[0])})
        return artifact
    from sklearn.neural_network import MLPClassifier  # type: ignore

    estimator = MLPClassifier(
        hidden_layer_sizes=(8,), activation="relu", solver="adam", alpha=1e-3,
        batch_size=min(256, max(16, len(x) // 4)), learning_rate_init=0.01,
        max_iter=350, random_state=seed, early_stopping=False, shuffle=True,
    ).fit(scaled, target)
    artifact.update({
        "kind": "mlp",
        "coefs": [[[float(v) for v in row] for row in matrix] for matrix in estimator.coefs_],
        "intercepts": [[float(v) for v in row] for row in estimator.intercepts_],
        "hidden_activation": "relu",
        "output_activation": "logistic",
    })
    return artifact


def predict_raw(artifact: dict[str, Any], x: list[list[float]]) -> list[float]:
    np, _ = require_scientific()
    kind = artifact.get("kind")
    if kind == "constant":
        return [float(artifact["intercept"]) for _ in x]
    scaled = np.asarray(_scale(x, artifact["scaler"]), dtype=float)
    if kind == "linear":
        coef = np.asarray(artifact["coef"], dtype=float)
        values = scaled @ coef + float(artifact["intercept"])
        if artifact["model_key"] == "ridge":
            return [float(min(1.0, max(0.0, value))) for value in values]
        return [float(value) for value in _sigmoid_array(values, np)]
    if kind == "mlp":
        values = scaled
        for index, (weights, intercept) in enumerate(zip(artifact["coefs"], artifact["intercepts"])):
            values = values @ np.asarray(weights, dtype=float) + np.asarray(intercept, dtype=float)
            if index < len(artifact["coefs"]) - 1:
                values = np.maximum(values, 0.0)
            else:
                values = _sigmoid_array(values, np)
        return [float(value) for value in values.ravel()]
    raise ValidationError("unknown model artifact kind", kind=kind)


def fit_calibrator(artifact: dict[str, Any], x: list[list[float]], y: list[float]) -> dict[str, Any]:
    """Fit Platt scaling on validation rows only; returns a new artifact."""
    np, (LogisticRegression, _) = require_scientific()
    if len(set(y)) < 2:
        return {**artifact, "calibrator": None,
                "calibration_note": "validation contained one class; raw probabilities retained"}
    probabilities = predict_raw(artifact, x)
    logits = np.asarray([[math.log(max(1e-6, p) / max(1e-6, 1 - p))] for p in probabilities])
    estimator = LogisticRegression(C=1.0, max_iter=1000).fit(logits, np.asarray(y, dtype=float))
    return {
        **artifact,
        "calibrator": {
            "method": "platt",
            "coef": float(estimator.coef_[0][0]),
            "intercept": float(estimator.intercept_[0]),
            "fitted_rows": len(y),
        },
    }


def predict(artifact: dict[str, Any], x: list[list[float]], *, calibrated: bool = True) -> list[float]:
    raw = predict_raw(artifact, x)
    calibrator = artifact.get("calibrator")
    if not calibrated or not calibrator:
        return [min(1.0, max(0.0, value)) for value in raw]
    values = []
    for probability in raw:
        logit = math.log(max(1e-9, probability) / max(1e-9, 1 - probability))
        values.append(_sigmoid(calibrator["coef"] * logit + calibrator["intercept"]))
    return values


def fit_return_model(x: list[list[float]], y: list[float], *, seed: int = 20261105) -> dict[str, Any]:
    np, (_, Ridge) = require_scientific()
    scaler = _scaler(x)
    scaled = np.asarray(_scale(x, scaler), dtype=float)
    target = np.asarray(y, dtype=float)
    estimator = Ridge(alpha=1.0).fit(scaled, target)
    residual = target - estimator.predict(scaled)
    sigma = float(np.std(residual, ddof=1)) if len(residual) > 1 else 0.0
    return {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "kind": "return_linear",
        "model_key": "return_ridge",
        "features": len(x[0]),
        "rows": len(x),
        "scaler": scaler,
        "coef": [float(v) for v in estimator.coef_.ravel()],
        "intercept": float(estimator.intercept_),
        "residual_sigma": sigma,
        "interval": "point forecast ± 1.645 training residual sigma; not a calibrated predictive distribution",
        "seed": seed,
    }


def predict_return(artifact: dict[str, Any], x: list[list[float]]) -> list[dict[str, float]]:
    np, _ = require_scientific()
    scaled = np.asarray(_scale(x, artifact["scaler"]), dtype=float)
    coef = np.asarray(artifact["coef"], dtype=float)
    values = scaled @ coef + float(artifact["intercept"])
    width = 1.645 * float(artifact["residual_sigma"])
    return [{"value": float(value), "lower": float(value - width), "upper": float(value + width)}
            for value in values]


def artifact_fingerprint(artifact: dict[str, Any]) -> str:
    return _hash(artifact)


def model_metadata(model_key: str) -> dict[str, Any]:
    item = next((entry for entry in MODEL_LIBRARY if entry["key"] == model_key), None)
    if item is None:
        raise ValidationError("unknown learning model", model=model_key)
    return dict(item)


__all__ = [
    "MODEL_ARTIFACT_VERSION",
    "MODEL_KEYS",
    "MODEL_LIBRARY",
    "artifact_fingerprint",
    "fit_calibrator",
    "fit_model",
    "fit_return_model",
    "model_metadata",
    "predict",
    "predict_raw",
    "predict_return",
    "require_scientific",
]
