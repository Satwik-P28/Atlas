"""Institutional valuation laboratory built on the FEC.

The DCF is not a separate engine: it is a canonical ``atlas.model.v1`` graph compiled and
executed by the same compiler used by equations, the SDK and Model Forge. The pure
functions in tests independently reproduce the arithmetic; this module never pretends an
assumption is an observed fact.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from ..core.errors import MissingDataError, ValidationError
from ..storage.db import Database
from ..terminal import read_models
from ..terminal.metric_store import get_issuer_metrics
from .compiler import compile_model
from .runtime import ExecutionEngine

VALUATION_SCHEMA = "atlas.valuation.v1"
DCF_DEFAULTS = {
    "horizon": 5,
    "revenue_growth": [0.05, 0.05, 0.05, 0.04, 0.04],
    "operating_margin": 0.18,
    "tax_rate": 0.21,
    "da_pct_revenue": 0.04,
    "capex_pct_revenue": 0.05,
    "nwc_pct_revenue": 0.02,
    "wacc": 0.09,
    "terminal_growth": 0.025,
    "terminal_method": "gordon_growth",
    "exit_multiple": 12.0,
    "convention": "end_year",
    "cash": 0.0,
    "debt": 0.0,
    # Deliberately zero: a missing share count must fail validation instead of
    # producing a per-share value from an invented single share.
    "shares": 0.0,
}
ASSUMPTION_KEYS = set(DCF_DEFAULTS)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be a number", field=name)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number", field=name) from exc
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be finite", field=name)
    return number


def _normalise(assumptions: dict[str, Any] | None) -> dict[str, Any]:
    supplied = dict(assumptions or {})
    unknown = sorted(set(supplied) - ASSUMPTION_KEYS - {"revenue", "provenance"})
    if unknown:
        raise ValidationError("unknown valuation assumptions", assumptions=unknown,
                              supported=sorted(ASSUMPTION_KEYS))
    merged = dict(DCF_DEFAULTS)
    merged.update({key: value for key, value in supplied.items()
                   if key in ASSUMPTION_KEYS})
    horizon = int(_number(merged["horizon"], "horizon"))
    if not 1 <= horizon <= 15:
        raise ValidationError("horizon must be between 1 and 15", horizon=horizon)
    growth = merged["revenue_growth"]
    if isinstance(growth, (int, float)):
        growth = [float(growth)] * horizon
    if not isinstance(growth, list) or not growth:
        raise ValidationError("revenue_growth must be a number or non-empty list")
    values = [_number(item, "revenue_growth") for item in growth]
    if len(values) != horizon:
        raise ValidationError("revenue_growth must contain one rate per forecast year",
                              horizon=horizon, received=len(values))
    if any(item <= -1 for item in values):
        raise ValidationError("revenue growth must be greater than -100%")
    merged["horizon"] = horizon
    merged["revenue_growth"] = values
    for key in ("operating_margin", "tax_rate", "da_pct_revenue", "capex_pct_revenue",
                "nwc_pct_revenue", "wacc", "terminal_growth", "exit_multiple", "cash",
                "debt", "shares"):
        merged[key] = _number(merged[key], key)
    if not 0 <= merged["tax_rate"] <= 1:
        raise ValidationError("tax_rate must be between 0 and 1")
    if not 0.001 <= merged["wacc"] <= 1:
        raise ValidationError("wacc must be between 0.1% and 100%")
    if merged["terminal_growth"] >= merged["wacc"]:
        raise ValidationError("terminal growth must be below WACC", wacc=merged["wacc"],
                              terminal_growth=merged["terminal_growth"])
    if merged["shares"] <= 0:
        raise ValidationError("share count must be positive")
    if merged["terminal_method"] not in {"gordon_growth", "exit_multiple"}:
        raise ValidationError("terminal_method must be gordon_growth or exit_multiple")
    if merged["convention"] not in {"end_year", "mid_year"}:
        raise ValidationError("convention must be end_year or mid_year")
    if merged["exit_multiple"] <= 0:
        raise ValidationError("exit_multiple must be positive")
    if "revenue" in supplied:
        merged["revenue"] = supplied["revenue"]
    if "provenance" in supplied:
        merged["provenance"] = supplied["provenance"]
    return merged


def build_dcf_spec(assumptions: dict[str, Any], *, name: str = "Unlevered DCF",
                   as_of: str | None = None, mode: str = "public_available",
                   evidence_ids: list[str] | None = None) -> dict[str, Any]:
    a = _normalise(assumptions)
    nodes: list[dict[str, Any]] = []

    def node(node_id: str, op: str, inputs: list[str] | None = None, **params: Any) -> None:
        nodes.append({"id": node_id, "op": op, "inputs": inputs or [], "params": params})

    node("revenue_forecast", "forecast_series", ["revenue", "revenue_growth"],
         periods=a["horizon"])
    node("ebit", "mul", ["revenue_forecast", "operating_margin"])
    node("tax", "mul", ["ebit", "tax_rate"])
    node("nopat", "sub", ["ebit", "tax"])
    node("da", "mul", ["revenue_forecast", "da_pct"])
    node("capex", "mul", ["revenue_forecast", "capex_pct"])
    node("nwc", "mul", ["revenue_forecast", "nwc_pct"])
    node("nwc_base", "mul", ["revenue", "nwc_pct"])
    node("nwc_change", "delta", ["nwc_base", "nwc"])
    node("fcff_a", "add", ["nopat", "da"])
    node("fcff_b", "sub", ["fcff_a", "capex"])
    node("fcff", "sub", ["fcff_b", "nwc_change"])
    node("pv_explicit", "npv", ["fcff", "wacc"], convention=a["convention"])
    node("terminal_value", "terminal_value", ["fcff", "wacc", "terminal_growth"],
         method=a["terminal_method"], multiple=a["exit_multiple"])
    node("pv_terminal", "discount", ["terminal_value", "wacc"],
         periods=a["horizon"], convention=a["convention"])
    node("enterprise_value", "add", ["pv_explicit", "pv_terminal"])
    node("equity_bridge_cash", "add", ["enterprise_value", "cash"])
    node("equity_value", "sub", ["equity_bridge_cash", "debt"])
    node("value_per_share", "div", ["equity_value", "shares"])

    return {
        "schema_version": "atlas.model.v1",
        "name": name,
        "version": "1.0.0",
        "interface": "graph",
        "as_of": as_of,
        "mode": mode,
        "inputs": [
            {"name": "revenue", "type": "Money[USD]", "required": True},
            {"name": "revenue_growth", "type": "Series[Rate]", "required": True},
            {"name": "operating_margin", "type": "Ratio", "required": True},
            {"name": "tax_rate", "type": "Ratio", "required": True},
            {"name": "da_pct", "type": "Ratio", "required": True},
            {"name": "capex_pct", "type": "Ratio", "required": True},
            {"name": "nwc_pct", "type": "Ratio", "required": True},
            {"name": "wacc", "type": "Rate[annual]", "required": True},
            {"name": "terminal_growth", "type": "Rate[annual]", "required": True},
            {"name": "cash", "type": "Money[USD]", "required": True},
            {"name": "debt", "type": "Money[USD]", "required": True},
            {"name": "shares", "type": "Shares", "required": True},
        ],
        "nodes": nodes,
        "outputs": {
            "value_per_share": "value_per_share",
            "equity_value": "equity_value",
            "enterprise_value": "enterprise_value",
            "pv_explicit": "pv_explicit",
            "pv_terminal": "pv_terminal",
            "terminal_value": "terminal_value",
            "fcff": "fcff",
            "revenue_forecast": "revenue_forecast",
        },
        "evidence_ids": list(evidence_ids or []),
        "assumptions": [
            {"key": key, "value": a[key], "kind": "assumption"}
            for key in ("wacc", "terminal_growth", "operating_margin", "tax_rate",
                        "da_pct_revenue", "capex_pct_revenue", "nwc_pct_revenue",
                        "terminal_method", "convention")
        ],
    }


def _inputs(assumptions: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    revenue = assumptions.get("revenue", metrics.get("revenue"))
    if revenue is None:
        raise MissingDataError(
            "reported revenue is unavailable; Atlas will not invent a base revenue",
            issuer=metrics.get("issuer", {}).get("issuer_id"),
        )
    return {
        "revenue": revenue,
        "revenue_growth": assumptions["revenue_growth"],
        "operating_margin": assumptions["operating_margin"],
        "tax_rate": assumptions["tax_rate"],
        "da_pct": assumptions["da_pct_revenue"],
        "capex_pct": assumptions["capex_pct_revenue"],
        "nwc_pct": assumptions["nwc_pct_revenue"],
        "wacc": assumptions["wacc"],
        "terminal_growth": assumptions["terminal_growth"],
        "cash": assumptions.get("cash", 0),
        "debt": assumptions.get("debt", 0),
        "shares": assumptions["shares"],
    }


def defaults_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Derive editable defaults from evidenced history, labelling every assumption."""
    values = metrics.get("metrics", {})
    revenue = values.get("revenue", {}).get("value")
    if revenue is None:
        raise MissingDataError("reported revenue is required to seed the valuation")
    margin = values.get("operating_margin", {}).get("value")
    growth = values.get("revenue_growth", {}).get("value")
    capex = values.get("capex", {}).get("value")
    cash = values.get("cash_and_equivalents", {}).get("value")
    debt = values.get("total_debt", {}).get("value")
    shares = values.get("shares_outstanding", {}).get("value")
    shares_provenance: dict[str, Any] | None = None
    if not shares:
        net_income = values.get("net_income", {}).get("value")
        eps = values.get("eps_diluted", {}).get("value")
        if net_income and eps and eps > 0:
            shares = float(net_income) / float(eps)
            shares_provenance = {
                "value": shares,
                "kind": "derived_estimate",
                "formula": "net_income / eps_diluted (implied weighted diluted shares)",
                "evidence_ids": sorted(set(
                    values.get("net_income", {}).get("evidence_ids", [])
                    + values.get("eps_diluted", {}).get("evidence_ids", [])
                )),
                "period_end": values.get("net_income", {}).get("period_end"),
                "note": "reported share count is unavailable; this is an evidenced derivation, not a reported count",
            }
        else:
            raise MissingDataError(
                "reported or derivable share count is required; Atlas will not assume one share",
            )
    growth_rate = max(-0.2, min(float(growth) if growth is not None else 0.05, 0.3))
    base = _normalise({
        "revenue_growth": [growth_rate] * 5,
        "operating_margin": float(margin) if margin is not None else 0.15,
        "capex_pct_revenue": abs(float(capex) / float(revenue)) if capex and revenue else 0.05,
        "cash": float(cash or 0),
        "debt": float(debt or 0),
        "shares": float(shares),
    })
    base["revenue"] = float(revenue)
    base["provenance"] = {
        key: {
            "value": values[key].get("value"),
            "kind": values[key].get("kind"),
            "evidence_ids": values[key].get("evidence_ids", []),
            "formula": values[key].get("formula"),
            "period_end": values[key].get("period_end"),
        }
        for key in ("revenue", "operating_margin", "revenue_growth", "capex",
                    "cash_and_equivalents", "total_debt", "shares_outstanding")
        if key in values
    }
    if shares_provenance is not None:
        base["provenance"]["shares_outstanding"] = shares_provenance
    return base


