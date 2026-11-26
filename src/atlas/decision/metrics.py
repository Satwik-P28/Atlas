"""Decision and evaluation metrics with explicit definitions.

Two rules govern this module.

First, every metric states its units and its sign convention, because a regret that is
reported with the wrong sign silently reverses a conclusion.

Second, uncertainty on dependent observations is never estimated by resampling individual
points. Financial and operational series are serially dependent, so the interval machinery
here is a **moving-block bootstrap**, which preserves short-range dependence within blocks.
An independent-sample interval is not offered at all.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

import numpy as np

from ..core.errors import ValidationError


def decision_regret(problem: Any, weights: Sequence[float], optimal_objective: float) -> float:
    """``P(w) - P(w*)`` in objective units. Non-negative at an optimum, by definition."""

    return float(problem.objective(weights) - optimal_objective)


def turnover(previous: Sequence[float], current: Sequence[float]) -> float:
    """One-way turnover ``0.5 * ||w - w_prev||_1``: the fraction of the book traded."""

    a = np.asarray(previous, dtype=float)
    b = np.asarray(current, dtype=float)
    if a.shape != b.shape:
        raise ValidationError("turnover needs matching weight vectors",
                              previous=int(a.size), current=int(b.size))
    return float(0.5 * np.sum(np.abs(b - a)))


def cvar_historical(returns: Sequence[float], *, confidence: float = 0.95) -> float:
    """Mean of the worst ``1 - confidence`` tail. Negative values are losses."""

    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValidationError("CVaR needs at least one observation")
    if not 0.0 < confidence < 1.0:
        raise ValidationError("confidence must be in (0, 1)", confidence=confidence)
    ordered = np.sort(values)
    count = max(1, int(math.ceil((1.0 - confidence) * ordered.size)))
    return float(np.mean(ordered[:count]))


def max_drawdown(period_returns: Sequence[float]) -> float:
    """Largest peak-to-trough decline of the compounded equity curve, as a positive number."""

    values = np.asarray(period_returns, dtype=float)
    # Start the curve at 1.0 so a decline in the first period is measured against the
    # capital that existed before it. Without the leading point a one-period loss shows
    # zero drawdown, which is wrong.
    equity = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    return float(-np.min(drawdown)) if drawdown.size else 0.0


def moving_block_bootstrap_ci(
    values: Sequence[float],
    *,
    statistic: Callable[[np.ndarray], float] = lambda sample: float(np.mean(sample)),
    block: int = 10,
    resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> dict[str, Any]:
    """Percentile interval for ``statistic`` under a moving-block bootstrap.

    ``block`` must exceed the dependence horizon the analyst is willing to assume. The
    interval is reported with the block length and the number of resamples so a reader can
    judge the assumption; it is not a distribution-free guarantee.
    """

    sample = np.asarray(values, dtype=float)
    n = sample.size
    if n < 2:
        raise ValidationError("bootstrap needs at least two observations", observations=n)
    block = max(1, min(int(block), n))
    if not 0.0 < confidence < 1.0:
        raise ValidationError("confidence must be in (0, 1)", confidence=confidence)
    rng = np.random.default_rng(seed)
    blocks_needed = int(math.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(resamples, blocks_needed))
    offsets = np.arange(block)
    draws = np.empty(resamples, dtype=float)
    for index in range(resamples):
        indices = (starts[index][:, None] + offsets[None, :]).ravel()[:n]
        draws[index] = statistic(sample[indices])
    alpha = (1.0 - confidence) / 2.0
    return {
        "statistic": float(statistic(sample)),
        "lower": float(np.quantile(draws, alpha)),
        "upper": float(np.quantile(draws, 1.0 - alpha)),
        "confidence": confidence,
        "block_length": block,
        "resamples": resamples,
        "method": "moving_block_bootstrap_percentile",
        "observations": n,
        "caveat": "interval validity depends on the block length exceeding the dependence horizon",
    }


def summarize(values: Sequence[float]) -> dict[str, float | int | None]:
    sample = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], dtype=float)
    if sample.size == 0:
        return {"count": 0, "mean": None, "median": None, "p05": None, "p95": None, "max": None}
    return {
        "count": int(sample.size),
        "mean": float(np.mean(sample)),
        "median": float(np.median(sample)),
        "p05": float(np.quantile(sample, 0.05)),
        "p95": float(np.quantile(sample, 0.95)),
        "max": float(np.max(sample)),
    }


__all__ = [
    "cvar_historical",
    "decision_regret",
    "max_drawdown",
    "moving_block_bootstrap_ci",
    "summarize",
    "turnover",
]
