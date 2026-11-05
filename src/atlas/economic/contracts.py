"""Typed contracts for the Phase 7 economic intelligence layer.

These are deliberately small, inspectable documents. They do not execute code and
they keep observation, inference, hypothesis, causal estimate and counterfactual
status separate. The Temporal Evidence Kernel remains authoritative for time; the
economic tables extend its discipline to nonfinancial observations.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..core.errors import ValidationError
from ..core.temporal import iso, parse_iso, utcnow

ECONOMIC_SCHEMA = "atlas.economic.intelligence.v1"
GRAPH_SCHEMA = "atlas.economic.graph.v1"
CLAIM_SCHEMA = "atlas.economic.claim.v1"
SCENARIO_SCHEMA = "atlas.economic.scenario.v1"
FORECAST_SCHEMA = "atlas.forecast.v1"

DATA_CLASSES = (
    "observed",
    "historically_reconstructed",
    "point_in_time_verified",
    "synthetic",
    "hypothetical",
)
EPISTEMIC_STATUSES = (
    "observed",
    "inferred",
    "hypothesized",
    "estimated_causal_effect",
    "counterfactual",
    "unresolved",
)
CAUSAL_STATUSES = ("not_applicable", "association", "identified", "not_identified")
EDGE_STATUSES = ("observed", "inferred", "hypothetical")
EVENT_STATUSES = ("observed", "provisional", "revised", "hypothetical", "cancelled")
ENTITY_TYPES = (
    "company",
    "legal_entity",
    "security",
    "facility",
    "geographic_region",
    "economic_sector",
    "infrastructure_asset",
    "commodity",
    "economic_indicator",
    "government_body",
    "event",
    "contract",
    "dataset",
    "research_hypothesis",
)
RELATIONSHIP_TYPES = (
    "operates",
    "operates_facility",
    "facility_located_in",
    "station_located_in",
    "geographic_context_for",
    "describes_geography",
    "observes_geography",
    "consumes_commodity",
    "supports_indicator",
    "is_affected_by",
    "tested_by",
    "cites",
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{digest(parts)[:20].upper()}"


def _timestamp(value: str, field: str) -> str:
    try:
        return iso(parse_iso(value))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"{field} must be an ISO timestamp", field=field, value=value) from exc


def validate_observation(document: dict[str, Any]) -> dict[str, Any]:
    required = (
        "series_id", "source_id", "period_start", "period_end", "observed_at",
        "availability_precision", "availability_basis", "value_numeric", "unit",
        "quality", "data_class",
    )
    missing = [key for key in required if key not in document]
    if missing:
        raise ValidationError("economic observation is missing fields", fields=missing)
    if document["data_class"] not in DATA_CLASSES:
        raise ValidationError("unknown economic data class", data_class=document["data_class"])
    if document["availability_precision"] not in {"exact", "date", "unknown"}:
        raise ValidationError("invalid availability precision",
                              precision=document["availability_precision"])
    if document["availability_precision"] == "unknown" and document.get("availability_time"):
        raise ValidationError("unknown availability must not carry a timestamp")
    if document["availability_precision"] != "unknown" and not document.get("availability_time"):
        raise ValidationError("evidenced availability requires a timestamp")
    try:
        start = parse_iso(document["period_start"])
        end = parse_iso(document["period_end"])
        observed = parse_iso(document["observed_at"])
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("economic observation has invalid time fields") from exc
    if start > end:
        raise ValidationError("economic period start is after its end")
    if observed < end:
        raise ValidationError("observation cannot be retrieved before its period ends")
    if not isinstance(document["value_numeric"], (int, float)):
        raise ValidationError("economic observation value must be numeric")
    return document


def validate_claim(document: dict[str, Any]) -> dict[str, Any]:
    required = ("subject_key", "predicate", "observed_at", "claimed_at", "source_id",
                "epistemic_status", "causal_status")
    missing = [key for key in required if key not in document]
    if missing:
        raise ValidationError("economic claim is missing fields", fields=missing)
    if document["epistemic_status"] not in EPISTEMIC_STATUSES:
        raise ValidationError("unknown epistemic status", status=document["epistemic_status"])
    if document["causal_status"] not in CAUSAL_STATUSES:
        raise ValidationError("unknown causal status", status=document["causal_status"])
    if document["epistemic_status"] == "estimated_causal_effect" and document["causal_status"] != "identified":
        raise ValidationError("a causal effect claim requires an identified design")
    if document["epistemic_status"] == "hypothesized" and document["causal_status"] == "identified":
        raise ValidationError("a hypothesis cannot carry an identified causal status")
    if document.get("value_numeric") is None and not str(document.get("value_text") or "").strip():
        raise ValidationError("a claim needs a numeric or textual assertion")
    _timestamp(document["observed_at"], "observed_at")
    _timestamp(document["claimed_at"], "claimed_at")
    return document


def validate_edge(document: dict[str, Any]) -> dict[str, Any]:
    for field in ("from_entity_id", "to_entity_id", "relationship_type", "source_id",
                  "confidence", "epistemic_status"):
        if field not in document:
            raise ValidationError("economic edge is missing fields", field=field)
    if document["epistemic_status"] not in EDGE_STATUSES:
        raise ValidationError("unknown edge epistemic status", status=document["epistemic_status"])
    if not 0 <= float(document["confidence"]) <= 1:
        raise ValidationError("edge confidence must be in [0,1]")
    if document["from_entity_id"] == document["to_entity_id"]:
        raise ValidationError("an edge cannot connect an entity to itself")
    return document


def claim_document(
    *, subject_key: str, predicate: str, source_id: str, observed_at: str,
    epistemic_status: str, causal_status: str = "not_applicable",
    value_numeric: float | None = None, value_text: str | None = None,
    unit: str | None = None, observation_id: str | None = None,
    claimed_at: str | None = None, review_status: str = "accepted",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = {
        "schema": CLAIM_SCHEMA,
        "subject_key": subject_key,
        "predicate": predicate,
        "source_id": source_id,
        "observed_at": observed_at,
        "claimed_at": claimed_at or iso(utcnow()),
        "epistemic_status": epistemic_status,
        "causal_status": causal_status,
        "value_numeric": value_numeric,
        "value_text": value_text,
        "unit": unit,
        "observation_id": observation_id,
        "review_status": review_status,
        "metadata": metadata or {},
    }
    return validate_claim(document)


def continuous_forecast_document(
    *, as_of: str, horizon_days: int, unit: str, model_id: str,
    point: float, lower: float, upper: float, data_class: str,
    assumptions: list[str], limitations: list[str],
) -> dict[str, Any]:
    if not 0 < horizon_days <= 3650:
        raise ValidationError("forecast horizon is out of range")
    if lower > point or point > upper:
        raise ValidationError("forecast interval does not contain the point forecast")
    if data_class not in DATA_CLASSES:
        raise ValidationError("unknown forecast data class", data_class=data_class)
    _timestamp(as_of, "as_of")
    return {
        "schema": FORECAST_SCHEMA,
        "kind": "continuous",
        "as_of": iso(parse_iso(as_of)),
        "horizon_days": horizon_days,
        "unit": unit,
        "point": point,
        "interval": {"lower": lower, "upper": upper, "level": 0.90,
                     "type": "parameter_and_residual_approximation"},
        "model_id": model_id,
        "data_class": data_class,
        "assumptions": assumptions,
        "limitations": limitations,
        "decision_rule": None,
        "note": "A forecast is not a trading signal; a separately declared decision rule is required.",
    }


def scenario_document(
    *, name: str, shock_c: float, reference_date: str, reference_temperature_c: float,
    demand_change_fraction: float, demand_change_interval: list[float],
    financial: dict[str, Any], assumptions: list[str], limitations: list[str],
) -> dict[str, Any]:
    if not assumptions:
        raise ValidationError("a scenario must declare at least one assumption")
    if demand_change_interval[0] > demand_change_interval[1]:
        raise ValidationError("scenario interval is reversed")
    return {
        "schema": SCENARIO_SCHEMA,
        "name": name,
        "reference_date": reference_date,
        "reference_temperature_c": reference_temperature_c,
        "shock_c": shock_c,
        "demand": {
            "change_fraction": demand_change_fraction,
            "interval_90": demand_change_interval,
            "interval_type": "parameter_uncertainty_only",
        },
        "financial": financial,
        "assumptions": assumptions,
        "limitations": limitations,
        "created_at": iso(utcnow()),
    }
