"""Independent Phase 6 validation.

The tests use deterministic fixtures, not vendor bytes. They independently
recompute the Brier score, log loss and calibration error, and verify that the
target date is strictly after every feature date.
"""

from __future__ import annotations

import math
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.entities.master import SecurityMaster
from atlas.fec import compile_model
from atlas.fec.runtime import ExecutionEngine
from atlas.learning.audit import audit_result
from atlas.learning.data import PROVIDERS, load_panel, panel_from_series
from atlas.learning.discovery import discover
from atlas.learning.experiments import run_experiment
from atlas.learning.features import build_rows
from atlas.learning.metrics import (
    brier_score,
    calibration_table,
    expected_calibration_error,
    log_loss,
)
from atlas.learning.service import LearningService
from atlas.market.bars import Bar, BarStore
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.api import create_app


def _dates(count: int) -> list[str]:
    current = date(2022, 1, 3)
    result = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def synthetic_panel(count: int = 720) -> dict:
    dates = _dates(count)
    series = {}
    volumes = {}
    # A mild, deterministic nonlinear relation makes the test exercise learned
    # models without pretending the fixture is evidence of real predictive skill.
    for index, name in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE")):
        price = 100.0 + index * 17.0
        values, vol = [], []
        for session in range(count):
            previous_return = 0.0 if session < 2 else values[-1] / values[-2] - 1.0
            carry = 0.12 * previous_return + 0.0002 * math.sin(session / 11 + index)
            shock = 0.008 * math.sin(session * 1.7 + index * 2.1)
            price *= 1.0 + carry + shock
            values.append(price)
            vol.append(1_000_000 + 100_000 * math.sin(session / 9 + index))
        series[name] = values
        volumes[name] = vol
    return panel_from_series(series, volumes=volumes, dates=dates, name="Phase 6 independent fixture")


def _seed_database(path: Path) -> Database:
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    panel = synthetic_panel()
    for index, item in enumerate(panel["instruments"]):
        old_id = item["security_id"]
        issuer = master.register_issuer(legal_name=f"Fixture {old_id}", source_id="atlas-synthetic")
        security = master.ensure_security(issuer, class_designation=f"fixture class {index}",
                                          source_id="atlas-synthetic")
        master.ensure_listing(security, "XNAS", valid_from="2022-01-03", is_primary=True,
                              source_id="atlas-synthetic")
        panel["instruments"][index] = {**item, "security_id": security}
        panel["closes"][security] = panel["closes"].pop(old_id)
        panel["volumes"][security] = panel["volumes"].pop(old_id)
    bars = []
    for security, closes in panel["closes"].items():
        for day, close in zip(panel["dates"], closes):
            bars.append(Bar(
                security_id=security, mic="XNAS", ts_utc=f"{day}T21:00:00Z",
                open=Decimal(str(close)), high=Decimal(str(close * 1.01)),
                low=Decimal(str(close * 0.99)), close=Decimal(str(close)),
                volume=Decimal("1000000"), currency="USD", source_id="atlas-synthetic",
            ))
    BarStore(db).ingest(bars)
    return db


def test_schema_8_and_provider_rights():
    with tempfile.TemporaryDirectory() as directory:
        db = Database(Path(directory) / "phase6.db")
        assert db.migrate() == list(range(1, 15))
        assert LATEST_VERSION == 14
        tables = {row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"learning_run", "learning_attempt", "learning_model", "learning_forecast"} <= tables
        db.close()
    eodhd = next(item for item in PROVIDERS if item["provider"] == "eodhd-demo")
    assert eodhd["redistribution"] == "restricted"
    assert "not point-in-time" not in eodhd["rights"].lower()


def test_features_are_strictly_prior_to_targets():
    panel = synthetic_panel(420)
    built = build_rows(panel, features=["mom_5", "mom_20", "vol_20", "cs_mom_20_rank"])
    assert built["row_count"] > 100
    for row in built["rows"]:
        assert row["date"] < row["target_date"]
        assert row["available_at"].startswith(row["date"])
        assert set(row["features"]) == {"mom_5", "mom_20", "vol_20", "cs_mom_20_rank"}
    # No target outcome can be dated before the feature observation.
    assert max(item["date"] for item in built["rows"]) < max(item["target_date"] for item in built["rows"])


