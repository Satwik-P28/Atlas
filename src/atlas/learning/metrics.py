"""Independent forecast metrics.

The arithmetic here is intentionally not delegated to a metric library. Tests
recompute these identities from their definitions so a future backend cannot
change a reported Brier score or calibration table silently.
"""

from __future__ import annotations

import math
import random
from statistics import mean
from typing import Any, Iterable


def _pairs(probabilities: Iterable[float], outcomes: Iterable[float]) -> list[tuple[float, float]]:
    p = [float(value) for value in probabilities]
    y = [float(value) for value in outcomes]
    if len(p) != len(y) or not p:
        raise ValueError("probabilities and outcomes must be non-empty and aligned")
    for value in p:
        if not 0.0 <= value <= 1.0 or not math.isfinite(value):
            raise ValueError("probability outside [0,1]")
    for value in y:
        if value not in (0.0, 1.0):
            raise ValueError("binary outcome must be 0 or 1")
    return list(zip(p, y))


def brier_score(probabilities: Iterable[float], outcomes: Iterable[float]) -> float:
    pairs = _pairs(probabilities, outcomes)
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def log_loss(probabilities: Iterable[float], outcomes: Iterable[float], *, epsilon: float = 1e-12) -> float:
    pairs = _pairs(probabilities, outcomes)
    clipped = [(min(1 - epsilon, max(epsilon, p)), y) for p, y in pairs]
    return -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in clipped) / len(clipped)


def roc_auc(probabilities: Iterable[float], outcomes: Iterable[float]) -> float | None:
    pairs = _pairs(probabilities, outcomes)
    positives = [p for p, y in pairs if y == 1.0]
    negatives = [p for p, y in pairs if y == 0.0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            wins += 1.0 if positive > negative else 0.5 if positive == negative else 0.0
    return wins / (len(positives) * len(negatives))


def calibration_table(
    probabilities: Iterable[float], outcomes: Iterable[float], *, bins: int = 10
) -> list[dict[str, Any]]:
    pairs = _pairs(probabilities, outcomes)
    table = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [(p, y) for p, y in pairs
                   if (low <= p < high) or (index == bins - 1 and p == 1.0)]
        if not members:
            table.append({"bin": index, "low": low, "high": high, "count": 0,
                          "mean_probability": None, "observed_rate": None, "gap": None})
            continue
        predicted = mean(p for p, _ in members)
        observed = mean(y for _, y in members)
        table.append({"bin": index, "low": low, "high": high, "count": len(members),
                      "mean_probability": predicted, "observed_rate": observed,
                      "gap": predicted - observed})
    return table


def expected_calibration_error(
    probabilities: Iterable[float], outcomes: Iterable[float], *, bins: int = 10
) -> float:
    pairs = _pairs(probabilities, outcomes)
    table = calibration_table([p for p, _ in pairs], [y for _, y in pairs], bins=bins)
    total = len(pairs)
    return sum((row["count"] / total) * abs(row["gap"])
               for row in table if row["count"] and row["gap"] is not None)


def brier_skill_score(probability: float, probabilities: Iterable[float],
                      outcomes: Iterable[float]) -> float | None:
    pairs = _pairs(probabilities, outcomes)
    baseline = brier_score([probability] * len(pairs), [y for _, y in pairs])
    if baseline <= 0:
        return None
    return 1.0 - brier_score([p for p, _ in pairs], [y for _, y in pairs]) / baseline


def bootstrap_mean_ci(values: Iterable[float], *, seed: int = 20261105,
                      resamples: int = 600, confidence: float = 0.95) -> dict[str, Any]:
    sample = [float(value) for value in values]
    if len(sample) < 10:
        return {"estimate": None, "low": None, "high": None, "resamples": 0,
                "note": "fewer than ten observations"}
    rng = random.Random(seed)
    estimates = sorted(mean(rng.choice(sample) for _ in sample) for _ in range(resamples))
    tail = (1.0 - confidence) / 2.0
    return {
        "estimate": mean(sample),
        "low": estimates[int(tail * (resamples - 1))],
        "high": estimates[int((1 - tail) * (resamples - 1))],
        "confidence": confidence,
        "resamples": resamples,
        "method": "nonparametric bootstrap of the mean; not a guarantee for dependent rows",
    }


def paired_block_bootstrap(
    left: Iterable[float], right: Iterable[float], *, block: int = 10, seed: int = 20261105,
    resamples: int = 500,
) -> dict[str, Any]:
    """Bootstrap the mean paired difference with contiguous blocks."""
    a, b = [float(value) for value in left], [float(value) for value in right]
    if len(a) != len(b) or len(a) < 20:
        return {"estimate": None, "low": None, "high": None, "note": "insufficient paired observations"}
    differences = [x - y for x, y in zip(a, b)]
    estimate = mean(differences)
    rng = random.Random(seed)
    samples = []
    for _ in range(resamples):
        chosen: list[float] = []
        while len(chosen) < len(differences):
            start = rng.randrange(len(differences))
            chosen.extend(differences[start:start + block])
        samples.append(mean(chosen[:len(differences)]))
    samples.sort()
    return {"estimate": estimate, "low": samples[int(0.025 * (resamples - 1))],
            "high": samples[int(0.975 * (resamples - 1))],
            "confidence": 0.95, "block": block, "resamples": resamples,
            "method": "paired block bootstrap; dependence and small samples remain limitations"}


def summarize(probabilities: Iterable[float], outcomes: Iterable[float], *,
              bins: int = 10) -> dict[str, Any]:
    p, y = [float(value) for value in probabilities], [float(value) for value in outcomes]
    positives = sum(y)
    return {
        "observations": len(y),
        "prevalence": positives / len(y) if y else None,
        "brier": brier_score(p, y),
        "log_loss": log_loss(p, y),
        "auc": roc_auc(p, y),
        "accuracy_at_half": sum((1.0 if prob >= 0.5 else 0.0) == outcome
                                for prob, outcome in zip(p, y)) / len(y),
        "calibration_error": expected_calibration_error(p, y, bins=bins),
        "calibration": calibration_table(p, y, bins=bins),
        "bins": bins,
    }


__all__ = [
    "bootstrap_mean_ci",
    "brier_score",
    "brier_skill_score",
    "calibration_table",
    "expected_calibration_error",
    "log_loss",
    "paired_block_bootstrap",
    "roc_auc",
    "summarize",
]
