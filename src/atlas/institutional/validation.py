"""Walk-forward and out-of-sample evaluation for the synthetic multi-asset fixture.

The test interval is never used to choose a parameter or a strategy family. Every
candidate receives a row in the persisted attempt log. The engine reports a trial count,
an unadjusted block-bootstrap diagnostic and a Bonferroni-adjusted warning, but it does
not turn those diagnostics into a claim of alpha.

This is a portfolio-weight research engine, not a replacement for the Phase 4 event-driven
single-instrument ledger. It rebalances weights at a close and applies the next day's
cross-sectional return, with a turnover cost. Its semantics are stated in every result.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from statistics import mean, stdev
from typing import Any

from ..core.errors import ValidationError
from ..fec import compile_model
from ..fec.runtime import ExecutionEngine
from ..finance.statistics import annualized_return, annualized_volatility, max_drawdown
from .universe import aligned_panel, returns_matrix

VALIDATION_SCHEMA = "atlas.institutional.walk_forward.v1"
FAMILIES = ("momentum", "inverse_vol", "model")
DEFAULT_LOOKBACKS = (20, 60, 120)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        __import__("json").dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _price_indices(returns: list[list[float]]) -> list[list[float]]:
    if not returns:
        return []
    n = len(returns[0])
    values = [100.0] * n
    indices = [list(values)]
    for row in returns:
        values = [values[i] * (1.0 + row[i]) for i in range(n)]
        indices.append(list(values))
    return indices


def _summary(returns: list[float], dates: list[str], *, risk_free: float = 0.0) -> dict[str, Any]:
    if len(returns) < 2:
        return {"observations": len(returns), "total_return": None, "sharpe": None}
    equity = []
    level = 1.0
    for value in returns:
        level *= 1.0 + value
        equity.append(level)
    vol = annualized_volatility(returns)
    excess = [value - risk_free / 252.0 for value in returns]
    sharpe = mean(excess) / vol * math.sqrt(252) if vol > 0 else None
    return {
        "observations": len(returns),
        "start_date": dates[0],
        "end_date": dates[-1],
        "total_return": math.prod(1.0 + value for value in returns) - 1.0,
        "annualized_return": annualized_return(returns),
        "annualized_volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(equity),
        "transaction_costs_deducted": True,
    }


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _target_weights(
    family: str, lookback: int, returns: list[list[float]], end: int,
    prices: list[list[float]], model: Any | None,
) -> list[float]:
    n = len(returns[0])
    history = returns[max(0, end - lookback + 1): end + 1]
    if not history:
        return [1.0 / n] * n
    if family == "equal_weight":
        return [1.0 / n] * n
    if family == "inverse_vol":
        vols = []
        for i in range(n):
            values = [row[i] for row in history]
            volatility = stdev(values) if len(values) > 1 else 0.0
            vols.append(volatility if volatility > 0 else 1e-12)
        inverse = [1.0 / value for value in vols]
        total = sum(inverse)
        return [value / total for value in inverse]
    if family == "model":
        scores = []
        for i in range(n):
            series = [row[i] for row in prices[: end + 1]]
            if len(series) < lookback + 1 or model is None:
                scores.append(-1e99)
                continue
            close = series[-1]
            sma = sum(series[-lookback:]) / lookback
            try:
                result = ExecutionEngine(use_cache=False).execute(
                    model, {"close": close, "sma": sma}, persist=False
                )
                scores.append(float(result["outputs"]["signal"]))
            except Exception:  # noqa: BLE001 - a failed model is excluded, not imputed
                scores.append(-1e99)
        winner = max(range(n), key=lambda i: scores[i])
        return [1.0 if i == winner else 0.0 for i in range(n)]
    # Momentum: total return over the lookback, equal-weight the winner.
    scores = []
    for i in range(n):
        values = [row[i] for row in history]
        scores.append(math.prod(1.0 + value for value in values) - 1.0)
    winner = max(range(n), key=lambda i: scores[i])
    return [1.0 if i == winner else 0.0 for i in range(n)]


def _run_strategy(
    securities: list[str], returns: list[list[float]], dates: list[str],
    *, family: str, lookback: int, rebalance: int, start: int, end: int,
    commission_bps: float = 2.0,
) -> dict[str, Any]:
    n = len(securities)
    if end <= start + 1:
        return {"family": family, "lookback": lookback, "returns": [], "dates": [],
                "weights": [], "turnover": 0.0}
    model = None
    if family == "model":
        model_spec = {
            "schema_version": "atlas.model.v1", "name": "Walk-forward price/SMA signal",
            "version": "1.0.0", "interface": "equation",
            "inputs": {"close": "Price[USD]", "sma": "Price[USD]"},
            "equations": [{"name": "signal", "expr": "close / sma - 1"}],
            "outputs": ["signal"],
        }
        model = compile_model(model_spec)
    prices = _price_indices(returns)
    weights = [1.0 / n] * n
    pending: list[float] | None = None
    pending_cost = 0.0
    values: list[float] = []
    dates_out: list[str] = []
    weight_log: list[dict[str, Any]] = []
    turnover = 0.0
    for index in range(start, end):
        if pending is not None:
            weights = pending
            pending = None
        realized = _dot(weights, returns[index])
        if pending_cost:
            realized -= pending_cost
            pending_cost = 0.0
        values.append(realized)
        dates_out.append(dates[index])
        weight_log.append({"date": dates[index], "weights": dict(zip(securities, weights))})
        if index + 1 < end and (index - start + 1) % rebalance == 0:
            target = _target_weights(family, lookback, returns, index, prices, model)
            turnover = sum(abs(a - b) for a, b in zip(target, weights)) / 2.0
            pending_cost = turnover * commission_bps / 10_000.0
            pending = target
    return {
        "family": family, "lookback": lookback, "returns": values, "dates": dates_out,
        "weights": weight_log, "turnover": turnover,
        "metrics": _summary(values, dates_out),
    }


def _fold_indices(length: int, *, folds: int, train: int, validation: int, test: int,
                  embargo: int, step: int, mode: str) -> list[dict[str, int]]:
    result = []
    for fold in range(folds):
        train_end = train + fold * step
        val_start = train_end + embargo
        val_end = val_start + validation
        test_start = val_end + embargo
        test_end = test_start + test
        if test_end > length:
            break
        train_start = max(0, train_end - train) if mode == "rolling" else 0
        result.append({
            "train_start": train_start, "train_end": train_end,
            "validation_start": val_start, "validation_end": val_end,
            "test_start": test_start, "test_end": test_end,
        })
    return result


def _block_bootstrap_p(returns: list[float], *, trials: int, seed: int = 20261104,
                       resamples: int = 600, block: int = 10) -> dict[str, Any]:
    if len(returns) < 10:
        return {"raw_p_value": None, "adjusted_p_value": None,
                "method": "insufficient observations"}
    observed = mean(returns)
    rng = random.Random(seed)
    count = 0
    for _ in range(resamples):
        sample: list[float] = []
        while len(sample) < len(returns):
            start = rng.randrange(len(returns))
            sample.extend(returns[start:start + block])
        if mean(sample[: len(returns)]) <= 0:
            count += 1
    raw = (count + 1) / (resamples + 1)
    return {
        "raw_p_value": raw,
        "adjusted_p_value": min(1.0, raw * max(1, trials)),
        "trials": trials,
        "method": "deterministic 10-day block bootstrap of test excess mean; one-sided",
        "warning": ("A block bootstrap is a diagnostic, not a guarantee of independence; "
                    "the adjusted value is a conservative multiple-testing warning."),
        "observed_mean_excess": observed,
    }


def walk_forward(
    *,
    folds: int = 4,
    train: int = 252,
    validation: int = 63,
    test: int = 63,
    embargo: int = 5,
    step: int = 63,
    mode: str = "rolling",
    lookbacks: tuple[int, ...] = DEFAULT_LOOKBACKS,
    rebalance: int = 21,
    commission_bps: float = 2.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    if mode not in {"rolling", "expanding"}:
        raise ValidationError("mode must be rolling or expanding", mode=mode)
    if min(train, validation, test) < 20:
        raise ValidationError("each partition must contain at least 20 sessions")
    if embargo < 1:
        raise ValidationError("embargo must be at least one session")
    data = aligned_panel()
    matrix = returns_matrix(data)
    dates = matrix["dates"]
    returns = matrix["returns"]
    securities = matrix["securities"]
    if len(returns) < train + validation + test + 2 * embargo:
        raise ValidationError("not enough synthetic history for the requested partitions",
                              available=len(returns))
    indices = _fold_indices(
        len(returns), folds=folds, train=train, validation=validation, test=test,
        embargo=embargo, step=step, mode=mode,
    )
    if not indices:
        raise ValidationError("no walk-forward fold fits in the available history")
    attempts: list[dict[str, Any]] = []
    fold_results: list[dict[str, Any]] = []
    test_returns_all: list[float] = []
    test_dates_all: list[str] = []
    test_benchmark_all: list[float] = []
    for fold_number, bounds in enumerate(indices, start=1):
        configs = [
            (family, lookback)
            for family in FAMILIES for lookback in lookbacks
        ]
        train_runs = {}
        for family, lookback in configs:
            run = _run_strategy(
                securities, returns, dates, family=family, lookback=lookback,
                rebalance=rebalance, start=bounds["train_start"], end=bounds["train_end"],
                commission_bps=commission_bps,
            )
            train_runs[(family, lookback)] = run
            attempts.append({
                "fold": fold_number, "stage": "train", "family": family,
                "lookback": lookback, "metrics": run["metrics"], "selected": False,
                "reason": "candidate evaluated on the training interval",
            })
        # One parameter winner per family, selected only on training data.
        family_winners = {}
        for family in FAMILIES:
            candidates = [(config, run) for config, run in train_runs.items() if config[0] == family]
            candidates.sort(key=lambda item: (
                item[1]["metrics"].get("sharpe") if item[1]["metrics"].get("sharpe") is not None else -1e9,
                item[1]["metrics"].get("total_return") or -1e9,
            ), reverse=True)
            family_winners[family] = candidates[0]
        validation_scores = []
        for family, (config, _run) in family_winners.items():
            val_run = _run_strategy(
                securities, returns, dates, family=family, lookback=config[1],
                rebalance=rebalance, start=bounds["validation_start"],
                end=bounds["validation_end"], commission_bps=commission_bps,
            )
            attempts.append({
                "fold": fold_number, "stage": "validation", "family": family,
                "lookback": config[1], "metrics": val_run["metrics"], "selected": False,
                "reason": "family winner selected on training, evaluated on validation",
            })
            validation_scores.append((family, config[1], val_run))
        validation_scores.sort(key=lambda item: (
            item[2]["metrics"].get("sharpe") if item[2]["metrics"].get("sharpe") is not None else -1e9,
            item[2]["metrics"].get("total_return") or -1e9,
        ), reverse=True)
        selected_family, selected_lookback, _ = validation_scores[0]
        test_run = _run_strategy(
            securities, returns, dates, family=selected_family, lookback=selected_lookback,
            rebalance=rebalance, start=bounds["test_start"], end=bounds["test_end"],
            commission_bps=commission_bps,
        )
        # Only after the test run is recorded do we mark the selected configuration.
        for attempt in attempts:
            if (attempt["fold"] == fold_number and attempt["family"] == selected_family
                    and attempt["lookback"] == selected_lookback):
                attempt["selected"] = True
        test_benchmark = _run_strategy(
            securities, returns, dates, family="equal_weight", lookback=1,
            rebalance=1, start=bounds["test_start"], end=bounds["test_end"],
            commission_bps=0.0,
        )
        test_returns_all.extend(test_run["returns"])
        test_dates_all.extend(test_run["dates"])
        test_benchmark_all.extend(test_benchmark["returns"])
        cost_sensitivity = []
        for cost in (0.0, 2.0, 10.0, 25.0):
            scenario = _run_strategy(
                securities, returns, dates, family=selected_family,
                lookback=selected_lookback, rebalance=rebalance,
                start=bounds["test_start"], end=bounds["test_end"],
                commission_bps=cost,
            )
            cost_sensitivity.append({
                "commission_bps": cost,
                "total_return": scenario["metrics"].get("total_return"),
                "sharpe": scenario["metrics"].get("sharpe"),
            })
        fold_results.append({
            "fold": fold_number,
            "partitions": {
                "train": [dates[bounds["train_start"]], dates[bounds["train_end"] - 1]],
                "validation": [dates[bounds["validation_start"]], dates[bounds["validation_end"] - 1]],
                "test": [dates[bounds["test_start"]], dates[bounds["test_end"] - 1]],
            },
            "embargo_sessions": embargo,
            "family_winners": {
                family: {"lookback": config[1], "train_metrics": run["metrics"]}
                for family, (config, run) in family_winners.items()
            },
            "validation_ranking": [
                {"family": family, "lookback": lookback, "metrics": run["metrics"]}
                for family, lookback, run in validation_scores
            ],
            "selected_before_test": {"family": selected_family, "lookback": selected_lookback},
            "test_metrics": test_run["metrics"],
            "test_turnover": test_run["turnover"],
            "test_cost_sensitivity": cost_sensitivity,
            "test_return_series": test_run["returns"],
            "test_dates": test_run["dates"],
        })
    valid_dates = [date for date in test_dates_all]
    aggregate = _summary(test_returns_all, valid_dates)
    bench = _summary(test_benchmark_all, valid_dates)
    excess = [a - b for a, b in zip(test_returns_all, test_benchmark_all)]
    trials = len(attempts)
    p_value = _block_bootstrap_p(excess, trials=trials)
    aggregate["benchmark_total_return"] = bench["total_return"]
    aggregate["excess_return"] = (
        aggregate["total_return"] - bench["total_return"]
        if aggregate["total_return"] is not None and bench["total_return"] is not None else None
    )
    aggregate["benchmark_sharpe"] = bench["sharpe"]
    aggregate["test_excess_series"] = excess
    selections = [fold["selected_before_test"] for fold in fold_results]
    lookbacks = [item["lookback"] for item in selections]
    families = [item["family"] for item in selections]
    return {
        "schema": VALIDATION_SCHEMA,
        "method": "walk_forward",
        "window_mode": mode,
        "data_class": matrix["data_class"],
        "universe_id": matrix["universe_id"],
        "provenance": matrix["provenance"],
        "securities": securities,
        "data_snapshot": {
            "content_hash": matrix.get("content_hash"),
            "data_class": matrix["data_class"],
            "observations": len(returns),
        },
        "partitions": {
            "train_sessions": train, "validation_sessions": validation,
            "test_sessions": test, "embargo_sessions": embargo, "step_sessions": step,
            "folds_requested": folds, "folds_completed": len(fold_results),
        },
        "selection_policy": {
            "fit": "one parameter winner per family selected on the training interval",
            "family_selection": "highest validation Sharpe; ties by validation return",
            "test": "evaluated once after the selected family and parameters are frozen",
            "test_used_for_selection": False,
        },
        "costs": {"commission_bps": commission_bps,
                  "turnover_cost": "turnover * commission_bps at the next session",
                  "slippage_bps": 0.0},
        "folds": fold_results,
        "attempts": attempts,
        "parameter_stability": {
            "selections_by_fold": selections,
            "unique_lookbacks": sorted(set(lookbacks)),
            "unique_families": sorted(set(families)),
            "same_lookback_every_fold": len(set(lookbacks)) == 1,
            "same_family_every_fold": len(set(families)) == 1,
            "interpretation": "Stable selection across folds is descriptive, not proof of robustness.",
        },
        "aggregate": aggregate,
        "multiple_testing": p_value,
        "credibility": {
            "confirmatory": True,
            "out_of_sample": True,
            "walk_forward": True,
            "test_interval_untouched": True,
            "warning": ("Walk-forward reduces a specific kind of selection leakage; it does not "
                        "prove a strategy will persist. The synthetic fixture is not a market."),
        },
        "limitations": [
            "The fixture is synthetic; no result is evidence about a real security or market.",
            "Weights are rebalanced at a close and applied to the next cross-sectional return; this is not the Phase 4 next-open fill ledger.",
            "No shorting, borrow, taxes, market impact, or multiple assets outside the three active synthetic names.",
            "Only three active securities enter the return matrix; the fourth fixture path is delisted and remains a coverage example.",
            "The bootstrap diagnostic does not solve all multiple-testing or data-snooping problems.",
            "The selected family is still selected on finite validation data and may be unstable.",
        ],
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "result_fingerprint": _json_hash({
            "schema": VALIDATION_SCHEMA,            "folds": fold_results, "aggregate": aggregate,
            "attempts": attempts, "data": matrix.get("content_hash"),
        }),
    }


__all__ = ["DEFAULT_LOOKBACKS", "FAMILIES", "VALIDATION_SCHEMA", "walk_forward"]