def test_metric_arithmetic_matches_definitions():
    p, y = [0.9, 0.1, 0.8], [1, 0, 1]
    assert brier_score(p, y) == pytest.approx(0.02)
    assert log_loss(p, y) == pytest.approx(0.14462152754328744, abs=1e-14)
    expected_ece = (2 / 3) * abs((0.9 + 0.8) / 2 - 1) + (1 / 3) * abs(0.1 - 0)
    assert expected_calibration_error(p, y, bins=2) == pytest.approx(expected_ece)
    table = calibration_table(p, y, bins=2)
    assert table[0]["count"] == 1 and table[1]["count"] == 2
    with pytest.raises(ValueError):
        brier_score([1.1], [1])


def test_experiment_selection_calibration_and_audit_are_reproducible():
    panel = synthetic_panel()
    first = run_experiment(
        panel, models=["climatology", "ridge", "logistic"], features=["mom_5", "mom_20", "vol_20"],
        seed=123,
    )
    second = run_experiment(
        panel, models=["climatology", "ridge", "logistic"], features=["mom_5", "mom_20", "vol_20"],
        seed=123,
    )
    assert first["split"]["test_used_for_selection"] is False
    assert first["selection"]["selected_model"] in {"climatology", "ridge", "logistic"}
    assert first["model"]["fingerprint"] == second["model"]["fingerprint"]
    assert first["test"]["brier"] == pytest.approx(second["test"]["brier"], abs=1e-12)
    assert first["audit"]["overall_score"] is None
    assert first["audit"]["findings"]
    assert all("code" not in item for item in first["audit"]["findings"])
    assert first["test"]["calibration"]
    assert len(first["forecasts"]) == first["test"]["observations"]
    assert first["continuous"]["metrics"]["interval_coverage"] >= 0


def test_auditor_flags_deliberate_contamination_and_small_sample():
    result = run_experiment(
        synthetic_panel(360), models=["ridge"], features=["mom_20", "vol_20"], seed=7,
    )
    contaminated = {
        **result,
        "split": {**result["split"], "test_used_for_selection": True},
    }
    audit = audit_result(
        contaminated, feature_correlation=0.99, train_rows=20, test_rows=12,
        selected_model="ridge", data_class="observed", rights="restricted",
    )
    by_key = {item["finding_key"]: item for item in audit["findings"]}
    assert by_key["chronological_partitions"]["severity"] == "error"
    assert by_key["small_test_sample"]["severity"] == "warning"
    assert by_key["collinear_features"]["severity"] == "warning"
    assert audit["overall_score"] is None


def test_bounded_discovery_never_uses_final_test():
    report = discover(synthetic_panel(520), budget=2, models=["ridge"], feature_sets=[["mom_20"]])
    assert report["evaluated"] == 2
    assert report["test_used"] is False
    assert report["recommendations"]
    assert report["stop_reason"].startswith("budget exhausted")


def test_signal_contract_accepts_only_bounded_frozen_probabilities():
    from atlas.quant.contracts import validate_strategy

    spec = {
        "schema_version": "atlas.strategy.v1", "name": "Frozen probabilities", "version": "1.0.0",
        "universe": {"instruments": [{"security_id": "SEC-ABC", "mic": "XNAS"}]},
        "features": [{"name": "close", "kind": "price", "window": 1}],
        "signal": {"kind": "learning_probability", "threshold": 0.55,
                   "forecasts": [{"date": "2025-01-02", "probability": 0.6},
                                 {"date": "2025-01-03", "probability": 0.4}]},
        "execution": {"signal_at": "close", "fill_at": "next_open"},
    }
    result = validate_strategy(spec)
    assert result["signal"]["forecasts"][0]["date"] == "2025-01-02"
    bad = {**spec, "signal": {**spec["signal"], "forecasts": [{"date": "2025-01-02", "probability": 1.2}]}}
    with pytest.raises(Exception):
        validate_strategy(bad)
    duplicate = {**spec, "signal": {**spec["signal"], "forecasts": [
        {"date": "2025-01-02", "probability": 0.6}, {"date": "2025-01-02", "probability": 0.4}]}}
    with pytest.raises(Exception):
        validate_strategy(duplicate)