def _audit(metrics: dict[str, Any], assumptions: dict[str, Any], result: dict[str, Any],
           evidence_ids: list[str]) -> dict[str, Any]:
    provenance = assumptions.get("provenance", {})
    return {
        "evidence_ids": evidence_ids,
        "observed_inputs": provenance,
        "assumptions": [
            {"key": key, "value": assumptions[key], "source": "user assumption",
             "note": "not an observed market fact"}
            for key in ("wacc", "terminal_growth", "operating_margin", "tax_rate",
                        "da_pct_revenue", "capex_pct_revenue", "nwc_pct_revenue",
                        "terminal_method", "convention")
        ],
        "formula": "FCFF = NOPAT + D&A − capex − ΔNWC; EV = PV(FCFF) + PV(terminal); equity = EV + cash − debt",
        "calculation_version": result["manifest"]["compiler_version"],
        "operator_versions": result["manifest"]["operator_versions"],
        "as_of": result["manifest"]["as_of"],
        "trace": result["trace"],
        "xray": f"/api/evidence/{evidence_ids[0]}" if evidence_ids else None,
        "limitations": [
            "D&A, tax, working-capital and WACC inputs default to explicit assumptions when not reported.",
            "The terminal value uses the final forecast FCFF, not an EBITDA multiple, for the Gordon method.",
            "This is an unlevered FCFF valuation; it is not a free-cash-flow-to-equity model.",
        ],
    }


