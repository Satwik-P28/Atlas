"""Chronological event-driven simulator for the Quant Lab vertical slice.

Timing contract:

* the signal is evaluated with data through the current session close;
* the order is posted after that close and executed at the next available session open;
* a session that has no observation cannot produce a fill; the pending target carries;
* splits and cash dividends are applied on their ex-date from the raw position;
* the simulator never reads a feature point dated after the session being evaluated.

The engine is intentionally a scoped reference simulator, not a claim of exchange-grade
execution. It models next-open fills, commissions and slippage. It does not model order
book depth, market impact, borrow, shorting, partial fills or intraday queues.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean, pstdev, stdev
from typing import Any, Callable, Iterable

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, utcnow
from ..fec.compiler import compile_model
from ..fec.runtime import ExecutionEngine
from ..market.actions import ActionStore, ActionType
from ..market.bars import Bar, BarStore
from ..storage.db import Database
from .contracts import STRATEGY_SCHEMA, canonical_json, strategy_fingerprint, validate_strategy
from .features import FeatureEngine, normalise_features
from .portfolio import Portfolio, D, max_affordable_quantity, money

SIMULATOR_VERSION = "atlas.quant.simulator.v1"


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _max_drawdown(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak:
            worst = min(worst, value / peak - 1)
    return worst


def _source_kind(db: Database, source_id: str | None) -> str | None:
    if not source_id:
        return None
    row = db.query_one("SELECT kind FROM source WHERE source_id = ?", (source_id,))
    return row["kind"] if row else None


def _action_factor(action: Any) -> Decimal:
    if action.ratio_from is None or action.ratio_to is None:
        raise ValidationError("split action is missing a ratio", action_id=action.action_id)
    return D(action.ratio_to) / D(action.ratio_from)


def compute_metrics(
    equity_curve: list[dict[str, Any]],
    *,
    benchmark_curve: list[dict[str, Any]] | None = None,
    ledger: list[dict[str, Any]] | None = None,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    if len(equity_curve) < 2:
        return {"sessions": len(equity_curve), "total_return": None,
                "warning": "fewer than two marked sessions; no performance statistics"}
    values = [_number(point["equity"]) for point in equity_curve]
    dates = [point["date"] for point in equity_curve]
    returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1] > 0]
    total_return = values[-1] / values[0] - 1 if values[0] else None
    n = len(returns)
    annualized = (1 + total_return) ** (252 / n) - 1 if total_return is not None and n >= 60 and total_return > -1 else None
    volatility = stdev(returns) * math.sqrt(252) if n >= 2 else None
    rf_daily = risk_free_rate / 252
    excess = [value - rf_daily for value in returns]
    sharpe = (mean(excess) / stdev(excess) * math.sqrt(252)) if n >= 2 and stdev(excess) > 0 else None
    downside = [min(value, 0.0) for value in returns]
    downside_dev = math.sqrt(sum(value * value for value in downside) / n) if n else 0
    sortino = (mean(excess) / downside_dev * math.sqrt(252)) if n and downside_dev > 0 else None
    # Real peak/trough index tracking, not the last equity as a stand-in.
    peak = values[0]
    peak_index = 0
    worst = 0.0
    worst_start = worst_end = 0
    for index, value in enumerate(values):
        if value > peak:
            peak = value
            peak_index = index
        drawdown = value / peak - 1 if peak else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_start, worst_end = peak_index, index
    max_dd_duration = worst_end - worst_start
    turnover = 0.0
    if ledger:
        notional = sum(abs(_number(item.get("gross", 0))) for item in ledger
                       if item.get("side") in {"buy", "sell"})
        average_equity = sum(values) / len(values)
        turnover = notional / average_equity if average_equity else 0.0
    costs = sum(_number(item.get("commission", 0)) + _number(item.get("slippage", 0))
                for item in (ledger or []) if item.get("side") in {"buy", "sell"})
    benchmark = None
    if benchmark_curve and len(benchmark_curve) >= 2:
        bvalues = [_number(point["equity"]) for point in benchmark_curve]
        benchmark = {
            "total_return": bvalues[-1] / bvalues[0] - 1 if bvalues[0] else None,
            "max_drawdown": _max_drawdown(bvalues),
        }
    warnings: list[str] = []
    if n < 60:
        warnings.append(f"only {n} daily return observations; annualized statistics are suppressed")
    if annualized is None:
        warnings.append("annualized return is unavailable for this sample")
    return {
        "sessions": len(equity_curve),
        "return_observations": n,
        "start_date": dates[0],
        "end_date": dates[-1],
        "start_equity": values[0],
        "end_equity": values[-1],
        "total_return": total_return,
        "annualized_return": annualized,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": worst,
        "max_drawdown_duration_sessions": max_dd_duration,
        "turnover": turnover,
        "transaction_costs": costs,
        "risk_free_rate": risk_free_rate,
        "benchmark": benchmark,
        "excess_return": (total_return - benchmark["total_return"]
                          if benchmark and benchmark.get("total_return") is not None else None),
        "warnings": warnings,
        "return_method": "daily time-weighted portfolio return; no cash-flow weighting",
        "annualization": "252 sessions; suppressed below 60 return observations",
    }


@dataclass(slots=True)
class SimulationConfig:
    as_of: str | date | None = None
    start: str | date | None = None
    end: str | date | None = None
    initial_capital: float | None = None
    commission_bps: float | None = None
    slippage_bps: float | None = None
    mode: str = "atlas_ingested"

    def resolved(self, spec: dict[str, Any]) -> "SimulationConfig":
        cutoff = iso_date(self.as_of) if self.as_of else iso_date(
            spec.get("as_of") or utcnow()
        )
        start = iso_date(self.start) if self.start else None
        end = iso_date(self.end) if self.end else None
        if start and end and start > end:
            raise ValidationError("start is after end", start=start, end=end)
        if end and end > cutoff:
            raise ValidationError("end is after the information cutoff", end=end, as_of=cutoff)
        return SimulationConfig(
            as_of=cutoff, start=start, end=end,
            initial_capital=(float(self.initial_capital)
                             if self.initial_capital is not None else spec["initial_capital"]),
            commission_bps=(float(self.commission_bps)
                            if self.commission_bps is not None
                            else spec["execution"]["commission_bps"]),
            slippage_bps=(float(self.slippage_bps)
                          if self.slippage_bps is not None else spec["execution"]["slippage_bps"]),
            mode=self.mode,
        )


def _period_key(day: str, frequency: str) -> tuple[int, ...]:
    parsed = date.fromisoformat(day)
    if frequency == "monthly":
        return (parsed.year, parsed.month)
    if frequency == "weekly":
        iso_year, iso_week, _ = parsed.isocalendar()
        return (iso_year, iso_week)
    return (parsed.toordinal(),)


class _Signal:
    def __init__(self, spec: dict[str, Any], bars: list[Bar], features: dict[str, dict[str, Any]],
                 db: Database) -> None:
        self.spec = spec
        self.bars = bars
        self.features = features
        self.kind = spec["signal"]["kind"]
        self.model = None
        self.engine = None
        self.forecast_map: dict[str, float] = {}
        if self.kind == "model":
            self.model = compile_model(spec["signal"]["model_spec"])
            self.engine = ExecutionEngine(db=None, use_cache=False, timeout_seconds=2.0)
        if self.kind == "learning_probability":
            self.forecast_map = {
                item["date"]: float(item["probability"])
                for item in spec["signal"]["forecasts"]
            }

    def close_signal(self, index: int) -> float | None:
        signal = self.spec["signal"]
        closes = [bar.close for bar in self.bars[: index + 1]]
        if self.kind == "buy_hold":
            return 1.0
        if self.kind == "sma_cross":
            fast, slow = signal["fast"], signal["slow"]
            if len(closes) < slow:
                return None
            fast_avg = mean(closes[-fast:])
            slow_avg = mean(closes[-slow:])
            return 1.0 if fast_avg > slow_avg else 0.0
        if self.kind == "momentum":
            window = signal["fast"]
            if len(closes) <= window:
                return None
            previous = closes[-window - 1]
            if previous == 0:
                return None
            value = closes[-1] / previous - 1
            return 1.0 if value > signal["threshold"] else 0.0
        if self.kind == "learning_probability":
            probability = self.forecast_map.get(self.bars[index].session_date)
            if probability is None:
                return None
            return 1.0 if probability >= float(signal["threshold"]) else 0.0
        if self.kind == "model":
            point = self.features.get(self.bars[index].session_date)
            if point is None:
                return None
            inputs: dict[str, Any] = {}
            for model_input, feature_name in signal["input_map"].items():
                value = point["values"].get(feature_name)
                if value is None:
                    return None
                inputs[model_input] = value
            try:
                result = self.engine.execute(self.model, inputs, persist=False)  # type: ignore[union-attr]
            except ValidationError as exc:
                raise ValidationError("custom strategy model failed at session",
                                      session=self.bars[index].session_date,
                                      detail=str(exc)) from exc
            value = result["outputs"].get(signal["output"])
            if value is None:
                raise ValidationError("custom strategy model returned no signal",
                                      output=signal["output"])
            return 1.0 if float(value) > 0 else 0.0
        raise ValidationError("unsupported signal kind", kind=self.kind)


def _execute_target(
    portfolio: Portfolio,
    date: str,
    bar: Bar,
    target: Decimal,
    *,
    commission_bps: Decimal,
    slippage_bps: Decimal,
) -> None:
    current = portfolio.position.quantity
    if target > 0 and current == 0:
        reference = bar.open
        fill = reference * (Decimal(1) + slippage_bps / Decimal(10_000))
        quantity = max_affordable_quantity(portfolio.cash, fill, commission_bps)
        if quantity <= 0:
            return
        commission = quantity * fill * commission_bps / Decimal(10_000)
        portfolio.buy(date, quantity, reference_price=reference, fill_price=fill,
                      commission=commission)
    elif target == 0 and current > 0:
        reference = bar.open
        fill = reference * (Decimal(1) - slippage_bps / Decimal(10_000))
        gross = current * fill
        commission = gross * commission_bps / Decimal(10_000)
        portfolio.sell(date, current, reference_price=reference, fill_price=fill,
                       commission=commission)


def _simulate_core(
    spec: dict[str, Any],
    bars: list[Bar],
    *,
    config: SimulationConfig,
    features: dict[str, dict[str, Any]],
    actions: list[Any],
    db: Database,
    benchmark: bool = False,
) -> tuple[Portfolio, list[dict[str, Any]], list[dict[str, Any]]]:
    if not bars:
        raise ValidationError("no market observations in the requested simulation scope")
    security_id = spec["universe"]["instruments"][0]["security_id"]
    commission_bps = D(config.commission_bps)
    slippage_bps = D(config.slippage_bps)
    portfolio = Portfolio(security_id, D(config.initial_capital))
    signal = None if benchmark else _Signal(spec, bars, features, db)
    frequency = "daily" if benchmark else spec["decision_frequency"]
    pending: Decimal | None = Decimal(0)
    last_target = Decimal(0)
    decision_key: tuple[int, ...] | None = None
    warnings: list[str] = []
    curve: list[dict[str, Any]] = []
    action_by_date: dict[str, list[Any]] = {}
    for action in actions:
        if action.ex_date:
            action_by_date.setdefault(action.ex_date, []).append(action)

    for index, bar in enumerate(bars):
        day = bar.session_date
        # A split changes the share count before a same-date dividend is credited.
        # Processing them in provider insertion order would make the dividend depend on
        # action ids, which is not an economic rule.
        for action in sorted(
            action_by_date.get(day, []),
            key=lambda item: (0 if item.action_type in {
                ActionType.SPLIT.value, ActionType.REVERSE_SPLIT.value
            } else 1, item.action_id or ""),
        ):
            if action.action_type in {ActionType.SPLIT.value, ActionType.REVERSE_SPLIT.value}:
                portfolio.apply_split(day, _action_factor(action))
            elif action.action_type == ActionType.CASH_DIVIDEND.value and action.cash_amount is not None:
                portfolio.apply_dividend(day, D(action.cash_amount))
        if pending is not None:
            _execute_target(portfolio, day, bar, pending, commission_bps=commission_bps,
                            slippage_bps=slippage_bps)
            pending = None
        portfolio.mark(bar.close)
        curve.append(portfolio.snapshot(day))
        if index + 1 >= len(bars):
            break
        key = _period_key(day, frequency)
        is_decision = benchmark or decision_key is None or key != decision_key
        if is_decision:
            decision_key = key
            if benchmark:
                target = Decimal(1)
            else:
                value = signal.close_signal(index) if signal is not None else None
                if value is None:
                    continue
                target = Decimal(1) if value > 0 else Decimal(0)
            if target != last_target:
                pending = target
                last_target = target
    if len(curve) < len(bars):
        warnings.append("some sessions are missing marked equity observations")
    return portfolio, curve, warnings


def _missing_sessions(bars: list[Bar]) -> int:
    """Count weekday gaps inside the observed span, never inventing exchange holidays."""
    if len(bars) < 2:
        return 0
    by_date = {bar.session_date for bar in bars}
    first, last = date.fromisoformat(bars[0].session_date), date.fromisoformat(bars[-1].session_date)
    count = 0
    current = first
    while current <= last:
        if current.weekday() < 5 and current.isoformat() not in by_date:
            count += 1
        current = date.fromordinal(current.toordinal() + 1)
    return count


def run_simulation(
    db: Database,
    strategy_spec: dict[str, Any],
    *,
    config: SimulationConfig | None = None,
) -> dict[str, Any]:
    started = __import__("time").perf_counter()
    spec = validate_strategy(strategy_spec)
    cfg = (config or SimulationConfig()).resolved(spec)
    instrument = spec["universe"]["instruments"][0]
    security_id, mic = instrument["security_id"], instrument["mic"]
    all_bars = BarStore(db).query(security_id, mic, "1900-01-01", cfg.as_of or iso(utcnow()))
    by_day: dict[str, Bar] = {}
    for bar in all_bars:
        if bar.session_date <= (cfg.as_of or bar.session_date):
            by_day[bar.session_date] = bar
    ordered = [by_day[key] for key in sorted(by_day)]
    if not ordered:
        raise ValidationError("no bars available for the strategy instrument",
                              security_id=security_id, as_of=cfg.as_of)
    start = cfg.start or ordered[0].session_date
    bars = [bar for bar in ordered if bar.session_date >= start and
            (cfg.end is None or bar.session_date <= cfg.end)]
    if len(bars) < 2:
        raise ValidationError("at least two marked sessions are required",
                              sessions=len(bars), start=start, end=cfg.end)
    feature_result = FeatureEngine(db).compute(
        security_id, mic, spec["features"], start=start, end=cfg.end or bars[-1].session_date,
        as_of=cfg.as_of, persist=False,
    )
    feature_map = {point["date"]: point for point in feature_result.points}
    actions = ActionStore(db).list(security_id, knowledge_as_of=cfg.as_of,
                                   computable_only=True, include_superseded=False)
    portfolio, curve, warnings = _simulate_core(
        spec, bars, config=cfg, features=feature_map, actions=actions, db=db,
    )
    benchmark_portfolio, benchmark_curve, benchmark_warnings = _simulate_core(
        spec, bars, config=cfg, features={}, actions=actions, db=db, benchmark=True,
    )
    metrics = compute_metrics(curve, benchmark_curve=benchmark_curve,
                              ledger=portfolio.ledger, risk_free_rate=spec["risk_free_rate"])
    benchmark_metrics = compute_metrics(benchmark_curve, ledger=benchmark_portfolio.ledger,
                                        risk_free_rate=spec["risk_free_rate"])
    metrics["benchmark"] = {
        "total_return": benchmark_metrics.get("total_return"),
        "annualized_return": benchmark_metrics.get("annualized_return"),
        "max_drawdown": benchmark_metrics.get("max_drawdown"),
        "sharpe": benchmark_metrics.get("sharpe"),
        "transaction_costs": benchmark_metrics.get("transaction_costs"),
    }
    metrics["excess_return"] = (
        metrics["total_return"] - benchmark_metrics["total_return"]
        if metrics.get("total_return") is not None and benchmark_metrics.get("total_return") is not None
        else None
    )
    warnings.extend(benchmark_warnings)
    if _missing_sessions(bars):
        warnings.append(f"{_missing_sessions(bars)} weekday session(s) in the span have no observation; they are not filled.")
    sources: dict[str, dict[str, Any]] = {}
    for bar in bars:
        sources.setdefault(bar.source_id, {"source_id": bar.source_id,
                                           "kind": _source_kind(db, bar.source_id),
                                           "observations": 0})
        sources[bar.source_id]["observations"] += 1
    source_ids = sorted(sources)
    actions_applied = [action.to_dict() for action in actions
                       if action.ex_date and bars[0].session_date <= action.ex_date <= bars[-1].session_date]
    rights_rows = db.query(
        f"SELECT source_id, redistribution FROM source WHERE source_id IN ({','.join('?' for _ in source_ids)})",
        source_ids,
    ) if source_ids else []
    rights_by_source = {row["source_id"]: row["redistribution"] for row in rights_rows}
    year_counts: dict[str, int] = {}
    for point in curve:
        year_counts[point["date"][:4]] = year_counts.get(point["date"][:4], 0) + 1
    result_fingerprint = hashlib.sha256(canonical_json({
        "strategy": spec,
        "config": {"as_of": cfg.as_of, "start": start, "end": cfg.end,
                   "initial_capital": cfg.initial_capital,
                   "commission_bps": cfg.commission_bps, "slippage_bps": cfg.slippage_bps},
        "bars": [{"date": bar.session_date, "revision": bar.revision_seq,
                  "open": money(bar.open), "close": money(bar.close)} for bar in bars],
        "actions": actions_applied,
    }).encode("utf-8")).hexdigest()
    credibility = {
        "status": "research_only",
        "accounting_reconciled": portfolio.reconciliation()["reconciled"],
        "result_fingerprint": result_fingerprint,
        "strategy_fingerprint": strategy_fingerprint(spec),
        "information_timing": {
            "signal": "session close",
            "fill": "next available session open",
            "feature_cutoff": cfg.as_of,
        },
        "period": {"start": bars[0].session_date, "end": bars[-1].session_date,
                   "sessions": len(curve), "years": len(year_counts)},
        "data_sources": list(sources.values()),
        "data_rights": [{"source_id": source, "kind": info.get("kind"),
                         "rights": rights_by_source.get(source)}
                        for source, info in sources.items()],
        "validation": {
            "method": "in_sample_only",
            "out_of_sample": False,
            "walk_forward": False,
            "multiple_testing_adjusted": False,
            "parameter_grid_trials": 1,
            "note": "This run is exploratory; it is not evidence of a persistent trading advantage.",
        },
        "accounting": portfolio.reconciliation(),
        "warnings": warnings,
        "limitations": [
            "Single instrument and long-only in this Lab release.",
            "Next-open fills use the raw session open; partial fills, queues and market impact are not modeled.",
            "Corporate actions use actions known at the information cutoff; missing actions are not imputed.",
            "Vendor rows downloaded later are not proof of the value displayed at the historical instant.",
            "No statistical significance claim is made from one backtest.",
        ],
    }
    elapsed = (__import__("time").perf_counter() - started) * 1000
    return {
        "schema": "atlas.quant.backtest.v1",
        "simulator_version": SIMULATOR_VERSION,
        "strategy": spec,
        "config": {"as_of": cfg.as_of, "start": bars[0].session_date,
                   "end": bars[-1].session_date, "initial_capital": cfg.initial_capital,
                   "commission_bps": cfg.commission_bps, "slippage_bps": cfg.slippage_bps,
                   "mode": cfg.mode},
        "security": {"security_id": security_id, "mic": mic},
        "period": {"start": bars[0].session_date, "end": bars[-1].session_date,
                   "sessions": len(curve), "missing_weekdays": _missing_sessions(bars)},
        "equity_curve": curve,
        "benchmark_curve": benchmark_curve,
        "trades": [item for item in portfolio.ledger if item.get("side") in {"buy", "sell"}],
        "ledger": portfolio.ledger,
        "benchmark_trades": [item for item in benchmark_portfolio.ledger
                             if item.get("side") in {"buy", "sell"}],
        "metrics": metrics,
        "benchmark": {"metrics": benchmark_metrics, "reconciliation": benchmark_portfolio.reconciliation()},
        "reconciliation": portfolio.reconciliation(),
        "credibility": credibility,
        "feature_fingerprint": feature_result.feature_fingerprint,
        "feature_metadata": feature_result.metadata,
        "result_fingerprint": result_fingerprint,
        "duration_ms": round(elapsed, 3),
        "warnings": warnings,
    }


__all__ = ["SIMULATOR_VERSION", "SimulationConfig", "compute_metrics", "run_simulation"]
