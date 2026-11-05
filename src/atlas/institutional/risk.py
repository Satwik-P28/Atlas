"""Aligned multi-asset risk, historical scenarios and constrained optimization."""

from __future__ import annotations

import itertools
import math
from typing import Any, Sequence

from ..core.errors import ValidationError
from ..finance.statistics import (
    annualized_return,
    annualized_volatility,
    beta,
    covariance_matrix,
    expected_shortfall,
    historical_var,
    max_drawdown,
    portfolio_returns,
    solve_linear,
)
from .universe import returns_matrix

RISK_SCHEMA = "atlas.institutional.portfolio_risk.v1"
OPTIMIZER_SCHEMA = "atlas.institutional.optimizer.v1"


def _weights(weights: dict[str, float] | Sequence[float], securities: Sequence[str]) -> list[float]:
    if isinstance(weights, dict):
        values = [float(weights.get(security, 0.0)) for security in securities]
    else:
        values = [float(value) for value in weights]
    if len(values) != len(securities):
        raise ValidationError("weights must cover every active security", expected=len(securities),
                              received=len(values))
    if any(not math.isfinite(value) or value < -1e-12 for value in values):
        raise ValidationError("weights must be finite and non-negative", weights=values)
    if sum(values) > 1.0 + 1e-9:
        raise ValidationError("weights cannot sum above 100%", total=sum(values))
    return values


def _equity_curve(returns: Sequence[float], dates: Sequence[str]) -> list[dict[str, Any]]:
    equity = 1.0
    curve = []
    for date, value in zip(dates, returns):
        equity *= 1.0 + value
        curve.append({"date": date, "equity": equity, "return": value})
    return curve


def _period_metrics(returns: Sequence[float], dates: Sequence[str], *, risk_free: float = 0.0) -> dict[str, Any]:
    if len(returns) < 2:
        return {"observations": len(returns), "total_return": None,
                "annualized_return": None, "volatility": None,
                "sharpe": None, "max_drawdown": None,
                "var_95_daily": None, "expected_shortfall_95_daily": None,
                "warning": "fewer than two observations"}
    total = math.prod(1.0 + value for value in returns) - 1.0
    vol = annualized_volatility(returns)
    excess = [value - risk_free / 252.0 for value in returns]
    mean_excess = sum(excess) / len(excess)
    downside = [min(value, 0.0) for value in returns]
    downside_dev = math.sqrt(sum(value * value for value in downside) / len(downside))
    return {
        "observations": len(returns),
        "start_date": dates[0],
        "end_date": dates[-1],
        "total_return": total,
        "annualized_return": annualized_return(returns),
        "annualized_volatility": vol,
        "sharpe": (mean_excess / vol * math.sqrt(252)) if vol > 0 else None,
        "sortino": (mean_excess / downside_dev * math.sqrt(252)) if downside_dev > 0 else None,
        "max_drawdown": max_drawdown([point["equity"] for point in _equity_curve(returns, dates)]),
        "var_95_daily": historical_var(returns, 0.95),
        "expected_shortfall_95_daily": expected_shortfall(returns, 0.95),
        "var_99_daily": historical_var(returns, 0.99),
        "expected_shortfall_99_daily": expected_shortfall(returns, 0.99),
        "risk_free_rate": risk_free,
        "return_frequency": "daily simple returns",
        "var_method": "historical quantile; loss reported as a positive number",
    }


