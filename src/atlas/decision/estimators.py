"""Forecast inputs for decision problems: means, covariances and shrinkage.

Only three estimators are provided, because the experiments need a defensible input rather
than a model zoo:

* the sample mean and covariance (transparent, unstable, and the honest default);
* Ledoit-Wolf shrinkage towards a scaled identity, which guarantees a positive definite risk
  matrix with a data-driven intensity, so the dual bound used by the certificates exists;
* diagonal loading, labelled as *numerical regularisation* rather than as a statistical
  estimator.

The Ledoit-Wolf intensity here is the closed-form univariate-target formula. It is checked
against scikit-learn's independent implementation in the test suite; a disagreement of more
than the stated tolerance is a test failure, not a note.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from ..core.errors import ValidationError

ESTIMATOR_SCHEMA = "atlas.decision.covariance_estimate.v1"


def _as_matrix(returns: Sequence[Sequence[float]]) -> np.ndarray:
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2:
        raise ValidationError("returns must be a two-dimensional array", shape=list(matrix.shape))
    if matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValidationError("returns need at least two observations and one asset",
                              shape=list(matrix.shape))
    if not np.all(np.isfinite(matrix)):
        raise ValidationError("returns must be finite")
    return matrix


def sample_covariance(returns: Sequence[Sequence[float]], *, ddof: int = 1) -> np.ndarray:
    matrix = _as_matrix(returns)
    if matrix.shape[0] <= ddof:
        raise ValidationError("not enough observations for the requested ddof",
                              observations=int(matrix.shape[0]), ddof=ddof)
    centred = matrix - matrix.mean(axis=0, keepdims=True)
    covariance = centred.T @ centred / float(matrix.shape[0] - ddof)
    return (covariance + covariance.T) / 2.0


def sample_mean(returns: Sequence[Sequence[float]]) -> np.ndarray:
    return _as_matrix(returns).mean(axis=0)


def ledoit_wolf_covariance(
    returns: Sequence[Sequence[float]],
    *,
    assume_centered: bool = False,
) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf shrinkage towards ``mu * I`` with ``mu = trace(S) / n``.

    Returns ``(covariance, shrinkage)``. The intensity is clipped to ``[0, 1]`` and the
    result is symmetrised. With ``T < n`` the sample covariance is singular and the shrinkage
    is what keeps the dual bound finite, so the returned matrix is positive definite whenever
    the data are not degenerate.
    """

    matrix = _as_matrix(returns)
    if not assume_centered:
        matrix = matrix - matrix.mean(axis=0, keepdims=True)
    n_samples, n_features = matrix.shape
    empirical = matrix.T @ matrix / float(n_samples)
    empirical = (empirical + empirical.T) / 2.0
    mu = float(np.trace(empirical)) / n_features
    target = mu * np.eye(n_features)
    delta = float(np.sum((empirical - target) ** 2)) / n_features
    if delta <= 0.0:
        return target, 1.0
    squared = matrix ** 2
    beta_matrix = (squared.T @ squared) / float(n_samples) - empirical ** 2
    beta = float(np.sum(beta_matrix)) / n_features
    shrinkage = max(0.0, min(1.0, beta / delta))
    covariance = shrinkage * target + (1.0 - shrinkage) * empirical
    return (covariance + covariance.T) / 2.0, shrinkage


def diagonal_loading(covariance: Sequence[Sequence[float]], *, floor: float = 1e-6) -> np.ndarray:
    """Add ``floor * trace(Σ)/n * I``. Numerical regularisation, not an estimator."""

    matrix = np.asarray(covariance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValidationError("covariance must be square", shape=list(matrix.shape))
    if floor < 0 or not math.isfinite(floor):
        raise ValidationError("floor must be finite and non-negative", floor=floor)
    n = matrix.shape[0]
    scale = float(np.trace(matrix)) / n if n else 0.0
    loaded = matrix + (floor * max(scale, 0.0)) * np.eye(n)
    return (loaded + loaded.T) / 2.0


def covariance_diagnostics(covariance: Sequence[Sequence[float]]) -> dict[str, Any]:
    matrix = np.asarray(covariance, dtype=float)
    eigenvalues = np.linalg.eigvalsh((matrix + matrix.T) / 2.0)
    largest = float(eigenvalues[-1])
    smallest = float(eigenvalues[0])
    return {
        "schema": ESTIMATOR_SCHEMA,
        "dimension": int(matrix.shape[0]),
        "smallest_eigenvalue": smallest,
        "largest_eigenvalue": largest,
        "positive_definite": bool(smallest > 0.0),
        "condition_number": float(largest / smallest) if smallest > 0 else float("inf"),
        "trace": float(np.trace(matrix)),
    }


__all__ = [
    "ESTIMATOR_SCHEMA",
    "covariance_diagnostics",
    "diagonal_loading",
    "ledoit_wolf_covariance",
    "sample_covariance",
    "sample_mean",
]
