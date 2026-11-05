"""Economic evidence fabric for the Phase 7 flagship study.

The committed fixture is a derived daily panel from public EIA-930 and NCEI
GHCN-Daily archives. The raw archives stay in ignored ``var/phase7/raw``. This
module registers their provenance, inserts observations with an explicit retrieval
availability proxy, and loads a panel under either point-in-time mode.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from ..core.errors import MissingDataError, UnknownEntity, ValidationError
from ..core.temporal import iso, iso_date, parse_iso, utcnow
from ..storage.db import Database
from .contracts import (
    DATA_CLASSES,
    ECONOMIC_SCHEMA,
    GRAPH_SCHEMA,
    stable_id,
    validate_observation,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "fixtures" / "phase7"
FIXTURE_PATH = FIXTURE_DIR / "weather_demand_2023.csv"
MANIFEST_PATH = FIXTURE_DIR / "source_manifest.json"

SERIES_DEMAND = "ECON-EIA-ERCO-DEMAND-D"
SERIES_DFW = "ECON-NOAA-DFW-TMAX-D"
SERIES_REDBIRD = "ECON-NOAA-REDBIRD-TMAX-D"

ENTITY_ERCO = "EENT-REGION-ERCO"
ENTITY_DALLAS = "EENT-REGION-DALLAS"
ENTITY_DFW_STATION = "EENT-STATION-DFW"
ENTITY_REDBIRD_STATION = "EENT-STATION-REDBIRD"
ENTITY_DEMAND = "EENT-INDICATOR-DEMAND"
ENTITY_TEMP = "EENT-INDICATOR-TEMP"
ENTITY_EIA = "EENT-DATASET-EIA930"
ENTITY_NOAA = "EENT-DATASET-GHCN"
ENTITY_ELECTRICITY = "EENT-COMMODITY-ELECTRICITY"
ENTITY_HYPOTHESIS = "EENT-HYPOTHESIS-WEATHER-DEMAND"
ENTITY_COMPANY = "EENT-COMPANY-HYPOTHETICAL-MFG"
ENTITY_FACILITY = "EENT-FACILITY-HYPOTHETICAL-TX"

DATA_LIMITATIONS = [
    "The source files are current bulk archives, not as-issued historical vintages.",
    "Availability is a retrieval proxy; no historical publication timestamp is claimed.",
    "A point weather station is not an area-weighted temperature for all of ERCOT.",
    "The relationship is a same-day association unless a defensible identification design is supplied.",
    "Company electricity consumption, contract structure, price and revenue are explicit hypothetical assumptions.",
]


def _manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise MissingDataError(
            "Phase 7 fixture manifest is missing",
            path=str(MANIFEST_PATH),
            fix="run scripts/build_phase7_fixtures.py after scripts/fetch_phase7_data.py",
        )
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _fixture_rows() -> list[dict[str, Any]]:
    if not FIXTURE_PATH.exists():
        raise MissingDataError(
            "Phase 7 weather-demand fixture is missing",
            path=str(FIXTURE_PATH),
            fix="run scripts/build_phase7_fixtures.py",
        )
    rows: list[dict[str, Any]] = []
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = {"date": raw["date"]}
            for key in (
                "demand_mean_mw", "demand_peak_mw", "demand_min_mw", "demand_energy_mwh",
                "temperature_mean_c", "temperature_max_c", "temperature_min_c",
                "cooling_degree_day_18c", "heating_degree_day_18c", "precipitation_mm",
                "comparison_temperature_max_c", "comparison_temperature_min_c",
            ):
                row[key] = None if raw[key] == "" else float(raw[key])
            row["hours_observed"] = int(raw["hours_observed"])
            rows.append(row)
    _validate_rows(rows)
    return rows


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 365:
        raise ValidationError("Phase 7 fixture must contain 365 daily rows", rows=len(rows))
    dates = [row["date"] for row in rows]
    if len(set(dates)) != len(dates):
        raise ValidationError("Phase 7 fixture contains duplicate dates")
    if dates != sorted(dates):
        raise ValidationError("Phase 7 fixture is not in chronological order")
    for row in rows:
        if row["demand_mean_mw"] <= 0 or row["demand_peak_mw"] <= 0:
            raise ValidationError("nonpositive demand in fixture", date=row["date"])
        if not 23 <= row["hours_observed"] <= 25:
            raise ValidationError("invalid hourly coverage in fixture", date=row["date"],
                                  hours=row["hours_observed"])
        if row["demand_peak_mw"] < row["demand_mean_mw"] or row["demand_mean_mw"] < row["demand_min_mw"]:
            raise ValidationError("demand high/low ordering is invalid", date=row["date"])
        if row["temperature_max_c"] < row["temperature_min_c"]:
            raise ValidationError("temperature high/low ordering is invalid", date=row["date"])
        if row["temperature_max_c"] is None or row["temperature_min_c"] is None:
            raise ValidationError("missing primary temperature observation", date=row["date"])


def fixture_summary() -> dict[str, Any]:
    manifest = _manifest()
    rows = _fixture_rows()
    demand = [row["demand_mean_mw"] for row in rows]
    temps = [row["temperature_mean_c"] for row in rows]
    diffs = [abs(row["temperature_max_c"] - row["comparison_temperature_max_c"]) for row in rows]
    return {
        "rows": len(rows),
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "demand_mean_mw": {"min": min(demand), "max": max(demand), "mean": sum(demand) / len(demand)},
        "temperature_mean_c": {"min": min(temps), "max": max(temps), "mean": sum(temps) / len(temps)},
        "station_max_temperature_difference_c": {
            "mean": sum(diffs) / len(diffs), "max": max(diffs),
            "days_over_2c": sum(value > 2.0 for value in diffs),
        },
        "panel_sha256": manifest["panel"]["sha256"],
        "sources": manifest["sources"],
        "limitations": DATA_LIMITATIONS,
    }


def _ensure_source(db: Database, *, source_id: str, name: str, kind: str,
                   homepage: str | None, licence: str, redistribution: str,
                   notes: str) -> None:
    db.execute(
        "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO NOTHING",
        (source_id, name, kind, homepage, licence, redistribution, notes, iso(utcnow())),
    )


def bootstrap(db: Database) -> dict[str, Any]:
    """Idempotently register the committed public fixture as economic evidence."""
    manifest = _manifest()
    rows = _fixture_rows()
    now = iso(utcnow())
    retrieved_at = iso(parse_iso(manifest["created_at"]))
    # A retrieval instant is not a publication date. It is stored as an exact
    # retrieval proxy with an explicit basis, so a historical as-of query before
    # that instant does not see the current archive.
    availability = retrieved_at
    source_meta = {item["source_id"]: item for item in manifest["sources"]}

    _ensure_source(
        db, source_id="eia-930", name="U.S. Energy Information Administration Form EIA-930",
        kind="public_economic", homepage="https://www.eia.gov/electricity/gridmonitor/",
        licence="U.S. Government public domain", redistribution="permitted",
        notes="Hourly balancing-authority operations; current bulk archive.",
    )
    _ensure_source(
        db, source_id="noaa-ghcn", name="NOAA NCEI GHCN-Daily",
        kind="public_economic", homepage="https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily",
        licence="U.S. Government public domain", redistribution="permitted",
        notes="Daily station observations; current quality-controlled archive.",
    )
    _ensure_source(
        db, source_id="atlas-assumption", name="Atlas scenario assumption",
        kind="model_assumption", homepage=None, licence="Internal research assumption",
        redistribution="not_applicable",
        notes="Used only for explicitly hypothetical exposures, never for observed evidence.",
    )

    series = [
        {
            "series_id": SERIES_DEMAND, "source_id": "eia-930", "dataset": "EIA-930",
            "name": "ERCOT daily mean electricity demand", "geography_code": "ERCO",
            "geography_name": "Electric Reliability Council of Texas balancing authority",
            "frequency": "daily", "unit": "MW", "data_class": "observed",
            "rights": "U.S. Government public domain", "redistribution": "permitted",
            "source_url": "https://www.eia.gov/electricity/gridmonitor/",
            "vintage_policy": "current archive retained; historical as-issued vintage not available",
            "publication_policy": "retrieval proxy only; operator corrections may postdate the operating day",
            "metadata": {
                "transform": "hourly Demand (MW) mean/peak/min and summed MWh by local operating day",
                "region_code": "ERCO", "hours_per_year": 8760,
                "publication_caveat": "Data Date is local; DST days have 23/25 hours.",
            },
        },
        {
            "series_id": SERIES_DFW, "source_id": "noaa-ghcn", "dataset": "GHCN-Daily",
            "name": "Dallas/Fort Worth daily maximum temperature", "geography_code": "DALLAS-DFW",
            "geography_name": "Dallas/Fort Worth International Airport, Texas",
            "frequency": "daily", "unit": "degC", "data_class": "observed",
            "rights": "U.S. Government public domain", "redistribution": "permitted",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00013960.csv",
            "vintage_policy": "current archive retained; historical as-issued vintage not available",
            "publication_policy": "retrieval proxy only; no historical forecast or publication vintage",
            "metadata": {"station": "USW00013960", "station_name": "DALLAS FAA AIRPORT, TX US",
                         "latitude": 32.83839, "longitude": -96.83583, "elevation_m": 147.6,
                         "units": "tenths of degrees Celsius converted to Celsius; no infilling"},
        },
        {
            "series_id": SERIES_REDBIRD, "source_id": "noaa-ghcn", "dataset": "GHCN-Daily",
            "name": "Dallas Redbird daily maximum temperature", "geography_code": "DALLAS-REDBIRD",
            "geography_name": "Dallas Redbird Airport, Texas", "frequency": "daily",
            "unit": "degC", "data_class": "observed",
            "rights": "U.S. Government public domain", "redistribution": "permitted",
            "source_url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00003971.csv",
            "vintage_policy": "current archive retained; historical as-issued vintage not available",
            "publication_policy": "retrieval proxy only; no historical forecast or publication vintage",
            "metadata": {"station": "USW00003971", "station_name": "DALLAS REDBIRD AIRPORT, TX US",
                         "latitude": 32.67816, "longitude": -96.86771, "elevation_m": 200.4,
                         "units": "tenths of degrees Celsius converted to Celsius; no infilling"},
        },
    ]
    for item in series:
        db.execute(
            "INSERT INTO economic_series (series_id, source_id, dataset, name, geography_code, "
            "geography_name, frequency, unit, data_class, rights, redistribution, source_url, "
            "vintage_policy, publication_policy, metadata_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO NOTHING",
            (item["series_id"], item["source_id"], item["dataset"], item["name"],
             item["geography_code"], item["geography_name"], item["frequency"], item["unit"],
             item["data_class"], item["rights"], item["redistribution"], item["source_url"],
             item["vintage_policy"], item["publication_policy"],
             json.dumps({**item["metadata"], "fixture_sha256": manifest["panel"]["sha256"]},
                        sort_keys=True), now),
        )

    vintage = f"{manifest['created_at'][:10]}-current-archive"
    observation_ids: dict[str, str] = {}
    for row in rows:
        day = row["date"]
        demand_meta = {
            "peak_mw": row["demand_peak_mw"], "min_mw": row["demand_min_mw"],
            "energy_mwh": row["demand_energy_mwh"], "hours_observed": row["hours_observed"],
            "adjustment": "none; submitted EIA-930 demand",
        }
        temp_meta = {
            "max_c": row["temperature_max_c"], "min_c": row["temperature_min_c"],
            "cdd_18c": row["cooling_degree_day_18c"], "hdd_18c": row["heating_degree_day_18c"],
            "precip_mm": row["precipitation_mm"], "station": "USW00013960",
        }
        comparison_meta = {
            "max_c": row["comparison_temperature_max_c"], "min_c": row["comparison_temperature_min_c"],
            "station": "USW00003971", "role": "independent comparison",
        }
        for series_id, value, unit, metadata, quality in (
            (SERIES_DEMAND, row["demand_mean_mw"], "MW", demand_meta, "verified_source_archive"),
            (SERIES_DFW, row["temperature_mean_c"], "degC", temp_meta, "verified_source_archive"),
            (SERIES_REDBIRD, (row["comparison_temperature_max_c"] + row["comparison_temperature_min_c"]) / 2,
             "degC", comparison_meta, "verified_source_archive"),
        ):
            payload = {
                "series_id": series_id, "date": day, "value": value, "unit": unit,
                "vintage": vintage, "revision_seq": 1,
            }
            observation_id = stable_id("EOBS", payload)
            observation_ids[f"{series_id}:{day}"] = observation_id
            document = {
                "series_id": series_id, "source_id": "eia-930" if series_id == SERIES_DEMAND else "noaa-ghcn",
                "period_start": day, "period_end": day, "observed_at": retrieved_at,
                "availability_time": availability, "availability_precision": "exact",
                "availability_basis": "archive retrieval instant; not a historical publication vintage",
                "value_numeric": value, "unit": unit, "quality": quality,
                "data_class": "observed",
            }
            validate_observation(document)
            db.execute(
                "INSERT INTO economic_observation (observation_id, series_id, source_id, period_start, "
                "period_end, published_at, availability_time, availability_precision, availability_basis, "
                "observed_at, vintage, revision_seq, supersedes, value_numeric, unit, quality, data_class, "
                "raw_ref, content_hash, metadata_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(observation_id) DO NOTHING",
                (observation_id, series_id, document["source_id"], day, day, None, availability,
                 "exact", document["availability_basis"], retrieved_at, vintage, 1, None,
                 float(value), unit, quality, "observed", manifest["panel"]["sha256"],
                 __import__("atlas.economic.contracts", fromlist=["digest"]).digest(
                     {**payload, **metadata}), json.dumps(metadata, sort_keys=True), now),
            )

    _bootstrap_graph(db, rows, observation_ids, retrieved_at, availability, now)
    claims = _bootstrap_claims(db, rows, observation_ids, retrieved_at, now)
    conflicts = detect_conflicts(db)
    counts = {
        "series": db.row_count("economic_series"),
        "observations": db.row_count("economic_observation"),
        "entities": db.row_count("economic_entity"),
        "edges": db.row_count("economic_edge"),
        "claims": db.row_count("economic_claim"),
        "conflicts": db.row_count("economic_conflict"),
        "events": db.row_count("economic_event"),
    }
    return {
        "schema": "atlas.economic.bootstrap.v1",
        "fixture": manifest,
        "counts": counts,
        "conflicts": conflicts,
        "claims": claims,
    }


def _node(db: Database, *, entity_id: str, entity_type: str, name: str, canonical_key: str,
          geography_code: str | None, data_class: str, status: str, source_id: str,
          metadata: dict[str, Any], now: str) -> None:
    db.execute(
        "INSERT INTO economic_entity (entity_id, entity_type, name, canonical_key, geography_code, "
        "data_class, status, source_id, valid_from, valid_to, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id) DO NOTHING",
        (entity_id, entity_type, name, canonical_key, geography_code, data_class, status,
         source_id, "2023-01-01", None, json.dumps(metadata, sort_keys=True), now),
    )


def _edge(db: Database, *, from_id: str, to_id: str, relationship_type: str, source_id: str,
          observation_id: str | None, claim_id: str | None, confidence: float, status: str,
          metadata: dict[str, Any], now: str) -> None:
    edge_id = stable_id("EEDG", from_id, to_id, relationship_type, status)
    db.execute(
        "INSERT INTO economic_edge (edge_id, from_entity_id, to_entity_id, relationship_type, "
        "source_id, observation_id, claim_id, valid_from, valid_to, confidence, epistemic_status, "
        "geography_code, metadata_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(edge_id) DO NOTHING",
        (edge_id, from_id, to_id, relationship_type, source_id, observation_id, claim_id,
         "2023-01-01", None, confidence, status, None,
         json.dumps(metadata, sort_keys=True), now),
    )


def _bootstrap_graph(db: Database, rows: list[dict[str, Any]], observation_ids: dict[str, str],
                     retrieved_at: str, availability: str, now: str) -> None:
    day = "2023-08-15"
    demand_obs = observation_ids[f"{SERIES_DEMAND}:{day}"]
    temp_obs = observation_ids[f"{SERIES_DFW}:{day}"]
    nodes = [
        (ENTITY_ERCO, "geographic_region", "ERCOT balancing authority", "ERCOT", "ERCO",
         "observed", "eia-930", {"source": "EIA-930 Region=TEX", "boundary_precision": "balancing authority"}),
        (ENTITY_DALLAS, "geographic_region", "Dallas/Fort Worth", "DALLAS-DFW", "DALLAS-DFW",
         "inferred", "noaa-ghcn", {"scope": "metro context, not a legal boundary"}),
        (ENTITY_DFW_STATION, "infrastructure_asset", "Dallas/Fort Worth International Airport station",
         "USW00013960", "DALLAS-DFW", "observed", "noaa-ghcn",
         {"station_id": "USW00013960", "coordinates": [32.83839, -96.83583]}),
        (ENTITY_REDBIRD_STATION, "infrastructure_asset", "Dallas Redbird Airport station",
         "USW00003971", "DALLAS-REDBIRD", "observed", "noaa-ghcn",
         {"station_id": "USW00003971", "coordinates": [32.67816, -96.86771]}),
        (ENTITY_DEMAND, "economic_indicator", "ERCOT daily mean demand", SERIES_DEMAND, "ERCO",
         "observed", "eia-930", {"unit": "MW", "frequency": "daily"}),
        (ENTITY_TEMP, "economic_indicator", "Dallas daily temperature", SERIES_DFW, "DALLAS-DFW",
         "observed", "noaa-ghcn", {"unit": "degC", "frequency": "daily"}),
        (ENTITY_EIA, "dataset", "EIA-930 public hourly grid archive", "eia-930", "US",
         "observed", "eia-930", {"rights": "public domain"}),
        (ENTITY_NOAA, "dataset", "NOAA GHCN-Daily public station archive", "noaa-ghcn", "US",
         "observed", "noaa-ghcn", {"rights": "public domain"}),
        (ENTITY_ELECTRICITY, "commodity", "Electricity", "ELECTRICITY", "ERCO", "observed",
         "eia-930", {"unit": "MWh"}),
        (ENTITY_HYPOTHESIS, "research_hypothesis", "Weather affects ERCOT electricity demand",
         "WEATHER-DEMAND-ERCOT", "ERCO", "hypothesized", "atlas-assumption",
         {"statement": "Higher cooling demand raises daily mean electricity demand.",
          "causal_status": "not_identified"}),
        (ENTITY_COMPANY, "company", "Hypothetical Texas manufacturer", "HYPOTHETICAL-MFG",
         "ERCO", "hypothetical", "atlas-assumption",
         {"note": "No real company is represented. This is an explicit scenario exposure."}),
        (ENTITY_FACILITY, "facility", "Hypothetical ERCOT manufacturing facility",
         "HYPOTHETICAL-FACILITY", "ERCO", "hypothetical", "atlas-assumption",
         {"note": "Location and load are assumptions, not observed facility data."}),
    ]
    for entity_id, kind, name, key, geography, status, source, metadata in nodes:
        _node(db, entity_id=entity_id, entity_type=kind, name=name, canonical_key=key,
              geography_code=geography, data_class=status, status=status, source_id=source,
              metadata=metadata, now=now)
    edges = [
        (ENTITY_DEMAND, ENTITY_ERCO, "describes_geography", "eia-930", demand_obs, None, 0.98,
         "observed", {"note": "EIA region code ERCO"}),
        (ENTITY_TEMP, ENTITY_DALLAS, "describes_geography", "noaa-ghcn", temp_obs, None, 0.95,
         "observed", {"note": "station point observation"}),
        (ENTITY_DFW_STATION, ENTITY_DALLAS, "station_located_in", "noaa-ghcn", temp_obs, None, 0.99,
         "observed", {"station": "USW00013960"}),
        (ENTITY_REDBIRD_STATION, ENTITY_DALLAS, "station_located_in", "noaa-ghcn", None, None, 0.99,
         "observed", {"station": "USW00003971"}),
        (ENTITY_DALLAS, ENTITY_ERCO, "geographic_context_for", "noaa-ghcn", None, None, 0.65,
         "inferred", {"note": "Analyst geographic mapping; Dallas is inside the ERCOT study context, "
                              "but a point station is not an area-weighted ERCOT temperature."}),
        (ENTITY_DEMAND, ENTITY_TEMP, "is_affected_by", "atlas-assumption", None, None, 0.35,
         "hypothetical", {"note": "Research hypothesis, not an identified causal edge."}),
        (ENTITY_EIA, ENTITY_DEMAND, "supports_indicator", "eia-930", demand_obs, None, 1.0,
         "observed", {}),
        (ENTITY_NOAA, ENTITY_TEMP, "supports_indicator", "noaa-ghcn", temp_obs, None, 1.0,
         "observed", {}),
        (ENTITY_COMPANY, ENTITY_FACILITY, "operates_facility", "atlas-assumption", None, None, 1.0,
         "hypothetical", {"note": "scenario assumption"}),
        (ENTITY_FACILITY, ENTITY_ERCO, "facility_located_in", "atlas-assumption", None, None, 1.0,
         "hypothetical", {"note": "scenario assumption"}),
        (ENTITY_FACILITY, ENTITY_ELECTRICITY, "consumes_commodity", "atlas-assumption", None, None, 1.0,
         "hypothetical", {"note": "scenario assumption"}),
        (ENTITY_HYPOTHESIS, ENTITY_DEMAND, "tested_by", "atlas-assumption", None, None, 0.35,
         "hypothetical", {"note": "Hypothesis is tested by the weather-demand analysis."}),
    ]
    for from_id, to_id, rel, source, obs, claim, confidence, status, metadata in edges:
        _edge(db, from_id=from_id, to_id=to_id, relationship_type=rel, source_id=source,
              observation_id=obs, claim_id=claim, confidence=confidence, status=status,
              metadata=metadata, now=now)


def _insert_claim(db: Database, document: dict[str, Any], now: str) -> str:
    claim_id = stable_id("ECLM", document)
    db.execute(
        "INSERT INTO economic_claim (claim_id, subject_key, predicate, value_numeric, value_text, "
        "unit, observed_at, claimed_at, source_id, observation_id, epistemic_status, causal_status, "
        "review_status, supersedes, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(claim_id) DO NOTHING",
        (claim_id, document["subject_key"], document["predicate"], document.get("value_numeric"),
         document.get("value_text"), document.get("unit"), document["observed_at"],
         document["claimed_at"], document["source_id"], document.get("observation_id"),
         document["epistemic_status"], document["causal_status"], document["review_status"],
         None, json.dumps(document.get("metadata", {}), sort_keys=True), now),
    )
    return claim_id


def _bootstrap_claims(db: Database, rows: list[dict[str, Any]], observation_ids: dict[str, str],
                      retrieved_at: str, now: str) -> dict[str, Any]:
    from .contracts import claim_document

    conflict_day = max(
        rows,
        key=lambda row: abs(row["temperature_max_c"] - row["comparison_temperature_max_c"]),
    )
    day = conflict_day["date"]
    subject = f"dallas_area.daily_max_temperature.{day}"
    primary = _insert_claim(db, claim_document(
        subject_key=subject, predicate="daily_max_temperature_c", source_id="noaa-ghcn",
        observed_at=day, claimed_at=retrieved_at, epistemic_status="observed",
        value_numeric=conflict_day["temperature_max_c"], unit="degC",
        observation_id=observation_ids[f"{SERIES_DFW}:{day}"],
        metadata={"station": "USW00013960", "station_name": "Dallas/Fort Worth International Airport",
                  "scope": "point observation", "data_class": "observed"},
    ), now)
    comparison = _insert_claim(db, claim_document(
        subject_key=subject, predicate="daily_max_temperature_c", source_id="noaa-ghcn",
        observed_at=day, claimed_at=retrieved_at, epistemic_status="observed",
        value_numeric=conflict_day["comparison_temperature_max_c"], unit="degC",
        observation_id=observation_ids[f"{SERIES_REDBIRD}:{day}"],
        metadata={"station": "USW00003971", "station_name": "Dallas Redbird Airport",
                  "scope": "point observation", "data_class": "observed"},
    ), now)
    demand = _insert_claim(db, claim_document(
        subject_key=f"ercot.daily_mean_demand.{day}", predicate="daily_mean_demand_mw",
        source_id="eia-930", observed_at=day, claimed_at=retrieved_at,
        epistemic_status="observed", value_numeric=conflict_day["demand_mean_mw"], unit="MW",
        observation_id=observation_ids[f"{SERIES_DEMAND}:{day}"],
        metadata={"region": "ERCO", "aggregation": "mean of hourly MW"},
    ), now)
    hypothesis = _insert_claim(db, claim_document(
        subject_key="hypothesis.weather_to_ercot_demand",
        predicate="temperature_raises_demand", source_id="atlas-assumption",
        observed_at="2023-01-01", claimed_at=retrieved_at, epistemic_status="hypothesized",
        causal_status="not_identified",
        value_text="Higher Dallas-area temperature is associated with higher daily ERCOT demand.",
        metadata={"identification": "not supplied", "note": "Weather is not randomly assigned."},
    ), now)
    # Event record is a provenance anchor, not a market contract.
    db.execute(
        "INSERT INTO economic_event (event_id, event_type, label, geography_code, started_at, "
        "ended_at, observed_at, published_at, status, data_class, source_id, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING",
        (stable_id("EEVT", "temperature-disagreement", day, primary, comparison),
         "measurement_disagreement", f"Two Dallas stations disagree on {day} maximum temperature",
         "DALLAS-DFW", day, day, retrieved_at, None, "observed", "observed", "noaa-ghcn",
         json.dumps({"claims": [primary, comparison], "difference_c": abs(
             conflict_day["temperature_max_c"] - conflict_day["comparison_temperature_max_c"])},
             sort_keys=True), now),
    )
    return {"primary_temperature_claim": primary, "comparison_temperature_claim": comparison,
            "demand_claim": demand, "hypothesis_claim": hypothesis, "conflict_date": day,
            "primary_temperature_c": conflict_day["temperature_max_c"],
            "comparison_temperature_c": conflict_day["comparison_temperature_max_c"]}


def detect_conflicts(db: Database) -> list[dict[str, Any]]:
    """Detect same-subject, same-unit numerical disagreement without choosing a winner."""
    now = iso(utcnow())
    rows = db.query(
        "SELECT claim_id, subject_key, predicate, value_numeric, unit, source_id, claimed_at, "
        "epistemic_status, observation_id FROM economic_claim WHERE value_numeric IS NOT NULL "
        "ORDER BY subject_key, claimed_at, claim_id"
    )
    grouped: dict[tuple[str, str | None], list[Any]] = defaultdict(list)
    for row in rows:
        grouped[(row["subject_key"], row["unit"])].append(row)
    found = []
    for (subject, unit), items in grouped.items():
        values = {round(float(item["value_numeric"]), 9) for item in items}
        if len(values) < 2:
            continue
        items = sorted(items, key=lambda item: (item["claimed_at"], item["claim_id"]))
        claim_ids = [item["claim_id"] for item in items]
        existing = db.query_one(
            "SELECT conflict_id, status, resolution FROM economic_conflict WHERE subject_key = ? "
            "ORDER BY detected_at DESC LIMIT 1", (subject,)
        )
        if existing:
            found.append({"conflict_id": existing["conflict_id"], "subject_key": subject,
                          "claim_ids": claim_ids, "status": existing["status"],
                          "resolution": existing["resolution"]})
            continue
        confidence = min(0.95, 0.55 + 0.05 * len(items))
        metadata = {
            "unit": unit, "values": [item["value_numeric"] for item in items],
            "sources": [item["source_id"] for item in items],
            "observation_ids": [item["observation_id"] for item in items],
            "interpretation": "station representativeness; not a single truth adjudication",
            "dependent_research_stale": True,
        }
        conflict_id = stable_id("ECNF", subject, claim_ids)
        db.execute(
            "INSERT INTO economic_conflict (conflict_id, subject_key, claim_ids_json, status, reason, "
            "resolution, detected_at, metadata_json) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (conflict_id, subject, json.dumps(claim_ids), "unresolved",
             "two observed station measurements disagree for the same metro-area subject",
             None, now, json.dumps(metadata, sort_keys=True)),
        )
        found.append({"conflict_id": conflict_id, "subject_key": subject,
                      "claim_ids": claim_ids, "status": "unresolved", "resolution": None,
                      "values": [item["value_numeric"] for item in items],
                      "sources": [item["source_id"] for item in items],
                      "confidence": confidence,
                      "note": "Both source records are preserved. No automatic winner is selected."})
    return found


def load_panel(db: Database, *, as_of: str | None = None, mode: str = "public_available",
               start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Load complete daily rows from economic observations under an explicit as-of mode."""
    if mode not in {"public_available", "atlas_ingested"}:
        raise ValidationError("mode must be public_available or atlas_ingested")
    cutoff = iso(parse_iso(as_of)) if as_of else iso(utcnow())
    time_column = "availability_time" if mode == "public_available" else "observed_at"
    rows = db.query(
        "SELECT o.observation_id, o.series_id, o.period_start, o.period_end, o.published_at, "
        "o.availability_time, o.availability_precision, o.availability_basis, o.observed_at, "
        "o.value_numeric, o.unit, o.quality, o.data_class, o.revision_seq, o.metadata_json "
        "FROM economic_observation o WHERE o.period_start >= ? AND o.period_end <= ? "
        "AND o.period_end <= ? ORDER BY o.period_start, o.series_id, o.revision_seq",
        (start or "1900-01-01", end or "2100-01-01", cutoff[:10]),
    )
    selected: dict[tuple[str, str], Any] = {}
    excluded = 0
    unknown = 0
    for row in rows:
        if row["availability_precision"] == "unknown":
            unknown += 1
            if mode == "public_available":
                excluded += 1
                continue
        if mode == "public_available":
            if not row["availability_time"] or row["availability_time"] > cutoff:
                excluded += 1
                continue
        elif row["observed_at"] > cutoff:
            excluded += 1
            continue
        key = (row["series_id"], row["period_start"])
        current = selected.get(key)
        if current is None or int(row["revision_seq"]) > int(current["revision_seq"]):
            selected[key] = row

    by_date: dict[str, dict[str, Any]] = defaultdict(dict)
    for (series_id, day), row in selected.items():
        metadata = json.loads(row["metadata_json"])
        if series_id == SERIES_DEMAND:
            by_date[day].update({
                "demand_mean_mw": row["value_numeric"],
                "demand_peak_mw": metadata.get("peak_mw"),
                "demand_min_mw": metadata.get("min_mw"),
                "demand_energy_mwh": metadata.get("energy_mwh"),
                "hours_observed": metadata.get("hours_observed"),
                "demand_observation_id": row["observation_id"],
            })
        elif series_id == SERIES_DFW:
            by_date[day].update({
                "temperature_mean_c": row["value_numeric"],
                "temperature_max_c": metadata.get("max_c"),
                "temperature_min_c": metadata.get("min_c"),
                "cooling_degree_day_18c": metadata.get("cdd_18c"),
                "heating_degree_day_18c": metadata.get("hdd_18c"),
                "precipitation_mm": metadata.get("precip_mm"),
                "temperature_observation_id": row["observation_id"],
            })
        elif series_id == SERIES_REDBIRD:
            by_date[day].update({
                "comparison_temperature_mean_c": row["value_numeric"],
                "comparison_temperature_max_c": metadata.get("max_c"),
                "comparison_temperature_min_c": metadata.get("min_c"),
            })
    required = {
        "demand_mean_mw", "temperature_mean_c", "temperature_max_c", "temperature_min_c",
        "cooling_degree_day_18c", "heating_degree_day_18c", "demand_peak_mw",
    }
    complete = []
    partial = []
    for day in sorted(by_date):
        row = {"date": day, **by_date[day]}
        if required <= set(row) and all(row[key] is not None for key in required):
            complete.append(row)
        else:
            partial.append(day)
    if not complete:
        raise MissingDataError(
            "no complete economic observations are available under this as-of query",
            as_of=cutoff, mode=mode, excluded=excluded,
            fix="choose an as_of after the archive retrieval date or import a validated vintage",
        )
    anomalies = []
    for row in complete:
        if row["demand_mean_mw"] <= 0:
            anomalies.append({"date": row["date"], "issue": "nonpositive demand"})
        if row["temperature_max_c"] < row["temperature_min_c"]:
            anomalies.append({"date": row["date"], "issue": "temperature high/low inversion"})
        if row["demand_peak_mw"] < row["demand_mean_mw"]:
            anomalies.append({"date": row["date"], "issue": "peak below mean"})
    return {
        "schema": "atlas.economic.panel.v1",
        "as_of": cutoff, "mode": mode,
        "start": complete[0]["date"], "end": complete[-1]["date"],
        "rows": complete,
        "row_count": len(complete),
        "partial_dates": partial,
        "quality": {
            "complete_rows": len(complete), "partial_rows": len(partial),
            "anomalies": anomalies[-20:], "anomaly_count": len(anomalies),
            "status": "ok" if not anomalies and not partial else "warning",
        },
        "completeness": {
            "status": "complete_for_query" if not partial and not excluded else "partial",
            "excluded_not_yet_available": excluded,
            "excluded_unknown_availability": unknown,
            "declared_limitations": DATA_LIMITATIONS,
        },
        "series": [dict(row) for row in db.query(
            "SELECT series_id, source_id, name, geography_code, geography_name, frequency, unit, "
            "data_class, rights, redistribution, vintage_policy, publication_policy "
            "FROM economic_series ORDER BY series_id"
        )],
    }


