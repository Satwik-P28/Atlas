"""Independent Phase 5 validation for curves, bonds, options, risk and OOS research."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.fec import compile_model
from atlas.fec.runtime import ExecutionEngine
from atlas.finance.curves import analyse_bond, load_treasury_csv
from atlas.finance.options import bsm_greeks, bsm_price, implied_volatility, option_parity_residual
from atlas.institutional.risk import optimize, portfolio_analysis
from atlas.institutional.universe import build_panel, returns_matrix
from atlas.institutional.validation import walk_forward
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.terminal.api import create_app

CURVE_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "phase5" / "treasury-par-yields-2024.csv"


def _curve():
    return load_treasury_csv(CURVE_FILE, observation_date="2024-06-28")


def test_schema_7_and_tables(tmp_path):
    db = Database(tmp_path / "phase5.db")
    assert LATEST_VERSION == 10
    assert db.migrate() == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    tables = {row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"institutional_run", "validation_attempt", "learning_run", "learning_model"} <= tables
    assert db.schema_version() == 10
    db.close()


def test_treasury_bootstrap_reconciles_every_par_node():
    curve = _curve()
    assert curve.source_sha256 == "6775840b76cd7fd41121f61d6f6c60184eca6b2ba49954ec7372c463cbeef34d"
    assert curve.nodes[0].par_yield == pytest.approx(0.0547)
    for node in curve.nodes:
        if node.months < 24:
            continue
        coupon = node.par_yield * 100 / 2
        times = [i / 2 for i in range(1, int(round(node.years * 2)) + 1)]
        price = sum(coupon * curve.discount_factor(t) for t in times)
        price += 100 * curve.discount_factor(node.years)
        assert price == pytest.approx(100.0, abs=1e-8), node.tenor
    # A forward is exactly the ratio of the discount factors, not a separately
    # estimated number pasted into the result.
    start, end = 2.0, 5.0
    expected_forward = (
        math.log(curve.discount_factor(start) / curve.discount_factor(end)) / (end - start)
    )
    assert curve.forward_rate(start, end) == pytest.approx(expected_forward, abs=1e-12)


def test_bond_cash_flows_and_sensitivities_are_independently_reproduced():
    curve = _curve()
    bond = analyse_bond(
        curve, settlement_date="2024-07-01", maturity_date="2029-06-30",
        coupon_rate=0.0425,
    )
    assert sum(flow.present_value for flow in bond.cash_flows) == pytest.approx(
        bond.dirty_price, abs=1e-9
    )
    assert bond.clean_price + bond.accrued_interest == pytest.approx(bond.dirty_price, abs=1e-9)
    # Manual Macaulay duration from the published cash-flow present values.
    expected_duration = sum(flow.year_fraction * flow.present_value for flow in bond.cash_flows)
    expected_duration /= bond.dirty_price
    assert bond.macaulay_duration == pytest.approx(expected_duration, abs=1e-10)
    # Modified duration × dirty price × 1bp should approximate curve-revaluation DV01.
    assert bond.dv01 == pytest.approx(
        bond.modified_duration * bond.dirty_price * 0.0001, rel=0.04
    )
    assert bond.dv01 > 0
    assert bond.accrued_days >= 0


def test_black_scholes_reference_values_parity_and_implied_volatility():
    call = bsm_price(100, 100, 1, 0.05, 0.20, 0.0, "call")
    put = bsm_price(100, 100, 1, 0.05, 0.20, 0.0, "put")
    assert call == pytest.approx(10.4505835722, abs=1e-9)
    assert put == pytest.approx(5.5735260223, abs=1e-9)
    assert option_parity_residual(call, put, 100, 100, 1, 0.05) == pytest.approx(0.0, abs=1e-12)
    assert implied_volatility(call, 100, 100, 1, 0.05, 0.0, "call") == pytest.approx(0.20, abs=1e-8)
    # Analytical Greeks against independent finite differences of the price function.
    bump = 1e-4
    delta_fd = (bsm_price(100 + bump, 100, 1, .05, .2) - bsm_price(100 - bump, 100, 1, .05, .2)) / (2 * bump)
    vega_fd = (bsm_price(100, 100, 1, .05, .2 + bump) - bsm_price(100, 100, 1, .05, .2 - bump)) / (2 * bump)
    greeks = bsm_greeks(100, 100, 1, .05, .2)
    assert greeks["delta"] == pytest.approx(delta_fd, abs=1e-6)
    assert greeks["vega"] == pytest.approx(vega_fd, abs=1e-5)
    assert bsm_price(100, 100, 0, .05, .2) == pytest.approx(0.0)


def test_portfolio_risk_is_aligned_and_contributions_reconcile():
    matrix = returns_matrix()
    assert matrix["data_class"] == "synthetic_fixture"
    assert len(matrix["securities"]) == 3
    assert len(matrix["dates"]) >= 900
    weights = {security: 1 / 3 for security in matrix["securities"]}
    report = portfolio_analysis(weights=weights, lookback=252)
    assert report["risk"]["contribution_check"]["matches_portfolio_volatility"]
    assert sum(report["risk"]["contribution_pct"].values()) == pytest.approx(1.0, abs=1e-10)
    assert report["risk"]["annualized_volatility"] > 0
    assert 0 < report["risk"]["historical_var_95_daily"] < 0.2
    assert report["risk"]["historical_es_95_daily"] >= report["risk"]["historical_var_95_daily"]
    assert sum(report["risk"]["sector_exposure"].values()) == pytest.approx(1.0, abs=1e-12)
    assert report["risk"]["rate_sensitivity"] is None


def test_optimizer_respects_caps_and_improves_on_equal_weight():
    matrix = returns_matrix()
    equal = {security: 1 / 3 for security in matrix["securities"]}
    result = optimize(weights=equal, max_weight=0.6)
    assert result["solution"]["feasible"] is True
    weights = result["solution"]["weights"]
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-10)
    assert max(weights.values()) <= 0.6 + 1e-10
    assert min(weights.values()) >= -1e-10
    equal_report = portfolio_analysis(weights=equal, lookback=len(matrix["returns"]))
    assert result["solution"]["variance"] <= equal_report["risk"]["variance"] + 1e-12
    infeasible = optimize(max_weight=0.2)
    assert infeasible["solution"]["feasible"] is False


def test_walk_forward_partitions_attempts_and_cost_sensitivity():
    result = walk_forward(folds=2, train=180, validation=40, test=40, step=40, embargo=5)
    assert result["credibility"]["test_interval_untouched"] is True
    assert result["selection_policy"]["test_used_for_selection"] is False
    assert len(result["folds"]) == 2
    assert len(result["attempts"]) == 24
    for fold in result["folds"]:
        train = fold["partitions"]["train"]
        validation = fold["partitions"]["validation"]
        test = fold["partitions"]["test"]
        assert train[1] < validation[0] < validation[1] < test[1]
        assert len(fold["test_cost_sensitivity"]) == 4
        assert {item["commission_bps"] for item in fold["test_cost_sensitivity"]} == {0.0, 2.0, 10.0, 25.0}
    assert result["aggregate"]["observations"] == 80
    assert result["multiple_testing"]["trials"] == 24
    assert result["parameter_stability"]["unique_families"]
    assert result["data_snapshot"]["content_hash"]


def test_compiler_exposes_bond_option_and_risk_operators():
    spec = {
        "schema_version": "atlas.model.v1", "name": "Phase 5 typed operators", "version": "1.0.0",
        "interface": "graph",
        "inputs": {
            "coupon": "Rate", "ytm": "Rate", "years": "Scalar",
            "spot": "Price[USD]", "strike": "Price[USD]", "vol": "Ratio", "rate": "Rate",
            "time": "Scalar", "weights": "Series[Ratio]", "covariance": "Series[Ratio]",
        },
        "nodes": [
            {"id": "bond", "op": "bond_price", "inputs": ["coupon", "ytm", "years"], "params": {"frequency": 2}},
            {"id": "duration", "op": "bond_macaulay_duration", "inputs": ["coupon", "ytm", "years"], "params": {"frequency": 2}},
            {"id": "option", "op": "option_price", "inputs": ["spot", "strike", "vol", "rate", "time"], "params": {"kind": "call"}},
            {"id": "delta", "op": "option_greek", "inputs": ["spot", "strike", "vol", "rate", "time"], "params": {"kind": "call", "greek": "delta"}},
            {"id": "variance", "op": "portfolio_variance", "inputs": ["weights", "covariance"]},
            {"id": "contrib", "op": "risk_contributions", "inputs": ["weights", "covariance"]},
        ],
        "outputs": ["bond", "duration", "option", "delta", "variance", "contrib"],
    }
    model = compile_model(spec)
    result = ExecutionEngine(use_cache=False).execute(model, {
        "coupon": 0.0425, "ytm": 0.043, "years": 5,
        "spot": 100, "strike": 100, "vol": 0.2, "rate": 0.05, "time": 1,
        "weights": [0.5, 0.5], "covariance": [0.04, 0.01, 0.01, 0.09],
    }, persist=False)
    assert result["outputs"]["bond"] == pytest.approx(99.77718762683088, abs=1e-8)
    assert result["outputs"]["duration"] == pytest.approx(4.556276755601258, abs=1e-8)
    assert result["outputs"]["option"] == pytest.approx(10.450583572185565, abs=1e-9)
    assert result["outputs"]["variance"] == pytest.approx(0.0375, abs=1e-12)
    assert sum(result["outputs"]["contrib"]) == pytest.approx(1.0, abs=1e-12)


def test_institutional_api_persists_runs_and_applications():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "api.db"
        db = Database(path)
        db.migrate()
        db.close()
        client = TestClient(create_app(path))
        assert client.get("/api/health").json()["schema_version"] == 10
        catalog = client.get("/api/institutional/catalog")
        assert catalog.status_code == 200
        assert "2024-06-28" in catalog.json()["curve"]["dates"]
        assert all("/" not in item for item in catalog.json()["curve"]["dates"])
        curve = client.get("/api/institutional/curve").json()
        assert curve["observation_date"] == "2024-06-28"
        bond = client.post("/api/institutional/bond", json={
            "settlement_date": "2024-07-01", "maturity_date": "2029-06-30",
            "coupon_rate": 0.0425,
        })
        assert bond.status_code == 200 and bond.json()["run_id"].startswith("IRUN-")
        option = client.post("/api/institutional/option", json={
            "spot": 100, "strike": 100, "time": 1, "rate": 0.05, "volatility": 0.2,
        })
        assert option.status_code == 200
        assert abs(option.json()["parity_residual"]) < 1e-10
        risk = client.post("/api/institutional/portfolio", json={"lookback": 252})
        assert risk.status_code == 200 and risk.json()["risk"]["contribution_check"]["matches_portfolio_volatility"]
        optimization = client.post("/api/institutional/optimize", json={"max_weight": 0.6})
        assert optimization.status_code == 200 and optimization.json()["solution"]["feasible"]
        validation = client.post("/api/institutional/validate", json={
            "folds": 1, "train": 180, "validation": 40, "test": 40, "step": 40,
        })
        assert validation.status_code == 200
        run_id = validation.json()["run_id"]
        attempts = client.get(f"/api/institutional/runs/{run_id}/attempts")
        assert attempts.status_code == 200 and len(attempts.json()["items"]) == 12
        application = client.post("/api/institutional/applications", json={
            "kind": "portfolio_risk", "name": "Risk test",
            "inputs": {"weights": {"SYN-ALPHA": 0.34, "SYN-BETA": 0.33, "SYN-GAMMA": 0.33}},
            "result": risk.json(),
        })
        assert application.status_code == 201
        reopened = client.get(f"/api/research/objects/{application.json()['object_id']}")
        assert reopened.status_code == 200
        assert reopened.json()["document"]["spec"]["application"]["type"] == "portfolio_risk"
        invalid = client.post("/api/institutional/bond", json={
            "settlement_date": "2024-07-01", "maturity_date": "2024-06-01",
            "coupon_rate": 0.04,
        })
        assert invalid.status_code == 422
        operators = client.get("/api/models/operators").json()["items"]
        assert {"bond_price", "option_price", "portfolio_variance", "risk_contributions"} <= {
            item["key"] for item in operators
        }
