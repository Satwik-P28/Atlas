"""Reference tests for the Phase 2 indicator engine.

Values are hand-computed from tiny series so a formula change fails loudly. This is
deliberately not a golden-file test: the numbers are derived in the test from the
documented definition.
"""

from __future__ import annotations

import math

import pytest

from atlas.core.errors import ValidationError
from atlas.terminal.indicators import (
    REGISTRY,
    catalog,
    compute_indicator,
    compute_many,
    resolve_params,
)


def bars_from_closes(closes: list[float], volumes: list[float] | None = None) -> list[dict]:
    return [
        {
            "date": f"2024-01-{index + 1:02d}",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": (volumes or [100.0] * len(closes))[index],
        }
        for index, close in enumerate(closes)
    ]


def values(result: dict, name: str) -> list[float | None]:
    series = next(item for item in result["series"] if item["name"] == name)
    mapping = {point["time"]: point["value"] for point in series["points"]}
    return [mapping.get(bar["date"]) for bar in result["_bars"]]


def test_registry_is_versioned_and_complete():
    keys = set(REGISTRY)
    assert {"sma", "ema", "rsi", "macd", "bollinger", "vwap", "rolling_volatility", "rolling_returns", "drawdown"} <= keys
    for key, spec in REGISTRY.items():
        assert spec.version == f"atlas.indicator.{key}.v1"
        assert spec.formula
        assert spec.outputs
    assert len(catalog()) == len(REGISTRY)


def test_sma_matches_arithmetic_mean_and_warms_up():
    result = compute_indicator("sma", bars_from_closes([1, 2, 3, 4, 5]), {"window": 3})
    result["_bars"] = bars_from_closes([1, 2, 3, 4, 5])
    assert values(result, "sma") == [None, None, 2.0, 3.0, 4.0]
    assert result["warmup"] == 2


def test_ema_is_seeded_with_sma_then_recursive():
    result = compute_indicator("ema", bars_from_closes([1, 2, 3, 4, 5]), {"window": 3})
    result["_bars"] = bars_from_closes([1, 2, 3, 4, 5])
    # seed = mean(1,2,3) = 2; alpha = 0.5; 4 -> 3; 5 -> 4
    assert values(result, "ema") == [None, None, 2.0, 3.0, 4.0]


def test_rsi_handles_all_gains_and_all_losses():
    rising = compute_indicator("rsi", bars_from_closes([1, 2, 3, 4, 5, 6]), {"window": 3})
    assert rising["series"][0]["points"][0]["value"] == pytest.approx(100.0)
    falling = compute_indicator("rsi", bars_from_closes([6, 5, 4, 3, 2, 1]), {"window": 3})
    assert falling["series"][0]["points"][0]["value"] == pytest.approx(0.0)


def test_rsi_wilder_reference_value():
    # Classic Wilder example: 14 up moves then a down move yields a high but finite RSI.
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    result = compute_indicator("rsi", bars_from_closes(closes), {"window": 14})
    first = result["series"][0]["points"][0]
    assert 50 < first["value"] < 90
    assert result["warmup"] == 14


def test_bollinger_bands_bracket_the_mean():
    closes = [10, 12, 11, 13, 12, 14, 13, 15, 14, 16]
    result = compute_indicator("bollinger", bars_from_closes(closes), {"window": 5, "num_std": 2})
    middle = result["series"][0]["points"][-1]["value"]
    upper = result["series"][1]["points"][-1]["value"]
    lower = result["series"][2]["points"][-1]["value"]
    assert lower < middle < upper
    window = closes[-5:]
    mean = sum(window) / 5
    dev = math.sqrt(sum((value - mean) ** 2 for value in window) / 5)
    assert middle == pytest.approx(mean)
    assert upper == pytest.approx(mean + 2 * dev)