def run_dcf(
    db: Database,
    issuer_identifier: str,
    assumptions: dict[str, Any] | None = None,
    *,
    as_of: str | None = None,
    mode: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    issuer = read_models.resolve_company(db, issuer_identifier)
    metrics = get_issuer_metrics(db, issuer["issuer_id"], as_of=as_of, mode=mode)
    defaults = defaults_from_metrics(metrics)
    merged = dict(defaults)
    merged.update(assumptions or {})
    normalised = _normalise(merged)
    normalised["revenue"] = float(merged["revenue"])
    normalised["provenance"] = defaults.get("provenance", {})
    evidence_ids = sorted({
        item for value in normalised["provenance"].values()
        for item in value.get("evidence_ids", [])
    })
    spec = build_dcf_spec(
        normalised, name=f"DCF · {issuer['legal_name']}", as_of=as_of,
        mode=mode or "public_available", evidence_ids=evidence_ids,
    )
    model = compile_model(spec)
    engine = ExecutionEngine(db, use_cache=True)
    result = engine.execute(model, _inputs(normalised, metrics), persist=persist)
    result.update({
        "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
        "valuation_schema": VALUATION_SCHEMA,
        "model_spec": spec,
        "model": model.to_dict(),
        "assumptions": normalised,
        "audit": _audit(metrics, normalised, result, evidence_ids),
        "data_status": {
            "period_end": metrics.get("period_end"),
            "price_as_of": metrics.get("price_as_of"),
            "price": metrics.get("price"),
            "price_source": metrics.get("price_source"),
        },
    })
    return result


def _solve_price(db: Database, issuer: str, assumptions: dict[str, Any], variable: str,
                 value: float) -> float:
    changed = dict(assumptions)
    if variable == "terminal_growth":
        changed["terminal_growth"] = value
    elif variable == "operating_margin":
        changed["operating_margin"] = value
    elif variable == "revenue_growth":
        changed["revenue_growth"] = [value] * int(changed["horizon"])
    elif variable == "wacc":
        changed["wacc"] = value
    else:
        raise ValidationError("unsupported reverse-DCF variable", variable=variable)
    result = run_dcf(db, issuer, changed, persist=False)
    return float(result["outputs"]["value_per_share"])


def reverse_dcf(
    db: Database,
    issuer_identifier: str,
    target_price: float,
    *,
    variable: str = "terminal_growth",
    bounds: tuple[float, float] | None = None,
    assumptions: dict[str, Any] | None = None,
    as_of: str | None = None,
    mode: str | None = None,
    tolerance: float = 1e-4,
) -> dict[str, Any]:
    target = _number(target_price, "target_price")
    if target <= 0:
        raise ValidationError("target price must be positive")
    result = run_dcf(db, issuer_identifier, assumptions, as_of=as_of, mode=mode, persist=False)
    base = result["assumptions"]
    if bounds is None:
        bounds = {
            "terminal_growth": (-0.05, min(base["wacc"] - 0.001, 0.08)),
            "operating_margin": (-0.2, 0.8),
            "revenue_growth": (-0.3, 0.5),
            "wacc": (0.03, 0.4),
        }.get(variable)
    if bounds is None:
        raise ValidationError("bounds are required for this variable")
    low, high = float(bounds[0]), float(bounds[1])
    if low >= high:
        raise ValidationError("reverse-DCF bounds must be increasing")

    def f(value: float) -> float:
        return _solve_price(db, issuer_identifier, base, variable, value) - target

    samples = [low + (high - low) * index / 20 for index in range(21)]
    values = [f(value) for value in samples]
    sign_changes = [
        (samples[i], samples[i + 1])
        for i in range(20)
        if values[i] == 0 or values[i + 1] == 0 or values[i] * values[i + 1] < 0
    ]
    if not sign_changes:
        return {
            "solved": False,
            "reason": "no solution in the supplied bounds",
            "variable": variable,
            "target_price": target,
            "bounds": [low, high],
            "base_value_per_share": result["outputs"]["value_per_share"],
            "note": "The model is not forced to a market-implied answer when none exists.",
        }
    if len(sign_changes) > 1:
        return {
            "solved": False,
            "reason": "multiple sign changes detected; the inverse problem is not uniquely identified",
            "variable": variable,
            "target_price": target,
            "bounds": [low, high],
            "candidates": [list(item) for item in sign_changes],
        }
    left, right = sign_changes[0]
    f_left = f(left)
    iterations = 0
    while iterations < 100:
        mid = (left + right) / 2
        f_mid = f(mid)
        if abs(f_mid) < tolerance or (right - left) < 1e-9:
            break
        if f_left * f_mid <= 0:
            right = mid
        else:
            left, f_left = mid, f_mid
        iterations += 1
    solved_value = (left + right) / 2
    solved_price = _solve_price(db, issuer_identifier, base, variable, solved_value)
    return {
        "solved": True,
        "variable": variable,
        "implied_value": solved_value,
        "target_price": target,
        "solved_price": solved_price,
        "residual": solved_price - target,
        "iterations": iterations,
        "bounds": [float(bounds[0]), float(bounds[1])],
        "base_value_per_share": result["outputs"]["value_per_share"],
        "method": "bounded bisection with a 21-point sign-change scan",
        "note": "A market-implied value is one point on an underdetermined inverse problem, not management guidance.",
        "audit": result["audit"],
    }


def scenarios(
    db: Database,
    issuer_identifier: str,
    assumptions: dict[str, Any] | None = None,
    *,
    as_of: str | None = None,
    mode: str | None = None,
    custom: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = run_dcf(db, issuer_identifier, assumptions, as_of=as_of, mode=mode, persist=False)
    base_assumptions = base["assumptions"]
    overrides = {
        "base": {},
        "bull": {"revenue_growth": [min(0.5, rate + 0.03) for rate in base_assumptions["revenue_growth"]],
                 "operating_margin": min(0.8, base_assumptions["operating_margin"] + 0.02),
                 "wacc": max(0.03, base_assumptions["wacc"] - 0.01)},
        "bear": {"revenue_growth": [max(-0.5, rate - 0.03) for rate in base_assumptions["revenue_growth"]],
                 "operating_margin": max(-0.2, base_assumptions["operating_margin"] - 0.02),
                 "wacc": min(0.4, base_assumptions["wacc"] + 0.01)},
    }
    if custom:
        overrides.update(custom)
    results = {}
    for name, override in overrides.items():
        changed = dict(base_assumptions)
        changed.update(override)
        try:
            run = run_dcf(db, issuer_identifier, changed, as_of=as_of, mode=mode, persist=False)
            results[name] = {
                "value_per_share": run["outputs"]["value_per_share"],
                "equity_value": run["outputs"]["equity_value"],
                "enterprise_value": run["outputs"]["enterprise_value"],
                "assumptions": {key: changed[key] for key in (
                    "revenue_growth", "operating_margin", "wacc", "terminal_growth")},
                "delta_vs_base": run["outputs"]["value_per_share"] - base["outputs"]["value_per_share"],
            }
        except ValidationError as exc:
            results[name] = {"error": exc.message, "context": exc.context}
    return {
        "issuer": base["issuer"], "scenarios": results, "base": "base",
        "schema": VALUATION_SCHEMA,
        "note": "Scenario overrides branch from one shared model definition.",
    }


def sensitivity(
    db: Database,
    issuer_identifier: str,
    *,
    wacc_values: list[float] | None = None,
    growth_values: list[float] | None = None,
    assumptions: dict[str, Any] | None = None,
    as_of: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    base = run_dcf(db, issuer_identifier, assumptions, as_of=as_of, mode=mode, persist=False)
    a = base["assumptions"]
    waccs = wacc_values or [round(a["wacc"] + delta, 4) for delta in (-0.02, -0.01, 0, 0.01, 0.02)]
    growths = growth_values or [round(a["terminal_growth"] + delta, 4) for delta in (-0.01, -0.005, 0, 0.005, 0.01)]
    if len(waccs) > 7 or len(growths) > 7:
        raise ValidationError("sensitivity grids are limited to 7×7")
    if any(w <= g for w in waccs for g in growths):
        raise ValidationError("every WACC must exceed terminal growth")
    matrix = []
    for wacc in waccs:
        row = []
        for growth in growths:
            changed = dict(a)
            changed["wacc"] = wacc
            changed["terminal_growth"] = growth
            run = run_dcf(db, issuer_identifier, changed, as_of=as_of, mode=mode, persist=False)
            row.append(run["outputs"]["value_per_share"])
        matrix.append(row)
    return {
        "issuer": base["issuer"],
        "wacc_values": waccs,
        "growth_values": growths,
        "matrix": matrix,
        "row_labels": [f"{value:.2%}" for value in waccs],
        "column_labels": [f"{value:.2%}" for value in growths],
        "units": "USD per share",
        "schema": VALUATION_SCHEMA,
        "note": "Each cell is a complete compiler execution of the same canonical model.",
    }
