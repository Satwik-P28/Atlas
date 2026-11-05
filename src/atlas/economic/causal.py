"""Small, explicitly-identified causal estimators.

These functions are intentionally separate from the observational weather-demand
model. A regression with controls is not automatically causal; callers must supply
a design and assumptions. The functions return estimates with named limitations.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..core.errors import ValidationError


def classify_design(design: str) -> dict[str, Any]:
    known = {
        "observational_regression": ("association", "not_identified",
            "No treatment assignment or exogenous variation is declared."),
        "difference_in_differences": ("estimated_causal_effect", "identified",
            "Parallel trends and no anticipation must hold."),
        "interrupted_time_series": ("estimated_causal_effect", "identified",
            "No concurrent shock and a stable pre-intervention trend must hold."),
    }
    if design not in known:
        raise ValidationError("unknown causal design", design=design, supported=sorted(known))
    status, causal, note = known[design]
    return {"design": design, "epistemic_status": status, "causal_status": causal, "assumption": note}


def two_by_two_difference_in_differences(
    rows: list[dict[str, Any]], *, outcome: str, treated: str, post: str,
) -> dict[str, Any]:
    """Classic 2x2 DiD with a Welch-style sampling-variance approximation.

    The caller is responsible for the parallel-trends design and for supplying a
    genuinely untreated comparison group. This function does not search for one.
    """
    if not rows:
        raise ValidationError("DiD requires observations")
    cells: dict[tuple[bool, bool], list[float]] = {(False, False): [], (False, True): [],
                                                   (True, False): [], (True, True): []}
    for row in rows:
        key = (bool(row[treated]), bool(row[post]))
        cells[key].append(float(row[outcome]))
    if any(not values for values in cells.values()):
        raise ValidationError("DiD requires all four treatment/post cells")
    means = {key: float(np.mean(values)) for key, values in cells.items()}
    variances = {key: float(np.var(values, ddof=1) / len(values)) if len(values) > 1 else 0.0
                 for key, values in cells.items()}
    estimate = (means[(True, True)] - means[(True, False)]
                - (means[(False, True)] - means[(False, False)]))
    variance = sum(variances.values())
    se = math.sqrt(max(variance, 0.0))
    return {
        "estimator": "two_by_two_difference_in_differences",
        "estimate": estimate,
        "standard_error": se,
        "interval_95": [estimate - 1.96 * se, estimate + 1.96 * se],
        "cell_means": {f"treated_{int(t)}_post_{int(p)}": value for (t, p), value in means.items()},
        "cell_sizes": {f"treated_{int(t)}_post_{int(p)}": len(cells[(t, p)]) for t, p in cells},
        "assumptions": ["parallel trends", "no anticipation", "stable composition",
                        "no concurrent treatment-specific shock"],
        "causal_status": "identified",
        "note": "This design is only valid when the comparison group and timing are defensible.",
    }


def interrupted_time_series(
    rows: list[dict[str, Any]], *, outcome: str, time: str, post: str,
    treatment_time: float,
) -> dict[str, Any]:
    """OLS interrupted time series with level and slope changes.

    Concurrent shocks are not detected automatically. The result is reported as an
    identified estimate only because the caller declared an intervention time.
    """
    ordered = sorted(rows, key=lambda row: float(row[time]))
    if len(ordered) < 8:
        raise ValidationError("interrupted time series requires at least eight observations")
    times = np.asarray([float(row[time]) for row in ordered], dtype=float)
    target = np.asarray([float(row[outcome]) for row in ordered], dtype=float)
    post_values = np.asarray([
        1.0 if bool(row[post]) or float(row[time]) >= treatment_time else 0.0 for row in ordered
    ])
    since = np.maximum(times - treatment_time, 0.0)
    matrix = np.column_stack([np.ones(len(ordered)), times, post_values, since])
    beta, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=None)
    if rank < matrix.shape[1]:
        raise ValidationError("interrupted time series design is rank deficient")
    residual = target - matrix @ beta
    dof = len(target) - matrix.shape[1]
    sigma2 = float(residual @ residual / dof) if dof > 0 else 0.0
    covariance = sigma2 * np.linalg.pinv(matrix.T @ matrix)
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    return {
        "estimator": "interrupted_time_series_ols",
        "level_change": float(beta[2]),
        "slope_change_per_unit_time": float(beta[3]),
        "standard_errors": {"level_change": float(se[2]), "slope_change": float(se[3])},
        "intervals_95": {
            "level_change": [float(beta[2] - 1.96 * se[2]), float(beta[2] + 1.96 * se[2])],
            "slope_change": [float(beta[3] - 1.96 * se[3]), float(beta[3] + 1.96 * se[3])],
        },
        "assumptions": ["stable pre-intervention trend", "no concurrent shock",
                        "correct intervention timing", "no endogenous treatment timing"],
        "causal_status": "identified",
        "note": "Refuse the causal label when a concurrent shock or endogenous timing is plausible.",
    }


def observational_policy() -> dict[str, Any]:
    return {
        "default": "association",
        "rule": "A regression with controls is not a causal estimate.",
        "requires_for_causal_label": ["declared intervention", "credible comparison or timing",
                                      "tested assumptions", "falsification tests"],
        "weather_demand_design": "observational_regression",
    }
