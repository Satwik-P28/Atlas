"""Lightweight vectorized-style research preview.

This is deliberately *not* a second execution engine. It calculates a signal series,
target weights, close-to-close hypothetical returns, turnover and an estimated cost
drag without generating orders or fills. Its result is labelled ``vectorized_preview``
and must never be presented as an executable backtest.

The environment has no NumPy/Pandas dependency. The preview therefore uses ordinary
Python arrays and a single chronological pass. It is useful for fast hypothesis triage,
not for a claim of high-performance vectorised execution; the event-driven simulator is
the authoritative research path for fills, cash and corporate actions.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, utcnow
from ..market.bars import BarStore
from ..storage.db import Database
from .contracts import canonical_json, validate_strategy
from .features import FeatureEngine
from .simulator import _Signal, compute_metrics


@dataclass(slots=True)
class VectorizedConfig:
    as_of: str | None = None
    start: str | None = None
    end: str | None = None
    initial_capital: float | None = None
    commission_bps: float | None = None
    slippage_bps: float | None = None


def run_preview(db: Database, strategy_spec: dict[str, Any], config: VectorizedConfig | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    spec = validate_strategy(strategy_spec)
    cfg = config or VectorizedConfig()
    cutoff = iso_date(cfg.as_of or utcnow())
    start = iso_date(cfg.start) if cfg.start else None
    end = iso_date(cfg.end) if cfg.end else None
    if end and end > cutoff:
        raise ValidationError("preview end is after the information cutoff", end=end, as_of=cutoff)
    instrument = spec["universe"]["instruments"][0]
    security_id, mic = instrument["security_id"], instrument["mic"]
    all_bars = BarStore(db).query(security_id, mic, "1900-01-01", cutoff)
    by_day = {bar.session_date: bar for bar in all_bars}
    ordered = [by_day[key] for key in sorted(by_day)]
    if start:
        ordered = [bar for bar in ordered if bar.session_date >= start]
    if end:
        ordered = [bar for bar in ordered if bar.session_date <= end]
    if len(ordered) < 3:
        raise ValidationError("vectorized preview requires at least three sessions", sessions=len(ordered))
    feature_result = FeatureEngine(db).compute(
        security_id, mic, spec["features"], start=start, end=end or ordered[-1].session_date,
        as_of=cutoff, persist=False,
    )
    feature_map = {point["date"]: point for point in feature_result.points}
    signal = _Signal(spec, ordered, feature_map, db)
    commission = cfg.commission_bps if cfg.commission_bps is not None else spec["execution"]["commission_bps"]
    slippage = cfg.slippage_bps if cfg.slippage_bps is not None else spec["execution"]["slippage_bps"]
    cost_rate = (float(commission) + float(slippage)) / 10_000
    initial = float(cfg.initial_capital or spec["initial_capital"])
    equity = initial
    benchmark_equity = initial
    previous_weight = 0.0
    turnover = 0.0
    costs = 0.0
    curve: list[dict[str, Any]] = [{"date": ordered[0].session_date, "equity": equity}]
    benchmark_curve: list[dict[str, Any]] = [{"date": ordered[0].session_date, "equity": benchmark_equity}]
    weights: list[dict[str, Any]] = []
    for index in range(len(ordered) - 1):
        target = signal.close_signal(index)
        if target is None:
            target = previous_weight
        weight = float(target)
        change = abs(weight - previous_weight)
        turnover += change
        cost = change * cost_rate
        costs += cost * equity
        close_return = float(ordered[index + 1].close / ordered[index].close - 1)
        equity *= 1 + weight * close_return - cost
        benchmark_equity *= 1 + close_return
        curve.append({"date": ordered[index + 1].session_date, "equity": equity})
        benchmark_curve.append({"date": ordered[index + 1].session_date, "equity": benchmark_equity})
        weights.append({"date": ordered[index].session_date, "weight": weight, "next_return": close_return})
        previous_weight = weight
    metrics = compute_metrics(curve, benchmark_curve=benchmark_curve, risk_free_rate=spec["risk_free_rate"])
    metrics["turnover"] = turnover
    metrics["transaction_costs"] = costs
    benchmark_metrics = compute_metrics(benchmark_curve, risk_free_rate=spec["risk_free_rate"])
    metrics["benchmark"] = {
        "total_return": benchmark_metrics.get("total_return"),
        "annualized_return": benchmark_metrics.get("annualized_return"),
        "max_drawdown": benchmark_metrics.get("max_drawdown"),
        "sharpe": benchmark_metrics.get("sharpe"),
    }
    metrics["excess_return"] = (
        metrics["total_return"] - benchmark_metrics["total_return"]
        if metrics.get("total_return") is not None and benchmark_metrics.get("total_return") is not None
        else None
    )
    fingerprint = hashlib.sha256(canonical_json({
        "spec": spec, "cutoff": cutoff, "start": start, "end": end,
        "commission_bps": commission, "slippage_bps": slippage,
        "bars": [bar.session_date for bar in ordered],
    }).encode("utf-8")).hexdigest()
    return {
        "schema": "atlas.quant.vectorized.v1",
        "engine": "python_array_preview.v1",
        "mode": "vectorized_preview",
        "not_a_fill_simulation": True,
        "strategy": spec,
        "security": {"security_id": security_id, "mic": mic},
        "period": {"start": ordered[0].session_date, "end": ordered[-1].session_date,
                   "sessions": len(ordered)},
        "equity_curve": curve,
        "benchmark_curve": benchmark_curve,
        "weights": weights[-250:],
        "metrics": metrics,
        "assumptions": [
            "Weights are applied to close-to-close returns after a signal at the prior close.",
            "No orders, fills, cash ledger, dividends or split adjustments are simulated.",
            "Costs are an estimated turnover drag, not a commission ledger.",
            "This preview is for triage; use the event-driven simulator for authoritative results.",
        ],
        "result_fingerprint": fingerprint,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


__all__ = ["VectorizedConfig", "run_preview"]
