"""Point-in-time cross-sectional features for the learning runtime.

Every feature at date ``t`` uses closes at or before ``t``. The target is the
next-session return from ``t`` to ``t+1``; its outcome date is recorded separately,
so an evaluator cannot pretend it was known at ``t``. Cross-sectional ranks use
only the securities present on ``t``. Normalisation is fitted later, on training
rows only.
"""

from __future__ import annotations

import math
from typing import Any

from ..core.errors import ValidationError
from .data import validate_panel

FEATURE_SCHEMA = "atlas.learning.feature.v2"

FEATURE_SPECS: tuple[dict[str, Any], ...] = (
    {"key": "mom_5", "label": "5-session momentum", "window": 5,
     "formula": "close[t] / close[t-5] - 1", "family": "momentum"},
    {"key": "mom_20", "label": "20-session momentum", "window": 20,
     "formula": "close[t] / close[t-20] - 1", "family": "momentum"},
    {"key": "mom_60", "label": "60-session momentum", "window": 60,
     "formula": "close[t] / close[t-60] - 1", "family": "momentum"},
    {"key": "vol_20", "label": "20-session volatility", "window": 20,
     "formula": "sample standard deviation of daily returns, last 20 sessions",
     "family": "risk"},
    {"key": "sma_gap_20", "label": "Price / SMA gap", "window": 20,
     "formula": "close[t] / mean(close[t-19..t]) - 1", "family": "trend"},
    {"key": "volume_z_20", "label": "Volume z-score", "window": 20,
     "formula": "(volume[t] - mean(volume[t-19..t])) / stdev(volume)",
     "family": "liquidity"},
    {"key": "cs_mom_20_rank", "label": "Cross-sectional momentum rank", "window": 20,
     "formula": "percentile rank of mom_20 across available securities at t",
     "family": "cross_section"},
)
FEATURE_KEYS = tuple(item["key"] for item in FEATURE_SPECS)
DEFAULT_FEATURES = ("mom_5", "mom_20", "vol_20", "sma_gap_20", "cs_mom_20_rank")
TARGETS = {
    "direction": {
        "label": "Next-session direction",
        "definition": "1 when close[t+1] > close[t], otherwise 0",
        "kind": "binary",
        "horizon": 1,
    },
    "return": {
        "label": "Next-session return",
        "definition": "close[t+1] / close[t] - 1",
        "kind": "continuous",
        "horizon": 1,
    },
}


def catalogue() -> dict[str, Any]:
    return {
        "schema": FEATURE_SCHEMA,
        "features": [dict(item) for item in FEATURE_SPECS],
        "targets": TARGETS,
        "timing": "features use data through t; targets use t+1 and carry target_date",
        "normalisation": "mean and scale fitted on training rows only",
        "missing_policy": "a row is omitted if any selected feature is unavailable",
    }


def normalise_features(features: Any) -> list[str]:
    if features is None:
        features = list(DEFAULT_FEATURES)
    if not isinstance(features, (list, tuple)) or not features:
        raise ValidationError("select at least one feature")
    result: list[str] = []
    for key in features:
        if not isinstance(key, str) or key not in FEATURE_KEYS:
            raise ValidationError("unknown learning feature", feature=key, supported=list(FEATURE_KEYS))
        if key not in result:
            result.append(key)
    if len(result) > 8:
        raise ValidationError("too many features", limit=8)
    return result


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))


def _pct_rank(values: dict[str, float], key: str) -> float:
    ordered = sorted(values.items(), key=lambda item: item[1])
    if len(ordered) == 1:
        return 0.5
    position = next(index for index, item in enumerate(ordered) if item[0] == key)
    return position / (len(ordered) - 1)