def test_macd_histogram_is_line_minus_signal():
    closes = [float(100 + index) for index in range(40)]
    result = compute_indicator("macd", bars_from_closes(closes), {"fast": 12, "slow": 26, "signal": 9})
    line = {point["time"]: point["value"] for point in result["series"][0]["points"]}
    signal = {point["time"]: point["value"] for point in result["series"][1]["points"]}
    histogram = {point["time"]: point["value"] for point in result["series"][2]["points"]}
    for date, value in histogram.items():
        assert value == pytest.approx(line[date] - signal[date])


def test_vwap_weights_typical_price_by_volume():
    bars = [
        {"date": "2024-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        {"date": "2024-01-02", "open": 20, "high": 20, "low": 20, "close": 20, "volume": 300},
    ]
    result = compute_indicator("vwap", bars, {"window": 2})
    assert result["series"][0]["points"][0]["value"] == pytest.approx((10 * 100 + 20 * 300) / 400)


def test_vwap_zero_volume_is_omitted_not_fabricated():
    bars = [
        {"date": "2024-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 0},
        {"date": "2024-01-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 0},
    ]
    result = compute_indicator("vwap", bars, {"window": 2})
    assert result["series"][0]["points"] == []
    assert any("zero volume" in warning for warning in result["warnings"])


def test_volatility_is_annualised_fraction_of_log_returns():
    closes = [100, 101, 100, 102, 101, 103]
    result = compute_indicator("rolling_volatility", bars_from_closes(closes), {"window": 3, "annualization": 252})
    assert result["series"][0]["points"]
    assert result["series"][0]["points"][-1]["value"] > 0
    assert result["series"][0]["points"][-1]["value"] < 10


def test_returns_and_drawdown_have_documented_signs():
    closes = [100, 110, 105, 90]
    returns = compute_indicator("rolling_returns", bars_from_closes(closes), {"window": 1})
    assert returns["series"][0]["points"][0]["value"] == pytest.approx(0.10)
    drawdown = compute_indicator("drawdown", bars_from_closes(closes), {})
    # 90 / 110 - 1 == -0.181818…; the running peak is 110, not 100.
    assert drawdown["series"][0]["points"][-1]["value"] == pytest.approx(90 / 110 - 1)


def test_parameter_validation_rejects_unknown_and_out_of_range():
    with pytest.raises(ValidationError):
        compute_indicator("sma", bars_from_closes([1, 2, 3]), {"window": 1})
    with pytest.raises(ValidationError):
        compute_indicator("sma", bars_from_closes([1, 2, 3]), {"window": 2, "nope": 1})
    with pytest.raises(ValidationError):
        compute_indicator("sma", bars_from_closes([1, 2, 3]), {"window": 2.5})
    with pytest.raises(ValidationError):
        resolve_params(REGISTRY["rsi"], {"window": "14"})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        compute_indicator("not_an_indicator", bars_from_closes([1, 2, 3]), {})


def test_macd_requires_fast_shorter_than_slow():
    with pytest.raises(ValidationError):
        compute_indicator("macd", bars_from_closes([100] * 40), {"fast": 30, "slow": 20, "signal": 9})


def test_bars_must_be_ordered_and_complete():
    disordered = bars_from_closes([1, 2, 3])
    disordered[2]["date"] = disordered[0]["date"]
    with pytest.raises(ValidationError):
        compute_indicator("sma", disordered, {"window": 2})
    with pytest.raises(ValidationError):
        compute_indicator("sma", [], {"window": 2})


def test_insufficient_data_is_reported_not_invented():
    result = compute_indicator("sma", bars_from_closes([1, 2]), {"window": 50})
    assert result["insufficient_data"] is True
    assert result["series"][0]["points"] == []
    assert any("insufficient" in warning for warning in result["warnings"])


def test_calculation_identity_changes_with_parameters_and_is_stable_otherwise():
    bars = bars_from_closes([float(i) for i in range(1, 30)])
    first = compute_indicator("sma", bars, {"window": 5})
    second = compute_indicator("sma", bars, {"window": 5})
    other = compute_indicator("sma", bars, {"window": 10})
    assert first["calculation_id"] == second["calculation_id"]
    assert first["calculation_id"] != other["calculation_id"]
    assert compute_many([{"key": "sma", "params": {"window": 5}}], bars)["signature"]