def graph(db: Database, *, as_of: str | None = None, entity_id: str | None = None,
          depth: int = 2) -> dict[str, Any]:
    cutoff = iso(parse_iso(as_of)) if as_of else None
    entities = [dict(row) for row in db.query(
        "SELECT entity_id, entity_type, name, canonical_key, geography_code, data_class, status, "
        "source_id, valid_from, valid_to, metadata_json FROM economic_entity "
        "WHERE (? IS NULL OR valid_from IS NULL OR valid_from <= ?) "
        "ORDER BY entity_type, name", (cutoff, cutoff)
    )]
    for item in entities:
        item["metadata"] = json.loads(item.pop("metadata_json"))
    edges = [dict(row) for row in db.query(
        "SELECT e.edge_id, e.from_entity_id, e.to_entity_id, e.relationship_type, e.source_id, "
        "e.observation_id, e.claim_id, e.valid_from, e.valid_to, e.confidence, "
        "e.epistemic_status, e.geography_code, e.metadata_json, "
        "f.name AS from_name, t.name AS to_name, s.name AS source_name, "
        "s.licence AS rights, s.redistribution AS redistribution "
        "FROM economic_edge e JOIN economic_entity f ON f.entity_id = e.from_entity_id "
        "JOIN economic_entity t ON t.entity_id = e.to_entity_id "
        "JOIN source s ON s.source_id = e.source_id "
        "WHERE (? IS NULL OR e.valid_from IS NULL OR e.valid_from <= ?) "
        "ORDER BY e.epistemic_status, e.relationship_type", (cutoff, cutoff)
    )]
    for item in edges:
        item["metadata"] = json.loads(item.pop("metadata_json"))
        item["status"] = item["epistemic_status"]
        item["current_valid"] = item["valid_to"] is None
        item["provenance"] = (
            f"{item['source_name']} ({item['source_id']}); relationship asserted in "
            f"{item['valid_from']}"
        )
        item["source_evidence"] = (
            item["metadata"].get("note")
            or item["metadata"].get("evidence")
            or f"{item['relationship_type']} edge supplied by {item['source_name']}"
        )
    allowed = {item["entity_id"] for item in entities}
    if entity_id:
        if entity_id not in allowed:
            raise UnknownEntity("unknown economic entity", entity_id=entity_id)
        frontier = {entity_id}
        reachable = {entity_id}
        for _ in range(max(1, min(depth, 5))):
            next_frontier = set()
            for edge in edges:
                if edge["from_entity_id"] in frontier:
                    next_frontier.add(edge["to_entity_id"])
                if edge["to_entity_id"] in frontier:
                    next_frontier.add(edge["from_entity_id"])
            next_frontier -= reachable
            reachable |= next_frontier
            frontier = next_frontier
        entities = [item for item in entities if item["entity_id"] in reachable]
        edges = [item for item in edges
                 if item["from_entity_id"] in reachable and item["to_entity_id"] in reachable]
    claims = [dict(row) for row in db.query(
        "SELECT claim_id, subject_key, predicate, value_numeric, value_text, unit, observed_at, "
        "claimed_at, source_id, observation_id, epistemic_status, causal_status, review_status, "
        "metadata_json FROM economic_claim ORDER BY subject_key, claimed_at"
    )]
    for item in claims:
        item["metadata"] = json.loads(item.pop("metadata_json"))
    conflicts = list_conflicts(db)
    return {
        "schema": GRAPH_SCHEMA, "as_of": cutoff, "entities": entities, "edges": edges,
        "claims": claims, "conflicts": conflicts,
        "counts": {
            "entities": len(entities), "edges": len(edges), "claims": len(claims),
            "conflicts": len(conflicts),
            "observed_edges": sum(1 for item in edges if item["epistemic_status"] == "observed"),
            "hypothetical_edges": sum(1 for item in edges if item["epistemic_status"] == "hypothetical"),
        },
        "note": "Observed, inferred and hypothetical edges are never merged.",
    }