def build_rows(
    panel: dict[str, Any],
    *,
    features: Any = None,
    target: str = "direction",
    min_history: int = 60,
) -> dict[str, Any]:
    """Return aligned feature rows and explicit target/outcome dates."""
    validate_panel(panel)
    keys = normalise_features(features)
    if target not in TARGETS:
        raise ValidationError("unknown target", target=target, supported=list(TARGETS))
    specs = {item["key"]: item for item in FEATURE_SPECS}
    required = max(specs[key]["window"] for key in keys)
    min_history = max(int(min_history), required + 1)
    dates: list[str] = list(panel["dates"])
    closes: dict[str, list[float]] = panel["closes"]
    volumes: dict[str, list[float | None]] = panel.get("volumes") or {}
    rows: list[dict[str, Any]] = []
    max_available = 0
    for index in range(min_history, len(dates) - 1):
        day = dates[index]
        momentums: dict[str, dict[str, float]] = {}
        for security, values in closes.items():
            momentums[security] = {}
            for window in (5, 20, 60):
                if index >= window and values[index - window] > 0:
                    momentums[security][f"mom_{window}"] = values[index] / values[index - window] - 1.0
        for security, values in closes.items():
            computed: dict[str, float] = {}
            for key in keys:
                window = int(specs[key]["window"])
                if key in momentums[security]:
                    computed[key] = momentums[security][key]
                elif key == "vol_20" and index >= 20:
                    returns = [values[i] / values[i - 1] - 1.0
                               for i in range(index - 19, index + 1) if values[i - 1] > 0]
                    if len(returns) == 20:
                        computed[key] = _stdev(returns)
                elif key == "sma_gap_20" and index >= 19:
                    mean = _mean(values[index - 19:index + 1])
                    if mean > 0:
                        computed[key] = values[index] / mean - 1.0
                elif key == "volume_z_20" and index >= 19:
                    volume_values = volumes.get(security) or []
                    sample = [volume_values[i] for i in range(index - 19, index + 1)
                              if i < len(volume_values) and volume_values[i] is not None]
                    if len(sample) == 20 and _stdev([float(v) for v in sample]) > 0:
                        computed[key] = (float(sample[-1]) - _mean([float(v) for v in sample])) / _stdev([float(v) for v in sample])
                elif key == "cs_mom_20_rank":
                    available = {name: values_map["mom_20"] for name, values_map in momentums.items()
                                 if "mom_20" in values_map}
                    if security in available:
                        computed[key] = _pct_rank(available, security)
            if len(computed) != len(keys):
                continue
            target_return = values[index + 1] / values[index] - 1.0
            rows.append({
                "date": day,
                "target_date": dates[index + 1],
                "security_id": security,
                "features": {key: float(computed[key]) for key in keys},
                "target_return": target_return,
                "target": 1.0 if target_return > 0 else 0.0,
                "available_at": f"{day}T23:59:59Z",
            })
            max_available += 1
    if not rows:
        raise ValidationError("no feature rows could be constructed",
                              sessions=len(dates), minimum_history=min_history)
    return {
        "schema": FEATURE_SCHEMA,
        "features": keys,
        "target": target,
        "target_definition": TARGETS[target],
        "horizon": 1,
        "rows": rows,
        "row_count": len(rows),
        "dates": sorted({row["date"] for row in rows}),
        "timing": {
            "feature_cutoff": "session t close",
            "label_outcome": "session t+1 close",
            "purge": "one session between partitions in addition to the evaluator embargo",
            "target_known_after": "t+1 close",
        },
        "panel_hash": panel["content_hash"],
    }


def matrix(rows: list[dict[str, Any]], features: list[str]) -> tuple[list[list[float]], list[float]]:
    x = [[float(row["features"][key]) for key in features] for row in rows]
    y = [float(row["target"]) for row in rows]
    return x, y


def max_abs_correlation(x: list[list[float]]) -> float:
    """Largest absolute pairwise Pearson correlation; used by the auditor."""
    if not x or not x[0]:
        return 0.0
    columns = list(zip(*x))
    worst = 0.0
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            a, b = columns[i], columns[j]
            mean_a, mean_b = _mean(list(a)), _mean(list(b))
            cov = sum((u - mean_a) * (v - mean_b) for u, v in zip(a, b))
            den = math.sqrt(sum((u - mean_a) ** 2 for u in a) * sum((v - mean_b) ** 2 for v in b))
            if den:
                worst = max(worst, abs(cov / den))
    return worst


__all__ = [
    "DEFAULT_FEATURES",
    "FEATURE_KEYS",
    "FEATURE_SCHEMA",
    "FEATURE_SPECS",
    "TARGETS",
    "build_rows",
    "catalogue",
    "matrix",
    "max_abs_correlation",
    "normalise_features",
]