def test_compiler_probability_operators_match_metrics():
    spec = {
        "schema_version": "atlas.model.v1", "name": "Probability scores", "version": "1.0.0",
        "interface": "graph", "inputs": {"p": "Series[Ratio]", "y": "Series[Scalar]"},
        "nodes": [
            {"id": "b", "op": "probability_brier", "inputs": ["p", "y"]},
            {"id": "l", "op": "probability_log_loss", "inputs": ["p", "y"]},
            {"id": "e", "op": "probability_calibration_error", "inputs": ["p", "y"], "params": {"bins": 2}},
        ], "outputs": ["b", "l", "e"],
    }
    result = ExecutionEngine(use_cache=False).execute(compile_model(spec), {"p": [0.9, 0.1, 0.8], "y": [1, 0, 1]}, persist=False)
    assert result["outputs"]["b"] == pytest.approx(0.02)
    assert result["outputs"]["l"] == pytest.approx(0.14462152754328744, abs=1e-12)
    assert result["outputs"]["e"] == pytest.approx(0.13333333333333333, abs=1e-12)


def test_api_persists_learning_run_forecast_audit_monitor_and_portfolio():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "learning.db"
        db = _seed_database(path)
        db.close()
        client = TestClient(create_app(path))
        assert client.get("/api/health").json()["schema_version"] == 14
        catalog = client.get("/api/learning/catalog")
        assert catalog.status_code == 200
        assert catalog.json()["datasets"][0]["securities"] == 5
        experiment = client.post("/api/learning/experiment", json={
            "dataset": "atlas-synthetic:all", "models": ["climatology", "logistic"],
            "features": ["mom_5", "mom_20", "vol_20"], "persist": True,
        })
        assert experiment.status_code == 200, experiment.text
        payload = experiment.json()
        assert payload["run_id"].startswith("LRUN-")
        assert payload["model_object_id"].startswith("URO-MOD-")
        assert payload["forecasts"]
        assert len(payload["forecasts"]) == payload["test"]["observations"]
        run_id = payload["run_id"]
        run = client.get(f"/api/learning/runs/{run_id}")
        assert run.status_code == 200 and run.json()["run_id"] == run_id
        forecast = client.get(f"/api/learning/runs/{run_id}/forecasts")
        assert forecast.status_code == 200 and forecast.json()["forecasts"]
        audit = client.get(f"/api/learning/runs/{run_id}/audit")
        assert audit.status_code == 200 and audit.json()["overall_score"] is None
        monitor = client.get(f"/api/learning/runs/{run_id}/monitor")
        assert monitor.status_code == 200 and monitor.json()["automatic_retrain"] is False
        memory = client.post("/api/learning/memory", json={"target": "direction"})
        assert memory.status_code == 200 and memory.json()["counts"]["runs"] >= 1
        applications = client.post("/api/learning/applications", json={
            "run_id": run_id, "name": "Phase 6 research application",
        })
        assert applications.status_code == 201
        assert applications.json()["document"]["kind"] == "application"
        security = payload["forecasts"][0]["security_id"]
        portfolio = client.post(f"/api/learning/runs/{run_id}/portfolio", json={
            "security_id": security, "threshold": 0.5,
        })
        assert portfolio.status_code == 200, portfolio.text
        assert portfolio.json()["backtest"]["reconciliation"]["reconciled"] is True
        assert portfolio.json()["application"]["document"]["kind"] == "application"
        # Changing the decision threshold is a new frozen strategy, not a silent edit.
        second_portfolio = client.post(f"/api/learning/runs/{run_id}/portfolio", json={
            "security_id": security, "threshold": 0.55,
        })
        assert second_portfolio.status_code == 200, second_portfolio.text
        assert (second_portfolio.json()["backtest"]["strategy_object_id"]
                != portfolio.json()["backtest"]["strategy_object_id"])
        # Repeating the same frozen decision is idempotent, not an immutable-object error.
        repeat = client.post(f"/api/learning/runs/{run_id}/portfolio", json={
            "security_id": security, "threshold": 0.5,
        })
        assert repeat.status_code == 200, repeat.text
        assert repeat.json()["application"]["object_id"] == portfolio.json()["application"]["object_id"]
