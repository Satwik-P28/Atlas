"""Economic reality simulator v1.

The simulator is intentionally narrow: a temperature shock, a conditional demand
response, and an explicitly hypothetical firm exposure. It reports observation,
parameter, model-form and relationship uncertainty separately. It does not combine
them into a single confidence percentage and it never labels the weather response
causal.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow
from ..fec import compile_model
from ..fec.runtime import ExecutionEngine
from .contracts import SCENARIO_SCHEMA, digest, scenario_document

DEFAULT_ASSUMPTIONS = [
    "The shock applies to the reference day's observed mean temperature, not to a forecast.",
    "Facility load sensitivity to regional demand is an explicit scenario parameter, not an observed facility relationship.",
    "Unhedged electricity is priced at the declared flat power price; no forward curve or contract settlement is modeled.",
    "Revenue, tax rate and exposure are assumptions; they are not observed company data.",
]


def _clip_covariance(covariance: np.ndarray) -> np.ndarray:
    symmetric = (covariance + covariance.T) / 2.0
    values, vectors = np.linalg.eigh(symmetric)
    values = np.maximum(values, 0.0)
    return (vectors * values) @ vectors.T


def _weather_features(temp_mean_c: float) -> dict[str, float]:
    cdd = max(temp_mean_c - 18.0, 0.0)
    hdd = max(18.0 - temp_mean_c, 0.0)
    return {"cdd_18c": cdd, "hdd_18c": hdd, "cdd_squared": cdd * cdd}


def _vector(feature_names: list[str], features: dict[str, float]) -> np.ndarray:
    return np.asarray([1.0] + [float(features[name]) for name in feature_names], dtype=float)


def _predict(coefficients: list[float] | np.ndarray, feature_names: list[str],
             features: dict[str, float]) -> float:
    return float(np.asarray(coefficients, dtype=float) @ _vector(feature_names, features))


def _delta_fraction(analysis: dict[str, Any], shock_c: float) -> dict[str, float]:
    reference = analysis["reference"]
    feature_names = analysis["model"]["feature_names"]
    base_features = dict(reference["features"])
    shocked_features = dict(base_features)
    shocked_features.update(_weather_features(reference["temperature_mean_c"] + shock_c))
    base = _predict(analysis["model"]["coefficients"], feature_names, base_features)
    shocked = _predict(analysis["model"]["coefficients"], feature_names, shocked_features)
    return {
        "base_demand_mw": base,
        "shocked_demand_mw": shocked,
        "delta_mw": shocked - base,
        "delta_fraction": (shocked - base) / base if base else 0.0,
    }


def financial_model_spec() -> dict[str, Any]:
    return {
        "schema_version": "atlas.model.v1",
        "name": "Phase 7 energy cost and margin impact",
        "version": "1.0.0",
        "interface": "graph",
        "inputs": [
            {"name": "annual_consumption_mwh", "type": "Scalar"},
            {"name": "demand_change_fraction", "type": "Scalar"},
            {"name": "load_sensitivity", "type": "Scalar"},
            {"name": "unhedged_fraction", "type": "Scalar"},
            {"name": "power_price_usd_mwh", "type": "Price[USD]"},
            {"name": "revenue_usd", "type": "Money[USD]"},
            {"name": "tax_rate", "type": "Rate[annual]"},
        ],
        "nodes": [
            {"id": "facility_change", "op": "mul", "inputs": ["demand_change_fraction", "load_sensitivity"]},
            {"id": "cost_delta", "op": "energy_cost_impact",
             "inputs": ["annual_consumption_mwh", "facility_change", "unhedged_fraction", "power_price_usd_mwh"]},
            {"id": "ebit_delta", "op": "neg", "inputs": ["cost_delta"]},
            {"id": "after_tax_cost", "op": "after_tax_cost_impact", "inputs": ["cost_delta", "tax_rate"]},
            {"id": "margin_delta", "op": "margin_impact", "inputs": ["ebit_delta", "revenue_usd"]},
        ],
        "outputs": {
            "cost_delta_usd": "cost_delta",
            "ebit_delta_usd": "ebit_delta",
            "after_tax_cost_usd": "after_tax_cost",
            "margin_delta": "margin_delta",
        },
        "assumptions": ["No pass-through of electricity cost is assumed.", "The declared price is flat."],
    }


def _execute_financial(db: Any, *, demand_change_fraction: float, annual_consumption_mwh: float,
                       load_sensitivity: float, unhedged_fraction: float,
                       power_price_usd_mwh: float, revenue_usd: float,
                       tax_rate: float) -> dict[str, Any]:
    model = compile_model(financial_model_spec())
    result = ExecutionEngine(db, use_cache=False).execute(model, {
        "annual_consumption_mwh": annual_consumption_mwh,
        "demand_change_fraction": demand_change_fraction,
        "load_sensitivity": load_sensitivity,
        "unhedged_fraction": unhedged_fraction,
        "power_price_usd_mwh": power_price_usd_mwh,
        "revenue_usd": revenue_usd,
        "tax_rate": tax_rate,
    }, persist=False)
    return {
        "outputs": result["outputs"],
        "run_id": result["run_id"],
        "fingerprint": result["fingerprint"],
        "trace": result["trace"],
        "compiler": result["manifest"]["compiler_version"],
        "operator_versions": result["manifest"]["operator_versions"],
    }


def _financial_scalar(*, delta_fraction: float, annual_consumption_mwh: float,
                      load_sensitivity: float, unhedged_fraction: float,
                      power_price_usd_mwh: float, revenue_usd: float,
                      tax_rate: float) -> dict[str, float]:
    delta_mwh = annual_consumption_mwh * delta_fraction * load_sensitivity
    cost = delta_mwh * unhedged_fraction * power_price_usd_mwh
    return {
        "delta_mwh": delta_mwh,
        "cost_delta_usd": cost,
        "ebit_delta_usd": -cost,
        "after_tax_cost_usd": cost * (1.0 - tax_rate),
        "margin_delta": (-cost / revenue_usd) if revenue_usd else 0.0,
    }


def run_scenario(
    analysis: dict[str, Any], *, db: Any = None, shock_c: float = 2.0,
    annual_consumption_mwh: float = 50_000.0, load_sensitivity: float = 0.5,
    unhedged_fraction: float = 0.6, power_price_usd_mwh: float = 65.0,
    revenue_usd: float = 40_000_000.0, tax_rate: float = 0.21,
    draws: int = 2_000, seed: int = 20261105,
) -> dict[str, Any]:
    if not -10.0 <= shock_c <= 10.0:
        raise ValidationError("temperature shock must be in [-10,10] C")
    if annual_consumption_mwh < 0 or load_sensitivity < 0 or not 0 <= unhedged_fraction <= 1:
        raise ValidationError("invalid physical or contract exposure")
    if power_price_usd_mwh < 0 or revenue_usd <= 0 or not 0 <= tax_rate <= 1:
        raise ValidationError("invalid financial scenario assumption")
    if not 200 <= draws <= 20_000:
        raise ValidationError("draws must be in [200,20000]")

    reference = analysis["reference"]
    feature_names = analysis["model"]["feature_names"]
    base_features = dict(reference["features"])
    shocked_features = dict(base_features)
    shocked_features.update(_weather_features(reference["temperature_mean_c"] + shock_c))
    central = _delta_fraction(analysis, shock_c)
    beta = np.asarray(analysis["model"]["coefficients"], dtype=float)
    covariance = _clip_covariance(np.asarray(analysis["model"]["covariance"], dtype=float))
    rng = np.random.default_rng(seed)
    beta_draws = rng.multivariate_normal(beta, covariance, size=draws, check_valid="ignore")
    base_vector = _vector(feature_names, base_features)
    shock_vector = _vector(feature_names, shocked_features)
    base_draws = beta_draws @ base_vector
    shock_draws = beta_draws @ shock_vector
    fraction_draws = np.divide(shock_draws - base_draws, base_draws,
                               out=np.zeros_like(base_draws), where=np.abs(base_draws) > 1e-9)
    residual_sigma = float(analysis["model"]["residual_sigma"])
    predictive_shock = shock_draws + rng.normal(0.0, residual_sigma, size=draws)
    parameter_interval = [float(np.percentile(fraction_draws, 5)),
                          float(np.percentile(fraction_draws, 95))]
    predictive_interval = [float(np.percentile(predictive_shock, 5)),
                           float(np.percentile(predictive_shock, 95))]

    financial = _execute_financial(
        db, demand_change_fraction=central["delta_fraction"],
        annual_consumption_mwh=annual_consumption_mwh, load_sensitivity=load_sensitivity,
        unhedged_fraction=unhedged_fraction, power_price_usd_mwh=power_price_usd_mwh,
        revenue_usd=revenue_usd, tax_rate=tax_rate,
    )
    central_financial = _financial_scalar(
        delta_fraction=central["delta_fraction"], annual_consumption_mwh=annual_consumption_mwh,
        load_sensitivity=load_sensitivity, unhedged_fraction=unhedged_fraction,
        power_price_usd_mwh=power_price_usd_mwh, revenue_usd=revenue_usd, tax_rate=tax_rate,
    )
    # The compiler is authoritative for the central arithmetic. This assertion keeps
    # the vectorised uncertainty path from silently diverging from it.
    for key in ("cost_delta_usd", "after_tax_cost_usd", "margin_delta"):
        compiled = float(financial["outputs"][key])
        if abs(compiled - central_financial[key]) > 1e-6:
            raise ValidationError("financial vectorisation diverged from compiler", field=key,
                                  compiled=compiled, vectorised=central_financial[key])
    cost_draws = np.asarray([
        _financial_scalar(
            delta_fraction=float(value), annual_consumption_mwh=annual_consumption_mwh,
            load_sensitivity=load_sensitivity, unhedged_fraction=unhedged_fraction,
            power_price_usd_mwh=power_price_usd_mwh, revenue_usd=revenue_usd, tax_rate=tax_rate,
        )["cost_delta_usd"]
        for value in fraction_draws
    ])
    cost_interval = [float(np.percentile(cost_draws, 5)), float(np.percentile(cost_draws, 95))]

    observation_low = _delta_fraction(analysis, shock_c - 0.05)["delta_fraction"]
    observation_high = _delta_fraction(analysis, shock_c + 0.05)["delta_fraction"]
    model_form = []
    for key, alternative in (analysis.get("alternatives") or {}).items():
        alt_names = alternative["features"]
        alt_features = dict(base_features)
        alt_features.update(_weather_features(reference["temperature_mean_c"] + shock_c))
        alt_base = dict(base_features)
        alt_shock = dict(alt_features)
        alt_central = ((_predict(alternative["coefficients"], alt_names, alt_shock)
                        - _predict(alternative["coefficients"], alt_names, alt_base))
                       / _predict(alternative["coefficients"], alt_names, alt_base))
        model_form.append({"model": key, "delta_fraction": alt_central})

    shock_grid = []
    for shock in (-2.0, 0.0, 2.0, 4.0):
        delta = _delta_fraction(analysis, shock)["delta_fraction"]
        value = _financial_scalar(
            delta_fraction=delta, annual_consumption_mwh=annual_consumption_mwh,
            load_sensitivity=load_sensitivity, unhedged_fraction=unhedged_fraction,
            power_price_usd_mwh=power_price_usd_mwh, revenue_usd=revenue_usd, tax_rate=tax_rate,
        )
        shock_grid.append({"shock_c": shock, "demand_change_fraction": delta,
                           "cost_delta_usd": value["cost_delta_usd"]})
    price_grid = []
    for price in (45.0, 65.0, 85.0):
        value = _financial_scalar(
            delta_fraction=central["delta_fraction"], annual_consumption_mwh=annual_consumption_mwh,
            load_sensitivity=load_sensitivity, unhedged_fraction=unhedged_fraction,
            power_price_usd_mwh=price, revenue_usd=revenue_usd, tax_rate=tax_rate,
        )
        price_grid.append({"price_usd_mwh": price, "cost_delta_usd": value["cost_delta_usd"]})
    hedge_grid = []
    for hedge in (0.2, 0.6, 0.9):
        value = _financial_scalar(
            delta_fraction=central["delta_fraction"], annual_consumption_mwh=annual_consumption_mwh,
            load_sensitivity=load_sensitivity, unhedged_fraction=1.0 - hedge,
            power_price_usd_mwh=power_price_usd_mwh, revenue_usd=revenue_usd, tax_rate=tax_rate,
        )
        hedge_grid.append({"hedge_fraction": hedge, "cost_delta_usd": value["cost_delta_usd"]})

    document = scenario_document(
        name=f"Temperature +{shock_c:.1f} C at {reference['date']}",
        shock_c=shock_c, reference_date=reference["date"],
        reference_temperature_c=reference["temperature_mean_c"],
        demand_change_fraction=central["delta_fraction"],
        demand_change_interval=parameter_interval,
        financial={
            "annual_consumption_mwh": annual_consumption_mwh,
            "load_sensitivity": load_sensitivity,
            "unhedged_fraction": unhedged_fraction,
            "power_price_usd_mwh": power_price_usd_mwh,
            "revenue_usd": revenue_usd,
            "tax_rate": tax_rate,
            "delta_mwh": central_financial["delta_mwh"],
            "cost_delta_usd": central_financial["cost_delta_usd"],
            "after_tax_cost_usd": central_financial["after_tax_cost_usd"],
            "margin_delta": central_financial["margin_delta"],
            "compiler_run_id": financial["run_id"],
            "compiler_fingerprint": financial["fingerprint"],
            "cost_interval_90": cost_interval,
        },
        assumptions=DEFAULT_ASSUMPTIONS,
        limitations=[
            "Counterfactual and hypothetical, not an observed event.",
            "Parameter interval conditions on the model family; model-form and relationship uncertainty are separate.",
            "No equity valuation or credit spread is calculated in this slice.",
        ],
    )
    result = {
        **document,
        "schema": SCENARIO_SCHEMA,
        "analysis_run_id": analysis["run_id"],
        "data_class": "hypothetical",
        "reference_prediction": {
            "base_demand_mw": central["base_demand_mw"],
            "shocked_demand_mw": central["shocked_demand_mw"],
            "delta_mw": central["delta_mw"],
            "delta_fraction": central["delta_fraction"],
            "parameter_interval_90_fraction": parameter_interval,
            "predictive_interval_90_mw": predictive_interval,
        },
        "uncertainty": {
            "observation": {
                "temperature_quantization_c": 0.1,
                "demand_fraction_range_for_0.05c": [observation_low, observation_high],
                "note": "Separate from parameter and model-form uncertainty.",
            },
            "parameter": {
                "type": "multivariate_normal_coefficient_draws",
                "draws": draws,
                "interval_90_demand_fraction": parameter_interval,
                "interval_90_cost_usd": cost_interval,
            },
            "model_form": {
                "alternatives": model_form,
                "note": "Difference between selected degree-day specification and available alternatives.",
            },
            "relationship": {
                "status": "not_identified",
                "note": "Weather is not randomly assigned; no causal interval is reported.",
            },
            "combined": None,
        },
        "sensitivity": {"temperature": shock_grid, "power_price": price_grid, "hedge": hedge_grid},
        "financial_compiler": {k: financial[k] for k in ("run_id", "fingerprint", "compiler")},
        "narrative": (
            f"A {shock_c:+.1f} C shift at {reference['date']} changes conditional demand by "
            f"{central['delta_fraction'] * 100:+.2f}%, costing the hypothetical facility "
            f"${central_financial['cost_delta_usd']:,.0f} on an unhedged basis. "
            "This is a counterfactual association, not a causal estimate or observed company result."
        ),
        "created_at": iso(utcnow()),
        "fingerprint": digest({
            "analysis": analysis["fingerprint"], "shock": shock_c,
            "annual": annual_consumption_mwh, "sensitivity": load_sensitivity,
            "hedge": unhedged_fraction, "price": power_price_usd_mwh,
            "revenue": revenue_usd, "tax": tax_rate, "draws": draws, "seed": seed,
        }),
    }
    return result
