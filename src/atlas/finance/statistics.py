"""Small, explicit statistical primitives for portfolio research.

No NumPy/SciPy dependency is introduced: the portfolio sizes in this scoped release are
small, and a readable implementation is easier to verify independently. The functions
state their annualization and missing-data conventions rather than hiding them.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any, Sequence

from ..core.errors import ValidationError


def _numbers(values: Sequence[Any], field: str = "values") -> list[float]:
    result = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field} must be numeric", value=value) from exc
        if not math.isfinite(number):
            raise ValidationError(f"{field} must be finite", value=value)
        result.append(number)
    return result


def portfolio_returns(matrix: Sequence[Sequence[float]], weights: Sequence[float]) -> list[float]:
    """Return wᵀr for each row of an aligned returns matrix."""
    if not matrix:
        return []
    rows = [_numbers(row) for row in matrix]
    weights = _numbers(weights, "weights")
    if any(len(row) != len(weights) for row in rows):
        raise ValidationError("returns matrix columns must equal weights")
    return [sum(w * r for w, r in zip(weights, row)) for row in rows]


def covariance_matrix(
    matrix: Sequence[Sequence[float]], *, sample: bool = True, shrinkage: float = 0.0,
) -> list[list[float]]:
    """Covariance of aligned observations, with optional diagonal shrinkage."""
    if not matrix:
        raise ValidationError("covariance requires observations")
    rows = [_numbers(row) for row in matrix]
    n = len(rows[0])
    if any(len(row) != n for row in rows):
        raise ValidationError("returns matrix must be rectangular")
    if len(rows) < 2:
        raise ValidationError("covariance requires at least two observations")
    shrinkage = float(shrinkage)
    if not 0.0 <= shrinkage <= 1.0:
        raise ValidationError("shrinkage must be between 0 and 1", shrinkage=shrinkage)
    divisor = (len(rows) - 1) if sample else len(rows)
    means = [sum(row[i] for row in rows) / len(rows) for i in range(n)]
    covariance = [
        [sum((row[i] - means[i]) * (row[j] - means[j]) for row in rows) / divisor
         for j in range(n)]
        for i in range(n)
    ]
    if shrinkage:
        # Shrink toward the diagonal. This is a transparent stabilization option, not
        # a claim that it solves covariance estimation or makes expected returns valid.
        for i in range(n):
            diagonal = covariance[i][i]
            for j in range(n):
                target = diagonal if i == j else 0.0
                covariance[i][j] = (1 - shrinkage) * covariance[i][j] + shrinkage * target
    return covariance


def annualized_return(returns: Sequence[float], periods: int = 252) -> float:
    values = _numbers(returns)
    if not values:
        raise ValidationError("return series is empty")
    growth = 1.0
    for value in values:
        if value <= -1:
            raise ValidationError("simple return cannot be -100% or less", value=value)
        growth *= 1.0 + value
    return growth ** (periods / len(values)) - 1.0


def annualized_volatility(returns: Sequence[float], periods: int = 252) -> float:
    values = _numbers(returns)
    if len(values) < 2:
        return 0.0
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance) * math.sqrt(periods)


def max_drawdown(values: Sequence[float]) -> float:
    numbers = _numbers(values)
    if not numbers:
        return 0.0
    peak = numbers[0]
    worst = 0.0
    for value in numbers:
        peak = max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1.0)
    return worst


def historical_var(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Positive loss at the lower-tail (1 - confidence) quantile."""
    values = _numbers(returns)
    if not values:
        raise ValidationError("return series is empty")
    if not 0 < confidence < 1:
        raise ValidationError("confidence must be between 0 and 1", confidence=confidence)
    ordered = sorted(values)
    # At 95% confidence this is the 5% lower-tail quantile of returns, not the
    # 95th percentile of returns. Using ceil(confidence*n) inverted the tail.
    index = max(0, min(len(ordered) - 1, int(math.floor((1.0 - confidence) * len(ordered)))))
    return max(0.0, -ordered[index])


def expected_shortfall(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Average loss in the tail at or below the historical VaR quantile."""
    values = _numbers(returns)
    if not values:
        raise ValidationError("return series is empty")
    if not 0 < confidence < 1:
        raise ValidationError("confidence must be between 0 and 1", confidence=confidence)
    ordered = sorted(values)
    count = max(1, int(math.ceil((1.0 - confidence) * len(ordered))))
    tail = ordered[:count]
    return max(0.0, -sum(tail) / len(tail))


def beta(portfolio: Sequence[float], benchmark: Sequence[float]) -> float | None:
    p, b = _numbers(portfolio), _numbers(benchmark)
    if len(p) != len(b) or len(p) < 2:
        return None
    pm, bm = mean(p), mean(b)
    variance = sum((value - bm) ** 2 for value in b)
    if variance == 0:
        return None
    return sum((x - pm) * (y - bm) for x, y in zip(p, b)) / variance


def correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    a, b = _numbers(left), _numbers(right)
    if len(a) != len(b) or len(a) < 2:
        return None
    am, bm = mean(a), mean(b)
    va = sum((value - am) ** 2 for value in a)
    vb = sum((value - bm) ** 2 for value in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - am) * (y - bm) for x, y in zip(a, b)) / math.sqrt(va * vb)


def solve_linear(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for small deterministic systems."""
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix) or len(vector) != n:
        raise ValidationError("linear system must be square")
    a = [list(map(float, row)) + [float(vector[i])] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(a[row][column]))
        if abs(a[pivot][column]) < 1e-14:
            raise ValidationError("linear system is singular", column=column)
        a[column], a[pivot] = a[pivot], a[column]
        divisor = a[column][column]
        a[column] = [value / divisor for value in a[column]]
        for row in range(n):
            if row == column:
                continue
            factor = a[row][column]
            if factor:
                a[row] = [a[row][i] - factor * a[column][i] for i in range(n + 1)]
    return [a[i][-1] for i in range(n)]


__all__ = [
    "annualized_return", "annualized_volatility", "beta", "correlation",
    "covariance_matrix", "expected_shortfall", "historical_var", "max_drawdown",
    "portfolio_returns", "solve_linear",
]
