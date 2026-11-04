"""Independent validation of the compiler, runtime and DCF arithmetic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.core.errors import ValidationError
from atlas.fec import ExecutionEngine, compile_model
from atlas.fec.sdk import ModelBuilder, price_times_shares
from atlas.fec.types import FinType, TypeMismatch
from atlas.fec.valuation import build_dcf_spec, run_dcf
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION


def reference_dcf(
    revenue: float, growth: list[float], margin: float, tax: float, da_pct: float,
    capex_pct: float, nwc_pct: float, wacc: float, terminal_growth: float,
    cash: float, debt: float, shares: float, horizon: int,
) -> dict[str, float]:
    """Pure arithmetic reference. It does not import or call the production compiler."""
    revenue_series, fcff = [], []
    initial_nwc = revenue * nwc_pct
    prior_nwc = initial_nwc
    for index in range(horizon):
        revenue = revenue * (1 + growth[index])
        revenue_series.append(revenue)
        ebit = revenue * margin
        nopat = ebit * (1 - tax)
        da = revenue * da_pct
        capex = revenue * capex_pct
        nwc = revenue * nwc_pct
        change = nwc - prior_nwc
        prior_nwc = nwc
        fcff.append(nopat + da - capex - change)
    pv = sum(cash_flow / (1 + wacc) ** (index + 1) for index, cash_flow in enumerate(fcff))
    terminal = fcff[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal / (1 + wacc) ** horizon
    enterprise = pv + pv_terminal
    equity = enterprise + cash - debt
    return {
        "enterprise_value": enterprise,
        "equity_value": equity,
        "value_per_share": equity / shares,
        "pv_explicit": pv,
        "pv_terminal": pv_terminal,
        "fcff": fcff,
        "revenue_forecast": revenue_series,
    }


def _assumptions() -> dict:
    return {
        "revenue": 100.0,
        "revenue_growth": [0.10, 0.08, 0.06, 0.05, 0.04],
        "operating_margin": 0.20,
        "tax_rate": 0.25,
        "da_pct_revenue": 0.05,
        "capex_pct_revenue": 0.06,
        "nwc_pct_revenue": 0.02,
        "wacc": 0.10,
        "terminal_growth": 0.02,
        "cash": 10.0,
        "debt": 20.0,
        "shares": 5.0,
    }


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "atlas.db")
    db.migrate()
    assert db.schema_version() == LATEST_VERSION
    return db


def test_equivalence_equation_graph_and_sdk(db):
    raw = {
        "schema_version": "atlas.model.v1", "name": "Price times shares",
        "interface": "equation",
        "inputs": [{"name": "price", "type": "Price[USD]"}, {"name": "shares", "type": "Shares"}],
        "equations": [{"name": "market_cap", "expr": "price * shares"}],
        "outputs": ["market_cap"],
    }
    equation = compile_model(raw)
    graph = price_times_shares().compile()
    sdk = (ModelBuilder("Price times shares").input("price", "Price[USD]")
           .input("shares", "Shares").node("market_cap", "mul", ["price", "shares"])
           .output("market_cap", "market_cap").compile())
    values = [
        ExecutionEngine(db).execute(model, {"price": 25, "shares": 4})["outputs"]["market_cap"]
        for model in (equation, graph, sdk)
    ]
    assert values == [100.0, 100.0, 100.0]
    assert equation.nodes[equation.outputs["market_cap"]].type == FinType.parse("Money[USD]")


def test_currency_and_temporal_errors_are_actionable():
    with pytest.raises(Exception) as exc:
        compile_model({
            "schema_version": "atlas.model.v1", "name": "FX error", "interface": "equation",
            "inputs": [{"name": "usd", "type": "Money[USD]"}, {"name": "eur", "type": "Money[EUR]"}],
            "equations": [{"name": "total", "expr": "usd + eur"}], "outputs": ["total"],
        })
    diagnostic = exc.value.context["diagnostics"][0]
    assert diagnostic["code"] == "currency_mismatch"
    assert "explicit FX conversion" in diagnostic["message"]

    with pytest.raises(TypeMismatch):
        FinType.parse("Money[EURO]")


def test_cycle_and_undefined_references():
    with pytest.raises(Exception) as exc:
        compile_model({
            "schema_version": "atlas.model.v1", "name": "cycle", "interface": "graph",
            "inputs": [{"name": "a", "type": "Scalar"}],
            "nodes": [{"id": "x", "op": "add", "inputs": ["y", "a"]},
                      {"id": "y", "op": "add", "inputs": ["x", "a"]}],
            "outputs": {"out": "x"},
        })
    assert any(item["code"] == "cycle" for item in exc.value.context["diagnostics"])


def test_dcf_matches_independent_reference(db):
    # Insert evidence only for the audit path; arithmetic is checked without valuation DB data.
    a = _assumptions()
    expected = reference_dcf(
        revenue=a["revenue"], growth=a["revenue_growth"], margin=a["operating_margin"],
        tax=a["tax_rate"], da_pct=a["da_pct_revenue"], capex_pct=a["capex_pct_revenue"],
        nwc_pct=a["nwc_pct_revenue"], wacc=a["wacc"],
        terminal_growth=a["terminal_growth"], cash=a["cash"], debt=a["debt"],
        shares=a["shares"], horizon=5,
    )
    from atlas.fec import valuation
    normalised = valuation._normalise(a)
    compiled = compile_model(build_dcf_spec(normalised, name="reference"))
    result = ExecutionEngine(db).execute(compiled, valuation._inputs(normalised, {}))
    for key in ("enterprise_value", "equity_value", "value_per_share", "pv_explicit", "pv_terminal"):
        assert result["outputs"][key] == pytest.approx(expected[key], rel=1e-10)
    for actual, ref in zip(result["outputs"]["fcff"], expected["fcff"]):
        assert actual == pytest.approx(ref, rel=1e-10)
    assert result["trace"]


def test_midyear_convention_and_terminal_errors(db):
    a = _assumptions()
    a["convention"] = "mid_year"
    normalised = __import__("atlas.fec.valuation", fromlist=["_normalise"])._normalise(a)
    compiled = compile_model(build_dcf_spec(normalised))
    result = ExecutionEngine(db).execute(compiled, __import__("atlas.fec.valuation", fromlist=["_inputs"])._inputs(normalised, {}))
    assert result["outputs"]["value_per_share"] > 0

    bad = _assumptions()
    bad["terminal_growth"] = bad["wacc"]
    with pytest.raises(ValidationError):
        build_dcf_spec(bad)


def test_share_count_is_never_silently_assumed():
    from atlas.core.errors import MissingDataError
    from atlas.fec.valuation import defaults_from_metrics

    with pytest.raises(MissingDataError):
        defaults_from_metrics({"metrics": {"revenue": {"value": 100.0}}})
    derived = defaults_from_metrics({"metrics": {
        "revenue": {"value": 100.0},
        "net_income": {"value": 10.0, "evidence_ids": ["EV-NI"], "period_end": "2024-12-31"},
        "eps_diluted": {"value": 2.0, "evidence_ids": ["EV-EPS"], "period_end": "2024-12-31"},
    }})
    assert derived["shares"] == 5.0
    assert derived["provenance"]["shares_outstanding"]["kind"] == "derived_estimate"


def test_incremental_recomputation_uses_only_dependent_subgraph(db):
    builder = (
        ModelBuilder("incremental", as_of="2024-01-01T00:00:00Z")
        .input("a", "Scalar").input("b", "Scalar")
        .node("a_squared", "mul", ["a", "a"])
        .node("a_plus_b", "add", ["a", "b"])
        .node("a_times_b", "mul", ["a", "b"])
        .output("a_squared", "a_squared")
        .output("a_plus_b", "a_plus_b")
        .output("a_times_b", "a_times_b")
    )
    model = builder.compile()
    engine = ExecutionEngine(db)
    first = engine.execute(model, {"a": 3, "b": 4})
    changed = engine.execute(model, {"a": 3, "b": 5})
    assert first["outputs"]["a_plus_b"] == 7.0
    assert changed["outputs"]["a_plus_b"] == 8.0
    assert changed["outputs"]["a_squared"] == 9.0
    statuses = {item["node"]: item["status"] for item in changed["trace"]}
    assert statuses["a_squared"] == "cached"
    assert statuses["a_plus_b"] == "computed"
    # A full reference execution without cache agrees numerically.
    reference = ExecutionEngine(use_cache=False).execute(model, {"a": 3, "b": 5})
    assert reference["outputs"] == changed["outputs"]


def test_historical_metadata_is_part_of_run_identity(db):
    builder = ModelBuilder("dated", as_of="2023-01-01T00:00:00Z").input("x", "Scalar").output("x", "x")
    result = ExecutionEngine(db).execute(builder.compile(), {"x": 2})
    assert result["manifest"]["as_of"] == "2023-01-01T00:00:00Z"
    assert result["manifest"]["fingerprint"] == result["fingerprint"]
