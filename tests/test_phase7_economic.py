"""Independent Phase 7 validation on the real public weather/demand panel."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from atlas.core.errors import MissingDataError, ValidationError
from atlas.core.temporal import iso, utcnow
from atlas.economic import data
from atlas.economic.causal import (
    classify_design,
    interrupted_time_series,
    observational_policy,
    two_by_two_difference_in_differences,
)
from atlas.economic.service import EconomicService
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.api import create_app


@pytest.fixture()
def economic(db):
    service = EconomicService(db)
    service.bootstrap()
    return service


def _run(service: EconomicService) -> dict:
    return service.analyze(as_of=iso(utcnow()), persist=True)


def test_schema_9_observed_coverage_rights_and_retrieval_proxy(economic):
    db = economic.db
    assert LATEST_VERSION == 14
    assert db.schema_version() == 14
    tables = {row["name"] for row in db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert {"economic_series", "economic_observation", "economic_entity", "economic_edge",
            "economic_event", "economic_claim", "economic_conflict", "economic_analysis",
            "economic_scenario", "economic_dependency", "economic_alert"} <= tables
    assert db.scalar("SELECT COUNT(*) FROM economic_observation") == 1095
    assert db.scalar("SELECT COUNT(*) FROM economic_series") == 3

    panel = economic.panel(as_of=iso(utcnow()))
    assert panel["row_count"] == 365
    assert len(panel["rows"]) == 365
    assert panel["start"] == "2023-01-01"
    assert panel["end"] == "2023-12-31"
    assert panel["completeness"]["status"] == "complete_for_query"
    assert len(panel["series"]) == 3
    assert all(item["redistribution"] == "permitted" for item in panel["series"])
    assert all(item["rights"] == "U.S. Government public domain" for item in panel["series"])
    assert all(row["demand_mean_mw"] > 0 for row in panel["rows"])
    assert len({row["temperature_observation_id"] for row in panel["rows"]}) == 365

    with pytest.raises(MissingDataError):
        economic.panel(as_of="2023-12-31T23:59:59Z")

    summary = data.fixture_summary()
    assert summary["rows"] == 365
    assert summary["panel_sha256"] == (
        "987feb4933df29c119d5d2d9f1f5e49c1439fe9d10c33e899a78179e0963314f"
    )
    manifest = data._manifest()
    assert "public domain" in manifest["sources"][0]["rights"].lower()
    assert any("not an as-issued historical vintage" in item
               for item in manifest["sources"][0]["limitations"])


def test_graph_edges_have_provenance_and_hypothetical_company_is_not_observed(economic):
    graph = economic.graph()
    assert graph["counts"]["entities"] == 12
    assert graph["counts"]["edges"] == 12
    assert economic.db.scalar("SELECT COUNT(*) FROM economic_event") == 1
    companies = [node for node in graph["entities"] if node["entity_type"] == "company"]
    assert len(companies) == 1
    assert companies[0]["name"].startswith("Hypothetical")
    assert companies[0]["status"] == "hypothetical"
    for edge in graph["edges"]:
        assert edge["source_id"]
        assert edge["provenance"]
        assert edge["valid_from"]
        assert edge["status"] in {"observed", "inferred", "hypothetical"}
        assert edge["rights"]


def test_two_station_measurements_are_spatial_not_a_logical_contradiction(economic):
    payload = economic.conflicts()
    assert payload["count"] == 1
    assert payload["logical_conflict_count"] == 0
    assert payload["spatial_representativeness_count"] == 1
    conflict = payload["items"][0]
    assert conflict["status"] == "spatial_representativeness"
    assert "Different point stations" in conflict["resolution"]
    assert len(conflict["claims"]) == 2
    values = sorted(claim["value_numeric"] for claim in conflict["claims"])
    assert values == [32.8, 35.6]
    assert conflict["metadata"]["dependent_research_stale"] is True
    assert conflict["metadata"]["conflict_class"] == "spatial_representativeness"
    assert conflict["metadata"]["logical_contradiction"] is False
    assert conflict["metadata"]["stations"] == ["USW00003971", "USW00013960"]
    assert all(claim["source_id"] == "noaa-ghcn" for claim in conflict["claims"])
    assert all(claim["epistemic_status"] == "observed" for claim in conflict["claims"])
    assert len({claim["observation_id"] for claim in conflict["claims"]}) == 2


def test_chronological_split_untouched_test_and_association_label(economic):
    run = _run(economic)
    assert run["split"]["scheme"] == "chronological 70/15/15"
    assert run["split"]["train"] == {
        "start": "2023-01-01", "end": "2023-09-12", "rows": 255
    }
    assert run["split"]["validation"] == {
        "start": "2023-09-13", "end": "2023-11-06", "rows": 55
    }
    assert run["split"]["test"] == {
        "start": "2023-11-07", "end": "2023-12-31", "rows": 55
    }
    assert run["split"]["test_used_for_selection"] is False
    assert run["selection"]["selected_model"] in {"degree_day_linear", "degree_day_curvature",
                                                   "seasonal_baseline"}
    assert run["test"]["observations"] == 55
    assert run["baseline"]["observations"] == 55
    assert 0.0 < run["skill_vs_seasonal"] < 1.0
    assert run["test"]["r2"] < 0
    assert run["test"]["mean_error"] > 0
    assert run["forecast_status"] == "unstable"
    assert run["conclusion"] == "association_supported_forecast_unstable"
    assert run["causal_status"] == "not_identified"
    assert run["association_effect"]["interpretation"].startswith("conditional association")
    assert run["causal_claim"]["status"] == "association"
    assert not any("causal effect of temperature" in item.lower() for item in run["limitations"])

    findings = {item["finding_key"]: item for item in run["audit"]["findings"]}
    assert "test_regime_instability" in findings
    assert findings["test_regime_instability"]["severity"] == "warning"
    assert run["audit"]["counts"] == {"error": 0, "warning": 5, "info": 1}


def test_scenario_reproduces_fec_and_keeps_uncertainty_sources_separate(economic):
    run = _run(economic)
    scenario = economic.scenario(
        run["run_id"], shock_c=2.0, annual_consumption_mwh=50_000,
        load_sensitivity=0.5, unhedged_fraction=0.6, power_price_usd_mwh=65,
        revenue_usd=40_000_000, tax_rate=0.21, draws=2_000, seed=20261105,
    )
    reference = run["reference"]
    names = run["model"]["feature_names"]
    coefficients = np.asarray(run["model"]["coefficients"], dtype=float)

    def features(temp):
        cdd = max(temp - 18.0, 0.0)
        return {"cdd_18c": cdd, "hdd_18c": max(18.0 - temp, 0.0), "cdd_squared": cdd * cdd}

    def predict(temp):
        row = dict(reference["features"])
        row.update(features(temp))
        return float(coefficients @ np.asarray([1.0] + [row[name] for name in names]))

    base = predict(reference["temperature_mean_c"])
    shocked = predict(reference["temperature_mean_c"] + 2.0)
    expected_fraction = (shocked - base) / base
    expected_delta_mwh = 50_000 * expected_fraction * 0.5
    expected_cost = expected_delta_mwh * 0.6 * 65.0
    assert scenario["demand"]["change_fraction"] == pytest.approx(expected_fraction, rel=0, abs=1e-12)
    assert scenario["financial"]["delta_mwh"] == pytest.approx(expected_delta_mwh, abs=1e-9)
    assert scenario["financial"]["cost_delta_usd"] == pytest.approx(expected_cost, abs=1e-9)
    assert scenario["financial"]["after_tax_cost_usd"] == pytest.approx(expected_cost * 0.79, abs=1e-9)
    assert scenario["financial"]["margin_delta"] == pytest.approx(-expected_cost / 40_000_000, abs=1e-15)
    assert scenario["financial_compiler"]["compiler"] == "atlas.fec.compiler.v1"
    assert scenario["financial"]["compiler_run_id"].startswith("RUN-")

    uncertainty = scenario["uncertainty"]
    assert set(uncertainty) == {"observation", "parameter", "model_form", "relationship", "combined"}
    assert uncertainty["combined"] is None
    assert uncertainty["relationship"]["status"] == "not_identified"
    assert uncertainty["parameter"]["draws"] == 2_000
    low, high = scenario["demand"]["interval_90"]
    assert low < scenario["demand"]["change_fraction"] < high
    assert scenario["financial"]["cost_interval_90"][0] < scenario["financial"]["cost_delta_usd"]
    assert scenario["financial"]["cost_interval_90"][1] > scenario["financial"]["cost_delta_usd"]
    assert scenario["sensitivity"]["temperature"][0]["cost_delta_usd"] < 0

    with pytest.raises(ValidationError):
        economic.scenario(run["run_id"], shock_c=20)
    with pytest.raises(ValidationError):
        economic.scenario(run["run_id"], unhedged_fraction=1.2)


def test_revision_retains_history_and_invalidates_exact_dependencies(economic):
    run = _run(economic)
    observation = economic.db.query_one(
        "SELECT observation_id, value_numeric FROM economic_observation "
        "WHERE series_id = 'ECON-NOAA-DFW-TMAX-D' AND period_start = '2023-06-30'"
    )
    revision = economic.revise_observation(
        observation["observation_id"], value=99.0, reason="independent validation revision",
    )
    assert revision["old_observation_id"] == observation["observation_id"]
    assert revision["revision_seq"] == 2
    assert run["run_id"] in revision["stale_runs"]
    old = economic.db.query_one(
        "SELECT value_numeric, supersedes FROM economic_observation WHERE observation_id = ?",
        (observation["observation_id"],),
    )
    assert float(old["value_numeric"]) == observation["value_numeric"]
    revised = economic.db.query_one(
        "SELECT value_numeric, supersedes FROM economic_observation WHERE observation_id = ?",
        (revision["new_observation_id"],),
    )
    assert float(revised["value_numeric"]) == 99.0
    assert revised["supersedes"] == observation["observation_id"]
    reopened = economic.get_run(run["run_id"])
    assert reopened["stale"] is True
    assert reopened["stale_reason"].startswith("observation revised")
    alerts = economic.db.query(
        "SELECT alert_type, severity, status FROM economic_alert ORDER BY created_at"
    )
    assert any(row["alert_type"] == "observation_revised" for row in alerts)


def test_application_roundtrip_and_honest_replay_limits(economic):
    run = _run(economic)
    scenario = economic.scenario(run["run_id"])
    application = economic.save_application(
        run["run_id"], scenario_id=scenario["scenario_id"],
        name="Independent weather-energy application", purpose="validation roundtrip",
    )
    reopened = economic.objects.get(application["object_id"])
    assert reopened["kind"] == "application"
    assert reopened["document"]["spec"]["run_id"] == run["run_id"]
    assert reopened["document"]["spec"]["scenario_id"] == scenario["scenario_id"]
    assert reopened["document"]["spec"]["scenario"]["financial"]["cost_delta_usd"] == pytest.approx(
        scenario["financial"]["cost_delta_usd"]
    )
    assert set(reopened["document"]["spec"]["views"]) == {
        "evidence", "graph", "association", "scenario", "sentinel"
    }

    reproduced = economic.replay(run["run_id"], as_of=iso(utcnow()))
    assert reproduced["status"] == "reproduced"
    assert reproduced["reproduced"] is True
    assert reproduced["rows"] == 365
    assert reproduced["reproduced_fingerprint"] == run["fingerprint"]

    unavailable = economic.replay(run["run_id"], as_of="2023-12-31T23:59:59Z")
    assert unavailable["status"] == "insufficient_evidence"
    assert unavailable["reproduced"] is False
    assert "no evidenced historical vintage" in unavailable["note"]


def test_identified_causal_estimators_on_known_dgps():
    rows = []
    for treated in (0, 1):
        for post in (0, 1):
            base = 10.0 + 2.0 * treated + 4.0 * post + 1.5 * treated * post
            for replicate in range(30):
                rows.append({"treated": treated, "post": post,
                             "outcome": base + 0.01 * replicate})
    did = two_by_two_difference_in_differences(
        rows, outcome="outcome", treated="treated", post="post",
    )
    assert did["estimate"] == pytest.approx(1.5, abs=1e-12)
    assert did["causal_status"] == "identified"
    assert len(did["assumptions"]) == 4

    series = []
    for time in range(80):
        post = int(time >= 40)
        value = 3.0 + 0.2 * time + 6.0 * post + 0.3 * max(time - 40, 0)
        series.append({"time": time, "post": post, "outcome": value})
    its = interrupted_time_series(
        series, outcome="outcome", time="time", post="post", treatment_time=40,
    )
    assert its["level_change"] == pytest.approx(6.0, abs=1e-9)
    assert its["slope_change_per_unit_time"] == pytest.approx(0.3, abs=1e-9)
    assert its["causal_status"] == "identified"

    assert classify_design("observational_regression")["causal_status"] == "not_identified"
    assert observational_policy()["default"] == "association"
    with pytest.raises(ValidationError):
        classify_design("regression_with_controls")


def test_economic_api_workflow(tmp_path: Path):
    path = tmp_path / "phase7-api.db"
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    EconomicService(db).bootstrap()
    db.close()
    client = TestClient(create_app(path))

    health = client.get("/api/health").json()
    assert health["schema_version"] == 14
    assert health["economic_observations"] == 1095
    catalog = client.get("/api/economic/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["counts"]["observations"] == 1095
    source_ids = {item["source_id"] for item in catalog.json()["sources"]}
    assert {"eia-930", "noaa-ghcn"} <= source_ids
    assert len(source_ids) == 3  # two public sources plus the non-evidence assumption registry
    assert client.get("/api/economic/graph").json()["counts"]["edges"] == 12
    conflicts = client.get("/api/economic/conflicts").json()
    assert conflicts["count"] == 1
    assert conflicts["logical_conflict_count"] == 0
    assert conflicts["spatial_representativeness_count"] == 1

    analyzed = client.post("/api/economic/analyze", json={
        "as_of": iso(utcnow()), "mode": "public_available", "persist": True,
    })
    assert analyzed.status_code == 200, analyzed.text
    run = analyzed.json()
    assert run["causal_status"] == "not_identified"
    assert run["forecast_status"] == "unstable"
    scenarios = client.post(f"/api/economic/runs/{run['run_id']}/scenario", json={
        "shock_c": 2.0, "draws": 500,
    })
    assert scenarios.status_code == 200, scenarios.text
    scenario = scenarios.json()
    created = client.post("/api/economic/applications", json={
        "run_id": run["run_id"], "scenario_id": scenario["scenario_id"],
        "name": "API weather study", "purpose": "API roundtrip",
    })
    assert created.status_code == 201, created.text
    object_id = created.json()["object_id"]
    assert client.get(f"/api/research/objects/{object_id}").status_code == 200
    assert client.get("/api/economic/sentinel").status_code == 200
    assert client.get("/api/economic/benchmarks").status_code == 200
