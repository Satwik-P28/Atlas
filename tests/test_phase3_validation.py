"""Independent numerical checks for the Phase 3 valuation laboratory.

These references implement the arithmetic directly from the printed formulas. They do
not import the compiler, operators, runtime or valuation module, so a shared implementation
mistake cannot satisfy both sides of the comparison.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atlas.core.temporal import ReportingPeriod, availability_from_instant
from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.evidence.model import EvidenceRecord
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.api import create_app

ISSUER = "ISS-CIK0000999999"


def _fact(kernel: EvidenceKernel, concept: str, value: str, *, end: date, start: date,
          available: str, unit: str = "USD", accession: str = "0000999999-24-000001") -> None:
    kernel.ingest(EvidenceRecord.build(
        entity_id=ISSUER, entity_kind="issuer", concept=concept, source_id="sec-edgar",
        unit=unit, availability=availability_from_instant(available, "test.acceptance"),
        period=ReportingPeriod(end=end, start=start, fiscal_year=end.year, fiscal_period="FY"),
        value=Decimal(value), accession_number=accession, form_type="10-K",
        filed_date=available[:10], observed_at=available, quality="verified",
        verification="source_primary", source_dataset="sec_companyfacts",
        taxonomy="us-gaap", source_concept=f"us-gaap:{concept}",
    ))


@pytest.fixture()
def valuation_client(tmp_path):
    path = tmp_path / "valuation.db"
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    issuer = master.register_issuer(
        legal_name="Reference Industries", cik="0000999999", entity_type="corporation",
        sic="3571", fiscal_year_end="1231", source_id="sec-edgar",
    )
    master.ensure_venue("XNAS", "Nasdaq Global Select Market", country="US")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="1980-12-12", is_primary=True)
    master.assign_ticker(listing, "REFI", valid_from="2024-01-01", confidence=1.0,
                         status="confirmed", source_id="sec-edgar")
    kernel = EvidenceKernel(db)
    fy23 = dict(end=date(2023, 12, 31), start=date(2023, 1, 1),
                available="2024-02-15T16:05:00Z")
    fy24 = dict(end=date(2024, 12, 31), start=date(2024, 1, 1),
                available="2025-02-15T16:05:00Z")
    _fact(kernel, "revenue", "100000000000", **fy23)
    _fact(kernel, "revenue", "110000000000", **fy24)
    _fact(kernel, "operating_income", "20000000000", **fy23)
    _fact(kernel, "operating_income", "24000000000", **fy24)
    _fact(kernel, "net_income", "15000000000", **fy24)
    _fact(kernel, "capex", "-5000000000", **fy24)
    _fact(kernel, "shares_outstanding", "1000000000", end=date(2024, 12, 31),
          start=date(2024, 1, 1), available="2025-02-15T16:05:00Z", unit="shares")
    db.close()
    return {"client": TestClient(create_app(path), raise_server_exceptions=False), "path": path}


def reference_dcf(a: dict) -> dict:
    """Unlevered FCFF DCF with independently written arithmetic."""
    revenue = float(a["revenue"])
    growth = [float(item) for item in a["revenue_growth"]]
    horizon = int(a["horizon"])
    margin = float(a["operating_margin"])
    tax = float(a["tax_rate"])
    da_pct = float(a["da_pct_revenue"])
    capex_pct = float(a["capex_pct_revenue"])
    nwc_pct = float(a["nwc_pct_revenue"])
    wacc = float(a["wacc"])
    terminal_growth = float(a["terminal_growth"])
    convention = a.get("convention", "end_year")
    method = a.get("terminal_method", "gordon_growth")

    prior_nwc = revenue * nwc_pct
    revenues: list[float] = []
    fcff: list[float] = []
    for rate in growth:
        revenue *= 1 + rate
        revenues.append(revenue)
        ebit = revenue * margin
        nopat = ebit * (1 - tax)
        da = revenue * da_pct
        capex = revenue * capex_pct
        nwc = revenue * nwc_pct
        fcff.append(nopat + da - capex - (nwc - prior_nwc))
        prior_nwc = nwc

    offset = 0.5 if convention == "mid_year" else 0.0
    pv_explicit = sum(
        cash / (1 + wacc) ** (index + 1 + offset) for index, cash in enumerate(fcff)
    )
    if method == "exit_multiple":
        terminal_value = fcff[-1] * float(a["exit_multiple"])
    else:
        terminal_value = fcff[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** (horizon + offset)
    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value + float(a.get("cash", 0)) - float(a.get("debt", 0))
    return {
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "value_per_share": equity_value / float(a["shares"]),
        "pv_explicit": pv_explicit,
        "pv_terminal": pv_terminal,
        "terminal_value": terminal_value,
        "fcff": fcff,
        "revenue_forecast": revenues,
    }


def reference_implied_growth(base: dict, target: float, low: float, high: float) -> float:
    """Independent bisection for terminal growth against reference_dcf."""
    def residual(growth: float) -> float:
        changed = dict(base)
        changed["terminal_growth"] = growth
        return reference_dcf(changed)["value_per_share"] - target

    left, right = low, high
    f_left = residual(left)
    assert f_left * residual(right) <= 0, "reference target is outside the supplied bounds"
    for _ in range(100):
        middle = (left + right) / 2
        f_middle = residual(middle)
        if abs(f_middle) < 1e-7:
            return middle
        if f_left * f_middle <= 0:
            right = middle
        else:
            left, f_left = middle, f_middle
    return (left + right) / 2


def _issuer(client: TestClient) -> str:
    return client.get("/api/companies").json()["items"][0]["issuer_id"]


def _base_case(client: TestClient, issuer: str) -> dict:
    response = client.post(
        "/api/valuation/dcf",
        json={"issuer": issuer, "assumptions": {"revenue_growth": [0.05] * 5}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dcf_conventions_match_independent_reference(valuation_client):
    client = valuation_client["client"]
    issuer = _issuer(client)
    base = _base_case(client, issuer)
    expected = reference_dcf(base["assumptions"])
    for key in ("enterprise_value", "equity_value", "value_per_share", "pv_explicit",
                "pv_terminal", "terminal_value"):
        assert base["outputs"][key] == pytest.approx(expected[key], rel=1e-10)
    assert len(base["outputs"]["fcff"]) == len(expected["fcff"])

    mid_year = client.post(
        "/api/valuation/dcf",
        json={
            "issuer": issuer,
            "assumptions": {**base["assumptions"], "convention": "mid_year"},
        },
    )
    assert mid_year.status_code == 200, mid_year.text
    expected_mid = reference_dcf(mid_year.json()["assumptions"])
    assert mid_year.json()["outputs"]["value_per_share"] == pytest.approx(
        expected_mid["value_per_share"], rel=1e-10
    )

    exit_multiple = client.post(
        "/api/valuation/dcf",
        json={
            "issuer": issuer,
            "assumptions": {
                **base["assumptions"],
                "terminal_method": "exit_multiple",
                "exit_multiple": 11.5,
            },
        },
    )
    assert exit_multiple.status_code == 200, exit_multiple.text
    expected_exit = reference_dcf(exit_multiple.json()["assumptions"])
    assert exit_multiple.json()["outputs"]["terminal_value"] == pytest.approx(
        expected_exit["terminal_value"], rel=1e-10
    )
    assert exit_multiple.json()["outputs"]["value_per_share"] == pytest.approx(
        expected_exit["value_per_share"], rel=1e-10
    )


def test_reverse_dcf_matches_independent_bisection(valuation_client):
    client = valuation_client["client"]
    issuer = _issuer(client)
    base = _base_case(client, issuer)
    assumptions = base["assumptions"]
    target = base["outputs"]["value_per_share"] * 1.04
    low, high = 0.0, min(float(assumptions["wacc"]) - 0.001, 0.08)
    expected = reference_implied_growth(assumptions, target, low, high)

    response = client.post(
        "/api/valuation/reverse",
        json={
            "issuer": issuer,
            "target_price": target,
            "variable": "terminal_growth",
            "bounds": [low, high],
            "assumptions": assumptions,
        },
    )
    assert response.status_code == 200, response.text
    solved = response.json()
    assert solved["solved"] is True
    assert solved["implied_value"] == pytest.approx(expected, abs=2e-4)
    assert solved["solved_price"] == pytest.approx(target, abs=1e-3)


def test_scenarios_and_sensitivity_match_independent_reference(valuation_client):
    client = valuation_client["client"]
    issuer = _issuer(client)
    base = _base_case(client, issuer)
    assumptions = base["assumptions"]

    scenarios = client.post(
        "/api/valuation/scenarios",
        json={
            "issuer": issuer,
            "assumptions": assumptions,
            "custom": {"recession": {"operating_margin": 0.12, "wacc": 0.11}},
        },
    )
    assert scenarios.status_code == 200, scenarios.text
    for name, row in scenarios.json()["scenarios"].items():
        changed = {**assumptions, **row["assumptions"]}
        expected = reference_dcf(changed)
        assert row["value_per_share"] == pytest.approx(
            expected["value_per_share"], rel=1e-10
        ), name
        assert row["delta_vs_base"] == pytest.approx(
            expected["value_per_share"] - base["outputs"]["value_per_share"],
            rel=1e-10,
        )

    waccs = [0.09, 0.10]
    growths = [0.02, 0.025]
    sensitivity = client.post(
        "/api/valuation/sensitivity",
        json={
            "issuer": issuer,
            "assumptions": assumptions,
            "wacc_values": waccs,
            "growth_values": growths,
        },
    )
    assert sensitivity.status_code == 200, sensitivity.text
    matrix = sensitivity.json()["matrix"]
    for row_index, wacc in enumerate(waccs):
        for column_index, growth in enumerate(growths):
            expected = reference_dcf(
                {**assumptions, "wacc": wacc, "terminal_growth": growth}
            )
            assert matrix[row_index][column_index] == pytest.approx(
                expected["value_per_share"], rel=1e-10
            )


def test_negative_flow_and_near_wacc_are_finite(valuation_client):
    client = valuation_client["client"]
    issuer = _issuer(client)
    base = _base_case(client, issuer)
    assumptions = base["assumptions"]

    negative = client.post(
        "/api/valuation/dcf",
        json={
            "issuer": issuer,
            "assumptions": {
                **assumptions,
                "capex_pct_revenue": 1.25,
                "nwc_pct_revenue": 0.40,
            },
        },
    )
    assert negative.status_code == 200, negative.text
    assert all(value < 0 for value in negative.json()["outputs"]["fcff"])

    near = client.post(
        "/api/valuation/dcf",
        json={
            "issuer": issuer,
            "assumptions": {**assumptions, "terminal_growth": 0.0899, "wacc": 0.09},
        },
    )
    assert near.status_code == 200, near.text
    assert near.json()["outputs"]["value_per_share"] > 0
    invalid = client.post(
        "/api/valuation/dcf",
        json={
            "issuer": issuer,
            "assumptions": {**assumptions, "terminal_growth": 0.09, "wacc": 0.09},
        },
    )
    assert invalid.status_code == 422


def test_export_manifest_includes_executed_run_snapshot(valuation_client):
    client = valuation_client["client"]
    db = Database(valuation_client["path"], create=False)
    evidence_id = db.scalar("SELECT evidence_id FROM evidence LIMIT 1")
    db.close()

    spec = {
        "schema_version": "atlas.model.v1",
        "name": "Export reproducibility model",
        "interface": "equation",
        "inputs": [
            {"name": "price", "type": "Price[USD]"},
            {"name": "shares", "type": "Shares"},
        ],
        "equations": [{"name": "value", "expr": "price * shares"}],
        "outputs": ["value"],
        "as_of": "2024-01-01T00:00:00Z",
        "mode": "public_available",
    }
    run = client.post(
        "/api/models/run",
        json={"spec": spec, "inputs": {"price": 12, "shares": 3}, "persist": True},
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]
    document = {
        "schema_version": "atlas.research_object.v1",
        "kind": "model",
        "name": "Export reproducibility object",
        "version": "1.0.0",
        "status": "validated",
        "description": "Exercises archived run inputs and outputs in export.",
        "as_of": "2024-01-01T00:00:00Z",
        "mode": "public_available",
        "evidence_ids": [evidence_id],
        "spec": {
            "inputs": {"price": "Price[USD]", "shares": "Shares"},
            "outputs": {"value": "value"},
            "method": "atlas.model.v1",
            "assumptions": [],
            "validation": "compiled",
            "model_spec": spec,
            "run_id": run_id,
        },
    }
    created = client.post("/api/research/objects", json={"document": document})
    assert created.status_code == 201, created.text
    manifest = client.get(
        f"/api/research/objects/{created.json()['object_id']}/export"
    ).json()
    assert manifest["run"]["run_id"] == run_id
    assert manifest["run"]["inputs"]["price"] == {"kind": "decimal", "value": "12"}
    assert manifest["run"]["outputs"]["value"] == 36.0
    json.dumps(manifest)