def list_conflicts(db: Database) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT conflict_id, subject_key, claim_ids_json, status, reason, resolution, detected_at, "
        "metadata_json FROM economic_conflict ORDER BY detected_at DESC, conflict_id"
    )
    result = []
    for row in rows:
        item = dict(row)
        item["claim_ids"] = json.loads(item.pop("claim_ids_json"))
        item["metadata"] = json.loads(item.pop("metadata_json"))
        result.append(item)
    return result


def catalog(db: Database) -> dict[str, Any]:
    manifest = _manifest()
    counts = {
        "series": db.row_count("economic_series"),
        "observations": db.row_count("economic_observation"),
        "entities": db.row_count("economic_entity"),
        "edges": db.row_count("economic_edge"),
        "claims": db.row_count("economic_claim"),
        "conflicts": db.row_count("economic_conflict"),
        "events": db.row_count("economic_event"),
        "analyses": db.row_count("economic_analysis"),
        "scenarios": db.row_count("economic_scenario"),
        "alerts": db.row_count("economic_alert"),
    }
    sources = [dict(row) for row in db.query(
        "SELECT source_id, name, kind, homepage, licence, redistribution, notes FROM source "
        "WHERE source_id IN ('eia-930','noaa-ghcn','atlas-assumption') ORDER BY source_id"
    )]
    series = [dict(row) for row in db.query(
        "SELECT series_id, source_id, dataset, name, geography_code, geography_name, frequency, "
        "unit, data_class, rights, redistribution, source_url, vintage_policy, publication_policy, "
        "metadata_json FROM economic_series ORDER BY series_id"
    )]
    for item in series:
        item["metadata"] = json.loads(item.pop("metadata_json"))
    return {
        "schema": ECONOMIC_SCHEMA,
        "panel_schema": "atlas.economic.panel.v1",
        "graph_schema": GRAPH_SCHEMA,
        "claim_schema": "atlas.economic.claim.v1",
        "scenario_schema": "atlas.economic.scenario.v1",
        "forecast_schema": "atlas.forecast.v1",
        "counts": counts,
        "sources": sources,
        "series": series,
        "fixture": manifest,
        "summary": fixture_summary() if counts["observations"] else None,
        "defaults": {
            "as_of": manifest["created_at"],
            "mode": "public_available",
            "region": "ERCO",
            "station": "USW00013960",
            "comparison_station": "USW00003971",
            "shock_c": 2.0,
            "annual_consumption_mwh": 50_000.0,
            "load_sensitivity": 0.5,
            "unhedged_fraction": 0.6,
            "power_price_usd_mwh": 65.0,
            "revenue_usd": 40_000_000.0,
            "tax_rate": 0.21,
        },
        "limitations": DATA_LIMITATIONS,
        "causal_policy": {
            "weather_demand": "association",
            "reason": "Weather is not randomly assigned; common drivers, measurement error and "
                      "simultaneity are not ruled out by this observational time-series design.",
            "identified_methods_available": ["two_by_two_difference_in_differences",
                                            "interrupted_time_series"],
        },
        "rights_note": "EIA and NOAA records are U.S. Government public-domain works. "
                       "Attribution and source URLs are preserved; raw bulk archives are not committed.",
    }


def source_ids() -> list[str]:
    return ["eia-930", "noaa-ghcn"]


def data_classes() -> list[str]:
    return list(DATA_CLASSES)