def portfolio_analysis(
    panel: dict[str, Any] | None = None,
    *,
    weights: dict[str, float] | Sequence[float],
    lookback: int = 252,
    capital: float = 100_000.0,
    risk_free: float = 0.0,
    benchmark_weights: dict[str, float] | None = None,
    current_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Risk report for an aligned, long-only multi-asset portfolio."""
    matrix = returns_matrix(panel)
    securities = list(matrix["securities"])
    values = _weights(weights, securities)
    if lookback < 20 or lookback > len(matrix["returns"]):
        raise ValidationError("lookback must be between 20 and the available history",
                              lookback=lookback, available=len(matrix["returns"]))
    returns = matrix["returns"][-lookback:]
    dates = matrix["dates"][-lookback:]
    portfolio = portfolio_returns(returns, values)
    covariance_daily = covariance_matrix(returns)
    covariance_annual = [[value * 252.0 for value in row] for row in covariance_daily]
    variance = sum(values[i] * sum(covariance_annual[i][j] * values[j]
                                  for j in range(len(values)))
                   for i in range(len(values)))
    volatility = math.sqrt(max(0.0, variance))
    marginal = [sum(covariance_annual[i][j] * values[j] for j in range(len(values)))
                for i in range(len(values))]
    component = [values[i] * marginal[i] for i in range(len(values))]
    contributions_vol = [item / volatility if volatility else 0.0 for item in component]
    contributions_pct = [item / variance if variance else 0.0 for item in component]
    benchmark = [1.0 / len(securities)] * len(securities) if benchmark_weights is None else _weights(
        benchmark_weights, securities
    )
    benchmark_returns = portfolio_returns(returns, benchmark)
    benchmark_curve = _equity_curve(benchmark_returns, dates)
    portfolio_curve = _equity_curve(portfolio, dates)
    metrics = _period_metrics(portfolio, dates, risk_free=risk_free)
    benchmark_metrics = _period_metrics(benchmark_returns, dates, risk_free=risk_free)
    metrics["benchmark"] = {
        "weights": dict(zip(securities, benchmark)),
        "total_return": benchmark_metrics["total_return"],
        "annualized_return": benchmark_metrics["annualized_return"],
        "max_drawdown": benchmark_metrics["max_drawdown"],
        "volatility": benchmark_metrics["annualized_volatility"],
    }
    metrics["excess_return"] = (
        metrics["total_return"] - benchmark_metrics["total_return"]
        if metrics["total_return"] is not None and benchmark_metrics["total_return"] is not None
        else None
    )
    beta_value = beta(portfolio, benchmark_returns)
    cash_weight = max(0.0, 1.0 - sum(values))
    sectors: dict[str, float] = {}
    for security_id, value in zip(securities, values):
        meta = next((item for item in matrix["instruments"]
                     if item["security_id"] == security_id), None)
        sector = (meta or {}).get("sector") or "unclassified"
        sectors[sector] = sectors.get(sector, 0.0) + value
    stress = []
    for label, shock in (
        ("equity_market_shock", -0.20),
        ("severe_combined_shock", -0.35),
    ):
        # A declared linear beta scenario, not a nonlinear revaluation or a forecast.
        pnl_pct = sum(value * shock * (beta_value if beta_value is not None else 1.0)
                      for value in values)
        stress.append({
            "scenario": label,
            "assumption": f"all risk assets move {shock:.0%} times portfolio beta; cash unchanged",
            "portfolio_return": pnl_pct,
            "pnl": pnl_pct * capital,
            "method": "linear beta approximation",
            "nonlinear": False,
        })
    stress.extend([
        {
            "scenario": "parallel_rates_100bp",
            "portfolio_return": None,
            "pnl": None,
            "assumption": "requires a fixed-income sleeve with curve sensitivity",
            "method": "unsupported for this all-equity fixture",
            "nonlinear": False,
        },
        {
            "scenario": "volatility_shock",
            "portfolio_return": None,
            "pnl": None,
            "assumption": "requires an option or volatility-sensitive sleeve",
            "method": "unsupported for this cash-equity fixture",
            "nonlinear": False,
        },
    ])
    return {
        "schema": RISK_SCHEMA,
        "data_class": matrix["data_class"],
        "universe_id": matrix["universe_id"],
        "provenance": matrix["provenance"],
        "securities": securities,
        "weights": dict(zip(securities, values)),
        "cash_weight": cash_weight,
        "lookback": {"sessions": len(returns), "start": dates[0], "end": dates[-1],
                     "return_frequency": "daily"},
        "metrics": metrics,
        "covariance_annualized": covariance_annual,
        "correlation_annualized": _correlations(covariance_annual),
        "risk": {
            "annualized_volatility": volatility,
            "variance": variance,
            "beta": beta_value,
            "component_variance": dict(zip(securities, component)),
            "component_volatility": dict(zip(securities, contributions_vol)),
            "contribution_pct": dict(zip(securities, contributions_pct)),
            "contribution_check": {
                "sum_volatility_contributions": sum(contributions_vol),
                "sum_percent": sum(contributions_pct),
                "matches_portfolio_volatility": abs(sum(contributions_vol) - volatility) < 1e-10,
            },
            "historical_var_95_daily": metrics["var_95_daily"],
            "historical_es_95_daily": metrics["expected_shortfall_95_daily"],
            "max_drawdown": metrics["max_drawdown"],
            "gross_exposure": sum(abs(value) for value in values),
            "net_exposure": sum(values),
            "cash_exposure": cash_weight,
            "sector_exposure": sectors,
            "rate_sensitivity": None,
            "rate_sensitivity_reason": "all-equity fixture; no fixed-income sleeve is valued in this report",
        },
        "stress_tests": stress,
        "equity_curve": portfolio_curve,
        "benchmark_curve": benchmark_curve,
        "warnings": [
            "The fixture is synthetic and must not be interpreted as a market forecast.",
            "Historical VaR/ES are sample quantiles, not a guarantee of tail coverage.",
            "Stress scenarios are linear approximations; they are not full nonlinear revaluations.",
            "Beta uses the equal-weight active fixture as its benchmark.",
        ],
        "limitations": [
            "Only continuously listed active securities enter the return matrix; the delisted path is documented in the universe.",
            "No shorting, borrowing, FX, taxes or derivatives are included in this report.",
            "Turnover and transaction costs are not deducted from the historical risk report.",
        ],
    }


def _correlations(covariance: list[list[float]]) -> list[list[float]]:
    n = len(covariance)
    result = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            left = math.sqrt(max(covariance[i][i], 0.0))
            right = math.sqrt(max(covariance[j][j], 0.0))
            result[i][j] = covariance[i][j] / (left * right) if left and right else 0.0
    return result


def _solve_active_set(
    covariance: list[list[float]], expected_returns: list[float], states: tuple[int, ...],
    *, invested: float, max_weight: float, target_return: float | None,
    tolerance: float = 1e-10,
) -> dict[str, Any] | None:
    n = len(covariance)
    fixed = {i: (0.0 if state == 0 else max_weight) for i, state in enumerate(states) if state != 2}
    free = [i for i, state in enumerate(states) if state == 2]
    fixed_vector = [fixed[i] for i in range(n) if i in fixed]
    A = [[1.0 for _ in free]]
    b = [invested - sum(fixed.values())]
    if target_return is not None:
        A.append([expected_returns[i] for i in free])
        b.append(target_return - sum(expected_returns[i] * value for i, value in fixed.items()))
    if not free:
        if len(b) > 1:
            target = sum(expected_returns[i] * fixed[i] for i in fixed)
            if abs(target - target_return) > tolerance:
                return None
        if abs(sum(fixed.values()) - invested) > tolerance:
            return None
        weights = [fixed[i] for i in range(n)]
        return {"weights": weights, "lambda": [], "objective": _quadratic(covariance, weights)}
    # KKT for min 0.5 w' C w subject to A w = b.
    size = len(free) + len(b)
    matrix = [[0.0] * size for _ in range(size)]
    rhs = [0.0] * size
    for row, i in enumerate(free):
        for column, j in enumerate(free):
            matrix[row][column] = covariance[i][j]
        for constraint in range(len(b)):
            matrix[row][len(free) + constraint] = A[constraint][row]
        rhs[row] = -sum(covariance[i][j] * fixed[j] for j in fixed)
    for constraint in range(len(b)):
        for column, j in enumerate(free):
            matrix[len(free) + constraint][column] = A[constraint][column]
        rhs[len(free) + constraint] = b[constraint]
    try:
        solution = solve_linear(matrix, rhs)
    except ValidationError:
        return None
    weights = [fixed[i] if i in fixed else solution[free.index(i)] for i in range(n)]
    if any(value < -tolerance or value > max_weight + tolerance for value in weights):
        return None
    return {"weights": weights, "lambda": solution[len(free):],
            "objective": _quadratic(covariance, weights)}


def _quadratic(covariance: list[list[float]], weights: list[float]) -> float:
    return sum(weights[i] * covariance[i][j] * weights[j]
               for i in range(len(weights)) for j in range(len(weights)))


def optimize(
    panel: dict[str, Any] | None = None,
    *,
    weights: dict[str, float] | None = None,
    max_weight: float = 0.6,
    cash_weight: float = 0.0,
    target_return: float | None = None,
    shrinkage: float = 0.0,
    current_weights: dict[str, float] | None = None,
    turnover_cap: float | None = None,
    sector_caps: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Minimum-variance or target-return long-only optimization with box constraints."""
    matrix = returns_matrix(panel)
    securities = list(matrix["securities"])
    n = len(securities)
    if n > 8:
        raise ValidationError("active-set optimizer supports at most 8 securities", count=n)
    if not 0 < max_weight <= 1:
        raise ValidationError("max_weight must be in (0, 1]", max_weight=max_weight)
    if not 0 <= cash_weight < 1:
        raise ValidationError("cash_weight must be in [0, 1)", cash_weight=cash_weight)
    invested = 1.0 - cash_weight
    if max_weight * n < invested - 1e-12:
        return _infeasible("maximum position constraint cannot fund the invested weight",
                           securities=securities, max_weight=max_weight, invested=invested)
    if turnover_cap is not None:
        raise ValidationError("turnover constraints are not implemented in this release",
                              parameter="turnover_cap")
    if sector_caps:
        raise ValidationError("sector cap constraints are not implemented in this release",
                              parameter="sector_caps")
    covariance = [[value * 252.0 for value in row] for row in covariance_matrix(
        matrix["returns"], shrinkage=shrinkage
    )]
    expected = [sum(row[i] for row in matrix["returns"]) / len(matrix["returns"]) * 252.0
                for i in range(n)]
    if target_return is not None and not math.isfinite(target_return):
        raise ValidationError("target_return must be finite", target_return=target_return)
    if shrinkage:
        covariance = covariance_matrix(matrix["returns"], shrinkage=shrinkage)
        covariance = [[value * 252.0 for value in row] for row in covariance]
    best = None
    feasible_count = 0
    for states in itertools.product((0, 1, 2), repeat=n):
        candidate = _solve_active_set(
            covariance, expected, states, invested=invested, max_weight=max_weight,
            target_return=target_return,
        )
        if candidate is None:
            continue
        feasible_count += 1
        if best is None or candidate["objective"] < best["objective"] - 1e-14:
            best = {**candidate, "states": states}
    if best is None:
        return _infeasible("no long-only solution satisfies the declared constraints",
                           securities=securities, max_weight=max_weight,
                           invested=invested, target_return=target_return)
    optimized = dict(zip(securities, best["weights"]))
    original = dict(zip(securities, _weights(weights or {s: invested / n for s in securities}, securities)))
    turnover = None
    if current_weights is not None:
        current = _weights(current_weights, securities)
        turnover = sum(abs(a - b) for a, b in zip(best["weights"], current)) / 2.0
    report = portfolio_analysis(
        panel, weights=optimized, lookback=len(matrix["returns"]), capital=100_000,
        benchmark_weights=original,
    )
    original_report = portfolio_analysis(
        panel, weights=original, lookback=len(matrix["returns"]), capital=100_000,
        benchmark_weights=original,
    )
    return {
        "schema": OPTIMIZER_SCHEMA,
        "data_class": matrix["data_class"],
        "universe_id": matrix["universe_id"],
        "securities": securities,
        "objective": "minimum variance" if target_return is None else "minimum variance subject to target return",
        "inputs": {
            "max_weight": max_weight, "cash_weight": cash_weight,
            "target_return": target_return, "shrinkage": shrinkage,
            "expected_returns": dict(zip(securities, expected)),
            "expected_return_basis": "historical sample mean annualized; not a forecast",
            "current_weights": current_weights,
        },
        "solution": {
            "weights": optimized,
            "cash_weight": cash_weight,
            "invested_weight": sum(best["weights"]),
            "expected_return": sum(expected[i] * best["weights"][i] for i in range(n)),
            "variance": best["objective"],
            "volatility": math.sqrt(max(best["objective"], 0.0)),
            "feasible": True,
            "constraints": {
                "sum_weights": sum(best["weights"]),
                "max_weight": max(best["weights"]),
                "long_only": all(value >= -1e-10 for value in best["weights"]),
                "target_return_satisfied": (
                    target_return is None
                    or sum(expected[i] * best["weights"][i] for i in range(n)) >= target_return - 1e-8
                ),
            },
            "turnover": turnover,
            "solver": "deterministic active-set KKT enumeration",
            "feasible_active_sets": feasible_count,
        },
        "original": {
            "weights": original,
            "risk": original_report,
        },
        "optimized": {
            "weights": optimized,
            "risk": report,
        },
        "diagnostics": {
            "covariance": covariance,
            "note": ("Expected returns are historical sample means and are not an alpha forecast. "
                     "The solution is a constrained estimate, not an investment recommendation."),
        },
        "limitations": [
            "No turnover, sector, transaction-cost, tax or borrow constraints in this release.",
            "Covariance is estimated from the synthetic fixture; it is not a forecast of future risk.",
            "The active-set solver enumerates at most eight assets; larger universes require a dedicated QP backend.",
        ],
    }


def _infeasible(reason: str, **context: Any) -> dict[str, Any]:
    return {
        "schema": OPTIMIZER_SCHEMA,
        "solution": {"feasible": False, "reason": reason, "weights": None},
        "diagnostics": context,
        "limitations": ["Infeasible optimization is reported rather than returning an invalid portfolio."],
    }


__all__ = ["OPTIMIZER_SCHEMA", "RISK_SCHEMA", "optimize", "portfolio_analysis"]
