"""Technical indicator registry.

Every indicator is a pure function of canonical Atlas market bars: it receives the
stored OHLCV observations (never a vendor API response) and returns a deterministic
series aligned to those bars. The registry is versioned so a workflow that saved
"RSI with window 14" can be reproduced even if the default parameters change later.

Design rules
------------
* **Explicit warm-up.** A value is ``None`` until enough observations exist. The
  terminal renders a gap rather than a fabricated partial value.
* **Documented formulas.** ``formula`` is displayed in the UI and asserted by tests
  against hand-computed reference series.
* **No silent parameter invention.** Unknown or out-of-range parameters raise.
* **Units are part of the output.** Returns, volatility and drawdown are fractions
  (0.05 = 5%); the frontend formats them, it never rescales the math.

The registry is the Phase 2 seed of the universal model registry: the same identity
shape (``atlas.<family>.<name>.v1``) is used by derived evidence rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..core.errors import ValidationError

VERSION_PREFIX = "atlas.indicator"


@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    kind: str  # "int" | "float"
    default: float
    minimum: float
    maximum: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    key: str
    label: str
    family: str
    inputs: tuple[str, ...]
    pane: str  # "overlay" (on price) | "separate"
    description: str
    formula: str
    params: tuple[ParamSpec, ...]
    outputs: tuple[tuple[str, str], ...]  # (series name, role)

    @property
    def version(self) -> str:
        return f"{VERSION_PREFIX}.{self.key}.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "family": self.family,
            "version": self.version,
            "inputs": list(self.inputs),
            "pane": self.pane,
            "description": self.description,
            "formula": self.formula,
            "params": [p.to_dict() for p in self.params],
            "outputs": [{"name": name, "role": role} for name, role in self.outputs],
        }


REGISTRY: dict[str, IndicatorSpec] = {
    spec.key: spec
    for spec in (
        IndicatorSpec(
            key="sma",
            label="Simple moving average",
            family="trend",
            inputs=("close",),
            pane="overlay",
            description="Arithmetic mean of the last N closing prices.",
            formula="SMA_t = (1/N) * Σ_{i=0}^{N-1} close_{t-i}",
            params=(ParamSpec("window", "int", 50, 2, 400, "Number of sessions in the average."),),
            outputs=(("sma", "line"),),
        ),
        IndicatorSpec(
            key="ema",
            label="Exponential moving average",
            family="trend",
            inputs=("close",),
            pane="overlay",
            description=(
                "Recursively weighted mean. Seeded with the simple mean of the first N "
                "observations, then smoothed with alpha = 2/(N+1)."
            ),
            formula="EMA_t = alpha*close_t + (1-alpha)*EMA_{t-1}, alpha = 2/(N+1)",
            params=(ParamSpec("window", "int", 20, 2, 400, "Smoothing window."),),
            outputs=(("ema", "line"),),
        ),
        IndicatorSpec(
            key="bollinger",
            label="Bollinger Bands",
            family="volatility",
            inputs=("close",),
            pane="overlay",
            description=(
                "Moving average with bands at +/- k population standard deviations of the "
                "same window. Population (not sample) deviation is used, stated so the "
                "numbers are reproducible."
            ),
            formula="mid_t = SMA_N(close); band_t = mid_t +/- k * stdev_N(close)",
            params=(
                ParamSpec("window", "int", 20, 2, 400, "Moving-average and deviation window."),
                ParamSpec("num_std", "float", 2.0, 0.5, 5.0, "Band width in standard deviations."),
            ),
            outputs=(("middle", "line"), ("upper", "band"), ("lower", "band")),
        ),
        IndicatorSpec(
            key="vwap",
            label="Rolling VWAP",
            family="volume",
            inputs=("high", "low", "close", "volume"),
            pane="overlay",
            description=(
                "Volume-weighted average of the typical price over a rolling window of "
                "sessions. Daily bars cannot produce a true intraday session VWAP, so this "
                "is explicitly a rolling measure and must be labelled as such."
            ),
            formula="VWAP_t = Σ(typical_i * volume_i) / Σ(volume_i), typical = (H+L+C)/3",
            params=(ParamSpec("window", "int", 20, 2, 400, "Sessions in the rolling window."),),
            outputs=(("vwap", "line"),),
        ),
        IndicatorSpec(
            key="rsi",
            label="Relative Strength Index",
            family="momentum",
            inputs=("close",),
            pane="separate",
            description=(
                "Wilder's RSI: average gains and losses seeded over N deltas and then "
                "smoothed. A window with no losses yields 100; no gains yields 0."
            ),
            formula="RSI = 100 - 100/(1+RS), RS = avg_gain_N / avg_loss_N",
            params=(ParamSpec("window", "int", 14, 2, 200, "Wilder smoothing period."),),
            outputs=(("rsi", "line"),),
        ),
        IndicatorSpec(
            key="macd",
            label="MACD",
            family="momentum",
            inputs=("close",),
            pane="separate",
            description="Difference of two EMAs, with an EMA signal line and histogram.",
            formula="MACD = EMA_fast - EMA_slow; signal = EMA_signal(MACD); hist = MACD - signal",
            params=(
                ParamSpec("fast", "int", 12, 2, 200, "Fast EMA window."),
                ParamSpec("slow", "int", 26, 3, 400, "Slow EMA window."),
                ParamSpec("signal", "int", 9, 2, 200, "Signal EMA window."),
            ),
            outputs=(("macd", "line"), ("signal", "line"), ("histogram", "histogram")),
        ),
        IndicatorSpec(
            key="rolling_volatility",
            label="Rolling volatility",
            family="risk",
            inputs=("close",),
            pane="separate",
            description=(
                "Annualised standard deviation of daily log returns. Output is a fraction "
                "(0.24 means 24%), using a 252-session year and population deviation."
            ),
            formula="sigma_t = stdev_N(ln(P_i/P_{i-1})) * sqrt(252)",
            params=(
                ParamSpec("window", "int", 20, 2, 400, "Return observations in the window."),
                ParamSpec("annualization", "int", 252, 1, 366, "Sessions per year."),
            ),
            outputs=(("volatility", "line"),),
        ),
        IndicatorSpec(
            key="rolling_returns",
            label="Rolling return",
            family="performance",
            inputs=("close",),
            pane="separate",
            description="Simple return over N sessions, as a fraction (0.05 means 5%).",
            formula="r_t = P_t / P_{t-N} - 1",
            params=(ParamSpec("window", "int", 21, 1, 400, "Look-back in sessions."),),
            outputs=(("return", "line"),),
        ),
        IndicatorSpec(
            key="drawdown",
            label="Drawdown",
            family="risk",
            inputs=("close",),
            pane="separate",
            description=(
                "Decline from the highest close seen so far in the loaded window, as a "
                "negative fraction. The running peak is window-dependent by construction."
            ),
            formula="DD_t = P_t / max(P_0..P_t) - 1",
            params=(),
            outputs=(("drawdown", "line"),),
        ),
    )
}


# --------------------------------------------------------------------------- math
def _sma(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total / window
    return out


def _ema(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < window:
        return out
    seed = sum(values[:window]) / window
    out[window - 1] = seed
    alpha = 2.0 / (window + 1)
    previous = seed
    for i in range(window, len(values)):
        previous = alpha * values[i] + (1.0 - alpha) * previous
        out[i] = previous
    return out


def _ema_optional(values: Sequence[float | None], window: int) -> list[float | None]:
    """EMA over a series with a leading warm-up gap."""
    out: list[float | None] = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None:
        return out
    dense = [v for v in values[start:] if v is not None]
    computed = _ema(dense, window)
    for offset, value in enumerate(computed):
        if value is not None:
            out[start + offset] = value
    return out


def _population_stdev(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _rolling_stdev(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = _population_stdev(values[i - window + 1 : i + 1])
    return out


# ----------------------------------------------------------------------- compute
def _bars(bars: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if not bars:
        raise ValidationError("indicator computation requires at least one bar")
    cleaned: list[dict[str, Any]] = []
    previous_date: str | None = None
    for bar in bars:
        date = str(bar.get("date") or bar.get("time") or "")[:10]
        if not date:
            raise ValidationError("bar is missing a date", bar=bar)
        if previous_date is not None and date <= previous_date:
            raise ValidationError(
                "bars must be strictly ordered by date with no duplicates",
                previous=previous_date,
                current=date,
            )
        previous_date = date
        cleaned.append(
            {
                "date": date,
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": float(bar.get("volume") or 0.0),
            }
        )
    return cleaned


def resolve_params(spec: IndicatorSpec, params: dict[str, Any] | None) -> dict[str, float]:
    supplied = dict(params or {})
    known = {p.name for p in spec.params}
    unknown = set(supplied) - known
    if unknown:
        raise ValidationError(
            "unknown indicator parameter", indicator=spec.key, unknown=sorted(unknown), supported=sorted(known)
        )
    resolved: dict[str, float] = {}
    for param in spec.params:
        raw = supplied.get(param.name, param.default)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValidationError(
                "indicator parameter must be a number", indicator=spec.key, parameter=param.name
            )
        value = float(raw)
        if param.kind == "int":
            if value != int(value):
                raise ValidationError(
                    "indicator parameter must be an integer", indicator=spec.key, parameter=param.name
                )
            value = float(int(value))
        if not (param.minimum <= value <= param.maximum):
            raise ValidationError(
                "indicator parameter out of range",
                indicator=spec.key,
                parameter=param.name,
                value=value,
                minimum=param.minimum,
                maximum=param.maximum,
            )
        resolved[param.name] = value
    return resolved


def _pairs(dates: Sequence[str], series: Sequence[float | None]) -> list[dict[str, Any]]:
    return [{"time": dates[i], "value": series[i]} for i in range(len(series)) if series[i] is not None]


def _calculate(spec: IndicatorSpec, bars: list[dict[str, Any]], params: dict[str, float]) -> tuple[list[tuple[str, str, list[float | None]]], list[str]]:
    dates = [bar["date"] for bar in bars]
    closes = [bar["close"] for bar in bars]
    warnings: list[str] = []
    window = int(params.get("window", 0)) if "window" in params else 0

    if spec.key == "sma":
        return [("sma", "line", _sma(closes, window))], warnings
    if spec.key == "ema":
        return [("ema", "line", _ema(closes, window))], warnings
    if spec.key == "bollinger":
        mid = _sma(closes, window)
        dev = _rolling_stdev(closes, window)
        k = params["num_std"]
        upper = [None if m is None or d is None else m + k * d for m, d in zip(mid, dev)]
        lower = [None if m is None or d is None else m - k * d for m, d in zip(mid, dev)]
        return [("middle", "line", mid), ("upper", "band", upper), ("lower", "band", lower)], warnings
    if spec.key == "vwap":
        points: list[float | None] = [None] * len(bars)
        typical = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars]
        volumes = [b["volume"] for b in bars]
        for i in range(window - 1, len(bars)):
            pv = sum(typical[j] * volumes[j] for j in range(i - window + 1, i + 1))
            vol = sum(volumes[j] for j in range(i - window + 1, i + 1))
            points[i] = pv / vol if vol else None
            if vol == 0:
                warnings.append(f"zero volume in VWAP window ending {dates[i]}; value omitted")
        return [("vwap", "line", points)], warnings
    if spec.key == "rsi":
        out: list[float | None] = [None] * len(bars)
        gains = [0.0] * len(bars)
        losses = [0.0] * len(bars)
        for i in range(1, len(bars)):
            change = closes[i] - closes[i - 1]
            gains[i] = max(change, 0.0)
            losses[i] = max(-change, 0.0)
        if len(bars) > window:
            avg_gain = sum(gains[1 : window + 1]) / window
            avg_loss = sum(losses[1 : window + 1]) / window
            out[window] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            for i in range(window + 1, len(bars)):
                avg_gain = (avg_gain * (window - 1) + gains[i]) / window
                avg_loss = (avg_loss * (window - 1) + losses[i]) / window
                out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        return [("rsi", "line", out)], warnings
    if spec.key == "macd":
        fast = int(params["fast"])
        slow = int(params["slow"])
        signal_window = int(params["signal"])
        if fast >= slow:
            raise ValidationError("MACD fast window must be shorter than the slow window", fast=fast, slow=slow)
        fast_ema = _ema(closes, fast)
        slow_ema = _ema(closes, slow)
        line = [None if f is None or s is None else f - s for f, s in zip(fast_ema, slow_ema)]
        signal = _ema_optional(line, signal_window)
        hist = [None if m is None or s is None else m - s for m, s in zip(line, signal)]
        return [("macd", "line", line), ("signal", "line", signal), ("histogram", "histogram", hist)], warnings
    if spec.key == "rolling_volatility":
        annual = int(params["annualization"])
        returns: list[float | None] = [None] * len(bars)
        for i in range(1, len(bars)):
            if closes[i - 1] > 0 and closes[i] > 0:
                returns[i] = math.log(closes[i] / closes[i - 1])
        dense = [r for r in returns if r is not None]
        dev = _rolling_stdev(dense, window)
        out = [None] * len(bars)
        valid = [i for i, r in enumerate(returns) if r is not None]
        for offset, value in enumerate(dev):
            if value is not None:
                out[valid[offset]] = value * math.sqrt(annual)
        return [("volatility", "line", out)], warnings
    if spec.key == "rolling_returns":
        lookback = int(params["window"])
        out = [None] * len(bars)
        for i in range(lookback, len(bars)):
            if closes[i - lookback] > 0:
                out[i] = closes[i] / closes[i - lookback] - 1.0
        return [("return", "line", out)], warnings
    if spec.key == "drawdown":
        out = [None] * len(bars)
        peak = 0.0
        for i, close in enumerate(closes):
            peak = max(peak, close)
            out[i] = close / peak - 1.0 if peak else None
        return [("drawdown", "line", out)], warnings
    raise ValidationError("indicator is not implemented", indicator=spec.key)


def compute_indicator(
    key: str, bars: Sequence[dict[str, Any]], params: dict[str, Any] | None = None
) -> dict[str, Any]:
    spec = REGISTRY.get(key)
    if spec is None:
        raise ValidationError("unknown indicator", indicator=key, supported=sorted(REGISTRY))
    resolved = resolve_params(spec, params)
    cleaned = _bars(bars)
    series, warnings = _calculate(spec, cleaned, resolved)
    dates = [bar["date"] for bar in cleaned]
    payload = [
        {
            "name": name,
            "role": role,
            "points": _pairs(dates, values),
            "observations": sum(1 for v in values if v is not None),
        }
        for name, role, values in series
    ]
    warmup = min((len(cleaned) - s["observations"] for s in payload), default=0)
    if warmup >= len(cleaned):
        warnings.append("insufficient observations for every value in this window")
    elif warmup:
        warnings.append(f"{warmup} leading observation(s) have no value during indicator warm-up")
    calculation_id = hashlib.sha256(
        json.dumps(
            {"indicator": spec.version, "params": resolved, "bars": len(cleaned)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:12]
    return {
        "key": spec.key,
        "label": spec.label,
        "version": spec.version,
        "calculation_id": calculation_id,
        "params": resolved,
        "pane": spec.pane,
        "formula": spec.formula,
        "series": payload,
        "warmup": warmup,
        "insufficient_data": warmup >= len(cleaned),
        "warnings": warnings,
    }


def compute_many(
    requests: Sequence[dict[str, Any]], bars: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    results = [compute_indicator(str(item.get("key")), bars, item.get("params")) for item in requests]
    return {
        "indicators": results,
        "signature": hashlib.sha256(
            json.dumps([r["calculation_id"] for r in results], separators=(",", ":")).encode()
        ).hexdigest()[:12],
    }


def catalog() -> list[dict[str, Any]]:
    return [REGISTRY[key].to_dict() for key in sorted(REGISTRY)]
