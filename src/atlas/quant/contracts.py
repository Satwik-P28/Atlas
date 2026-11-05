"""Typed strategy and experiment contracts for Quant Lab.

A strategy is a declaration in the existing Universal Research Object system. Its signal
may be one of a small set of audited primitives or an ``atlas.model.v1`` model evaluated
against point-in-time features. No Python, SQL or arbitrary expressions are accepted.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from typing import Any

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, parse_iso
from ..fec.compiler import compile_model
from .features import normalise_features

STRATEGY_SCHEMA = "atlas.strategy.v1"
EXPERIMENT_SCHEMA = "atlas.quant.experiment.v1"
LAB_VERSION = "atlas.quant.lab.v1"
FREQUENCIES = ("daily", "weekly", "monthly")
SIGNAL_KINDS = ("buy_hold", "sma_cross", "momentum", "model", "learning_probability")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def strategy_fingerprint(spec: dict[str, Any]) -> str:
    payload = {"schema": STRATEGY_SCHEMA, "lab": LAB_VERSION, "spec": spec}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _finite_number(value: Any, field: str, *, minimum: float | None = None,
                   maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a finite number", value=value)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a finite number", value=value) from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ValidationError(f"{field} must be finite", value=value)
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} is below its minimum", field=field,
                              value=number, minimum=minimum)
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} is above its maximum", field=field,
                              value=number, maximum=maximum)
    return number


def validate_strategy(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValidationError("strategy specification must be an object")
    if spec.get("schema_version", STRATEGY_SCHEMA) != STRATEGY_SCHEMA:
        raise ValidationError("unsupported strategy schema", supported=STRATEGY_SCHEMA)
    name = str(spec.get("name", "")).strip()
    if not name:
        raise ValidationError("strategy name is required")
    version = str(spec.get("version", "1.0.0"))
    if not SEMVER.match(version):
        raise ValidationError("strategy version must be semver", version=version)
    universe = spec.get("universe")
    if not isinstance(universe, dict):
        raise ValidationError("strategy universe is required")
    instruments = universe.get("instruments")
    if not isinstance(instruments, list) or len(instruments) != 1:
        raise ValidationError(
            "this Lab release supports exactly one instrument per strategy",
            received=len(instruments) if isinstance(instruments, list) else None,
        )
    instrument = instruments[0]
    if not isinstance(instrument, dict):
        raise ValidationError("universe instrument must be an object")
    security_id = str(instrument.get("security_id", "")).strip()
    mic = str(instrument.get("mic", "")).strip().upper()
    if not security_id.startswith("SEC-"):
        raise ValidationError("instrument must use a stable Atlas security id", security_id=security_id)
    if not re.match(r"^[A-Z]{2,8}$", mic):
        raise ValidationError("instrument mic is invalid", mic=mic)
    features = normalise_features(spec.get("features") or [])
    signal = spec.get("signal")
    if not isinstance(signal, dict):
        raise ValidationError("strategy signal is required")
    kind = str(signal.get("kind", "")).strip()
    if kind not in SIGNAL_KINDS:
        raise ValidationError("unsupported strategy signal", kind=kind, supported=list(SIGNAL_KINDS))
    feature_names = {item["name"] for item in features}
    normalised_signal: dict[str, Any] = {"kind": kind}
    if kind in {"sma_cross", "momentum"}:
        normalised_signal["fast"] = int(_finite_number(signal.get("fast", 20), "signal.fast", minimum=2, maximum=500))
        if kind == "sma_cross":
            normalised_signal["slow"] = int(_finite_number(signal.get("slow", 100), "signal.slow", minimum=3, maximum=500))
            if normalised_signal["slow"] <= normalised_signal["fast"]:
                raise ValidationError("slow moving average must exceed fast", signal=normalised_signal)
        else:
            normalised_signal["threshold"] = _finite_number(signal.get("threshold", 0.0), "signal.threshold", minimum=-1, maximum=1)
    elif kind == "learning_probability":
        threshold = _finite_number(signal.get("threshold", 0.5), "signal.threshold",
                                   minimum=0.0, maximum=1.0)
        forecast_rows = signal.get("forecasts")
        if not isinstance(forecast_rows, list) or len(forecast_rows) < 1 or len(forecast_rows) > 4000:
            raise ValidationError("learning_probability requires 1-4000 frozen forecasts")
        seen: set[str] = set()
        normalised_forecasts: list[dict[str, Any]] = []
        for item in forecast_rows:
            if not isinstance(item, dict):
                raise ValidationError("learning forecast must be an object")
            day = iso_date(item.get("date"))
            if day in seen:
                raise ValidationError("learning forecast dates must be unique", date=day)
            seen.add(day)
            probability = _finite_number(item.get("probability"), "signal.forecasts.probability",
                                         minimum=0.0, maximum=1.0)
            normalised_forecasts.append({"date": day, "probability": probability})
        normalised_forecasts.sort(key=lambda item: item["date"])
        normalised_signal.update({
            "threshold": threshold,
            "forecasts": normalised_forecasts,
            "model_id": str(signal.get("model_id", "")),
            "forecast_run_id": str(signal.get("forecast_run_id", "")),
        })
    elif kind == "model":
        model_spec = signal.get("model_spec")
        if not isinstance(model_spec, dict):
            raise ValidationError("model signal requires an atlas.model.v1 model_spec")
        model = compile_model(model_spec)
        input_map = signal.get("input_map")
        if not isinstance(input_map, dict) or not input_map:
            raise ValidationError("model signal requires input_map from model inputs to feature names")
        for model_input, feature_name in input_map.items():
            if model_input not in model.inputs:
                raise ValidationError("input_map references an unknown model input", input=model_input)
            if feature_name not in feature_names:
                raise ValidationError("input_map references an unknown feature", feature=feature_name)
        output_name = str(signal.get("output", "signal"))
        if output_name not in model.outputs:
            raise ValidationError("model signal output is not declared", output=output_name,
                                  declared=sorted(model.outputs))
        normalised_signal.update({
            "model_spec": copy.deepcopy(model_spec),
            "input_map": {str(key): str(value) for key, value in input_map.items()},
            "output": output_name,
            "model_fingerprint": model.fingerprint,
        })
    execution = spec.get("execution") or {}
    if not isinstance(execution, dict):
        raise ValidationError("execution must be an object")
    commission = _finite_number(execution.get("commission_bps", 0), "execution.commission_bps",
                                minimum=0, maximum=500)
    slippage = _finite_number(execution.get("slippage_bps", 0), "execution.slippage_bps",
                              minimum=0, maximum=500)
    if execution.get("fill_at", "next_open") != "next_open":
        raise ValidationError("only next_open fills are supported", fill_at=execution.get("fill_at"))
    if execution.get("signal_at", "close") != "close":
        raise ValidationError("only close signals are supported", signal_at=execution.get("signal_at"))
    frequency = str(spec.get("decision_frequency", spec.get("rebalance", "daily")))
    if frequency not in FREQUENCIES:
        raise ValidationError("unsupported decision frequency", frequency=frequency,
                              supported=list(FREQUENCIES))
    constraints = spec.get("constraints") or {}
    if not isinstance(constraints, dict):
        raise ValidationError("constraints must be an object")
    if constraints.get("long_only", True) is not True:
        raise ValidationError("this Lab release supports long-only strategies")
    _finite_number(constraints.get("max_position", 1.0), "constraints.max_position",
                   minimum=0, maximum=1)
    initial_capital = _finite_number(spec.get("initial_capital", 100_000),
                                     "initial_capital", minimum=1, maximum=1_000_000_000)
    risk_free = _finite_number(spec.get("risk_free_rate", 0.0), "risk_free_rate",
                               minimum=-0.1, maximum=0.5)
    benchmark = spec.get("benchmark") or {"kind": "buy_hold"}
    if benchmark.get("kind", "buy_hold") != "buy_hold":
        raise ValidationError("only a buy-and-hold benchmark is supported")
    source_ids = spec.get("source_ids", [])
    if not isinstance(source_ids, list) or any(not isinstance(item, str) or not item for item in source_ids):
        raise ValidationError("source_ids must be a list of source ids")
    normalised = {
        "schema_version": STRATEGY_SCHEMA,
        "name": name,
        "version": version,
        "description": str(spec.get("description", "")),
        "universe": {"instruments": [{"security_id": security_id, "mic": mic}]},
        "features": features,
        "signal": normalised_signal,
        "decision_frequency": frequency,
        "rebalance": frequency,
        "execution": {"signal_at": "close", "fill_at": "next_open",
                      "commission_bps": commission, "slippage_bps": slippage},
        "benchmark": {"kind": "buy_hold"},
        "initial_capital": initial_capital,
        "constraints": {"long_only": True,
                        "max_position": float(constraints.get("max_position", 1.0))},
        "risk_free_rate": risk_free,
        "source_ids": sorted(set(source_ids)),
    }
    return normalised


def strategy_document(
    spec: dict[str, Any],
    *,
    as_of: str | date | None = None,
    mode: str = "atlas_ingested",
    status: str = "validated",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    normalised = validate_strategy(spec)
    when = iso(as_of) if as_of else iso(iso_date(spec.get("as_of", "2026-11-04")))
    return {
        "schema_version": "atlas.research_object.v1",
        "kind": "strategy",
        "name": normalised["name"],
        "version": normalised["version"],
        "status": status,
        "description": normalised["description"] or f"{normalised['name']} quantitative strategy",
        "as_of": when,
        "mode": mode,
        "evidence_ids": list(evidence_ids or []),
        "source_ids": normalised["source_ids"],
        "object_ids": [],
        "assumptions": ["Signals are evaluated at the session close and filled at the next session open."],
        "limitations": ["Single-instrument, long-only vertical slice."],
        "spec": normalised,
    }


def experiment_document(
    *,
    name: str,
    version: str,
    run: dict[str, Any],
    strategy_object_id: str,
    as_of: str,
    mode: str,
    source_ids: list[str],
) -> dict[str, Any]:
    metrics = run.get("metrics", {})
    spec = {
        "hypothesis": run.get("hypothesis") or "A transparent signal may outperform buy-and-hold after costs.",
        "method": "chronological event-driven simulation; signal at close; fill at next open",
        "metrics": metrics,
        "strategy_object_id": strategy_object_id,
        "run_id": run["run_id"],
        "experiment_schema": EXPERIMENT_SCHEMA,
        "period": run.get("period"),
        "baseline": run.get("benchmark", {}).get("metrics"),
        "credibility": run.get("credibility"),
        "accounting": run.get("reconciliation"),
        "validation": run.get("credibility", {}).get("validation"),
        "limitations": run.get("credibility", {}).get("limitations", []),
        "result_fingerprint": run.get("result_fingerprint"),
    }
    return {
        "schema_version": "atlas.research_object.v1",
        "kind": "experiment",
        "name": name,
        "version": version,
        "status": "validated",
        "description": "Persisted Quant Lab experiment with accounting and credibility diagnostics.",
        "as_of": iso(as_of),
        "mode": mode,
        "evidence_ids": [],
        "source_ids": sorted(set(source_ids)),
        "object_ids": [strategy_object_id],
        "assumptions": ["No live trading is represented by this experiment."],
        "limitations": spec["limitations"],
        "spec": spec,
    }


__all__ = [
    "EXPERIMENT_SCHEMA",
    "LAB_VERSION",
    "SIGNAL_KINDS",
    "STRATEGY_SCHEMA",
    "canonical_json",
    "experiment_document",
    "strategy_document",
    "strategy_fingerprint",
    "validate_strategy",
]
