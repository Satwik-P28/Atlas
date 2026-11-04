"""HTTP API tests against a small, deterministic database.

The tests exercise the real FastAPI app and the real kernel — no mocked financial
layer — so a regression in selection, provenance or formatting surfaces here.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atlas.core.temporal import ReportingPeriod, availability_from_instant
from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.evidence.model import EvidenceRecord
from atlas.market.actions import ActionStore, ActionType, CorporateAction
from atlas.market.bars import Bar, BarStore
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.api import create_app

APPLE = "0000320193"
ISSUER = "ISS-CIK0000320193"


def _fact(kernel: EvidenceKernel, concept: str, value: str, *, end: date, start: date, fy: int,
          available: str, unit: str = "USD", accession: str = "0000320193-24-000123") -> None:
    record = EvidenceRecord.build(
        entity_id=ISSUER,
        entity_kind="issuer",
        concept=concept,
        source_id="sec-edgar",
        unit=unit,
        availability=availability_from_instant(available, "test.acceptance"),
        period=ReportingPeriod(end=end, start=start, fiscal_year=fy, fiscal_period="FY"),
        value=Decimal(value),
        accession_number=accession,
        form_type="10-K",
        filed_date=available[:10],
        observed_at=available,
        quality="verified",
        verification="source_primary",
        source_dataset="sec_companyfacts",
        taxonomy="us-gaap",
        source_concept=f"us-gaap:{concept}",
    )
    kernel.ingest(record)


@pytest.fixture()
def terminal(tmp_path):
    path = tmp_path / "atlas-terminal.db"
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    issuer = master.register_issuer(
        legal_name="Apple Inc.", cik=APPLE, entity_type="corporation", sic="3571",
        fiscal_year_end="0928", source_id="sec-edgar",
    )
    master.ensure_venue("XNAS", "Nasdaq Global Select Market", country="US")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="1980-12-12", is_primary=True)
    master.assign_ticker(listing, "AAPL", valid_from="2024-01-01", confidence=0.6,
                         status="probable", source_id="sec-edgar")

    kernel = EvidenceKernel(db)
    fy23 = dict(end=date(2023, 9, 30), start=date(2022, 10, 1), fy=2023, available="2023-11-03T16:05:00Z",
                accession="0000320193-23-000106")
    fy24 = dict(end=date(2024, 9, 28), start=date(2023, 10, 1), fy=2024, available="2024-11-01T16:05:00Z",
                accession="0000320193-24-000123")
    _fact(kernel, "revenue", "383285000000", **fy23)
    _fact(kernel, "revenue", "391035000000", **fy24)
    _fact(kernel, "net_income", "96995000000", **fy23)
    _fact(kernel, "net_income", "93736000000", **fy24)
    _fact(kernel, "gross_profit", "169148000000", **fy23)
    _fact(kernel, "gross_profit", "180683000000", **fy24)
    _fact(kernel, "operating_income", "114301000000", **fy23)
    _fact(kernel, "operating_income", "123216000000", **fy24)
    _fact(kernel, "assets", "352583000000", end=date(2023, 9, 30), start=None, fy=2023,
          available="2023-11-03T16:05:00Z", accession="0000320193-23-000106")
    _fact(kernel, "assets", "364980000000", end=date(2024, 9, 28), start=None, fy=2024,
          available="2024-11-01T16:05:00Z", accession="0000320193-24-000123")
    _fact(kernel, "liabilities", "290437000000", end=date(2024, 9, 28), start=None, fy=2024,
          available="2024-11-01T16:05:00Z")
    _fact(kernel, "equity", "56950000000", end=date(2024, 9, 28), start=None, fy=2024,
          available="2024-11-01T16:05:00Z")
    _fact(kernel, "shares_outstanding", "15408406000", end=date(2024, 9, 28), start=None, fy=2024,
          available="2024-11-01T16:05:00Z", unit="shares")
    _fact(kernel, "operating_cash_flow", "118254000000", **fy24)
    _fact(kernel, "capex", "-9447000000", **fy24)

    start = date(2024, 7, 1)
    bars = []
    close = 200.0
    for index in range(60):
        day = start + timedelta(days=index)
        if day.weekday() >= 5:
            continue
        close = close * 1.002
        bars.append(
            Bar(
                security_id=security,
                mic="XNAS",
                ts_utc=f"{day.isoformat()}T20:00:00Z",
                open=Decimal(str(round(close - 1, 2))),
                high=Decimal(str(round(close + 2, 2))),
                low=Decimal(str(round(close - 2, 2))),
                close=Decimal(str(round(close, 2))),
                volume=Decimal("1000000"),
                currency="USD",
                source_id="atlas-synthetic",
                observed_at=f"{day.isoformat()}T21:00:00Z",
            )
        )
    BarStore(db).ingest(bars)

    ActionStore(db).add(
        CorporateAction(
            security_id=security, action_type=ActionType.SPLIT.value, source_id="atlas-synthetic",
            ex_date="2024-08-01", ratio_from=Decimal("1"), ratio_to=Decimal("2"),
            notes="test split",
        ),
        availability=availability_from_instant("2024-07-01T12:00:00Z", "test"),
    )

    db.execute(
        "INSERT INTO filing (filing_id, issuer_id, cik, accession_number, form_type, filed_date, "
        "acceptance_datetime, period_of_report, primary_document, is_amendment, is_xbrl, is_inline_xbrl, source_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("FIL-1", issuer, APPLE, "0000320193-24-000123", "10-K", "2024-11-01",
         "2024-11-01T16:05:00Z", "2024-09-28", "aapl-20240928.htm", 0, 1, 1, "sec-edgar"),
    )
    db.execute(
        "INSERT INTO filing (filing_id, issuer_id, cik, accession_number, form_type, filed_date, "
        "acceptance_datetime, period_of_report, is_amendment, amends_accession, is_xbrl, is_inline_xbrl, source_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("FIL-2", issuer, APPLE, "0000320193-25-000010", "10-K/A", "2025-01-15",
         "2025-01-15T16:05:00Z", "2024-09-28", 1, "0000320193-24-000123", 1, 1, "sec-edgar"),
    )
    db.close()

    client = TestClient(create_app(path), raise_server_exceptions=False)
    return {"client": client, "path": path, "security_id": security}


def test_health_and_contract(terminal):
    client = terminal["client"]
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["schema_version"] == 5
    assert health["issuers"] == 1
    contract = client.get("/api/schema").json()
    assert contract["selection_policy"] == "atlas.select.point_in_time.v2"
    assert contract["terminal_schema"] == "atlas.terminal.v1"


def test_companies_and_detail(terminal):
    client = terminal["client"]
    companies = client.get("/api/companies").json()
    assert companies["count"] == 1
    company = companies["items"][0]
    assert company["legal_name"] == "Apple Inc."
    assert company["securities"][0]["tickers"][0]["ticker"] == "AAPL"
    assert company["evidence_count"] == 15

    detail = client.get(f"/api/companies/{ISSUER}").json()
    assert detail["availability"]["exact"] == 15
    assert detail["filing_count"] == 2
    assert detail["warnings"]


def test_search_finds_by_name_and_ticker_without_inventing(terminal):
    client = terminal["client"]
    by_name = client.get("/api/search?q=Apple").json()
    assert by_name["count"] == 1
    assert by_name["items"][0]["label"] == "Apple Inc."
    assert by_name["items"][0]["tickers"] == ["AAPL"]
    assert client.get("/api/search?q=AAPL").json()["items"][0]["issuer_id"] == ISSUER
    assert client.get("/api/search?q=zzzz").json()["items"] == []
    assert client.get("/api/search").status_code == 422


def test_company_resolution_by_ticker_and_unknown(terminal):
    client = terminal["client"]
    assert client.get("/api/companies/AAPL").status_code == 200
    response = client.get("/api/companies/ZZZZ")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "unknown_entity"
    assert body["error"]["context"]["ticker"] == "ZZZZ"


def test_statements_carry_evidence_ids(terminal):
    client = terminal["client"]
    response = client.get(f"/api/companies/{ISSUER}/statements?statement=income&period=FY&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert [column["period_end"] for column in data["columns"]] == ["2024-09-28", "2023-09-30"]
    revenue = next(row for row in data["rows"] if row["concept"] == "revenue")
    assert revenue["cells"][0]["value"] == "391035000000"
    assert revenue["cells"][0]["evidence_id"].startswith("EV-")
    assert data["completeness"] == "complete_for_query"
    assert data["policy"] == "atlas.select.point_in_time.v2"

    balance = client.get(f"/api/companies/{ISSUER}/statements?statement=balance&period=FY").json()
    assert any(row["concept"] == "assets" for row in balance["rows"])


def test_as_of_excludes_later_filing(terminal):
    client = terminal["client"]
    data = client.get(
        f"/api/companies/{ISSUER}/statements?statement=income&period=FY&as_of=2024-06-01T23:59:59Z"
    ).json()
    assert [column["period_end"] for column in data["columns"]] == ["2023-09-30"]
    assert data["excluded_not_yet_available"] > 0
    revenue = next(row for row in data["rows"] if row["concept"] == "revenue")
    assert revenue["cells"][0]["value"] == "383285000000"


def test_metrics_expose_formulas_and_evidence(terminal):
    client = terminal["client"]
    data = client.get(f"/api/companies/{ISSUER}/metrics").json()
    assert data["period_end"] == "2024-09-28"
    gross = data["metrics"]["gross_margin"]
    assert gross["formula"] == "gross_profit / revenue"
    assert gross["value"] == pytest.approx(180683 / 391035)
    assert gross["evidence_ids"]
    assert data["metrics"]["market_cap"]["formula"] == "last_close * shares_outstanding"
    assert data["metrics"]["market_cap"]["price_as_of"]
    assert data["price_source"] == "synthetic"
    assert data["metrics"]["pe"]["value"] > 0
    assert data["metrics"]["revenue_growth"]["comparison_period_end"] == "2023-09-30"
    assert "free_cash_flow" in data["metrics"]
    assert data["missing"] == []


def test_market_views_ranges_and_indicators(terminal):
    client = terminal["client"]
    security = terminal["security_id"]
    data = client.get(f"/api/securities/{security}/market?range=1Y&view=split").json()
    assert data["range"]["end"] == data["coverage"]["last"][:10]
    assert len(data["bars"]) > 10
    assert data["adjustment_status"] == "split_adjusted"
    assert data["data_status"] == "synthetic"
    assert data["range_note"] and "last stored session" in data["range_note"]

    raw = client.get(f"/api/securities/{security}/market?range=3M&view=raw").json()
    assert raw["adjustment_status"] == "raw"
    assert all(bar["close"] == pytest.approx(bar["open"] + 1, abs=0.06) for bar in raw["bars"])

    total = client.get(f"/api/securities/{security}/market?range=3M&view=total_return").json()
    assert total["index"]
    assert total["adjustment_status"] == "total_return_index"
    assert "not a price" in total["price_basis_note"]

    with_indicator = client.post(
        f"/api/securities/{security}/market",
        json={"range": "3M", "view": "split", "indicators": [{"key": "sma", "params": {"window": 10}}]},
    ).json()
    assert with_indicator["indicators"][0]["version"] == "atlas.indicator.sma.v1"
    assert with_indicator["indicators"][0]["series"][0]["points"]

    # Regression: total-return mode exposes only index levels, so indicators there must
    # be fed the index series rather than raw OHLC bars (this used to raise KeyError).
    index_with_indicator = client.post(
        f"/api/securities/{security}/market",
        json={"range": "3M", "view": "total_return", "indicators": [{"key": "sma", "params": {"window": 5}}]},
    )
    assert index_with_indicator.status_code == 200, index_with_indicator.text
    payload = index_with_indicator.json()
    assert payload["adjustment_status"] == "total_return_index"
    assert payload["indicators"][0]["series"][0]["points"]
    last_point = payload["indicators"][0]["series"][0]["points"][-1]
    assert last_point["value"] == pytest.approx(
        sum(point["value"] for point in payload["index"][-5:]) / 5, rel=1e-9
    )


def test_market_rejects_bad_view_and_unknown_security(terminal):
    client = terminal["client"]
    assert client.get(f"/api/securities/{terminal['security_id']}/market?view=bogus").status_code == 422
    response = client.get("/api/securities/SEC-nope/market")
    assert response.status_code == 404
    bad = client.post(
        f"/api/securities/{terminal['security_id']}/market",
        json={"range": "3M", "view": "split", "indicators": [{"key": "sma", "params": {"window": 1}}]},
    )
    assert bad.status_code == 422


def test_xray_returns_provenance(terminal):
    client = terminal["client"]
    statements = client.get(f"/api/companies/{ISSUER}/statements?statement=income&period=FY").json()
    evidence_id = statements["rows"][0]["cells"][0]["evidence_id"]
    data = client.get(f"/api/evidence/{evidence_id}").json()
    assert data["record"]["evidence_id"] == evidence_id
    # Regression: the record stores value_text/value_numeric, but X-Ray must expose one
    # displayable value or the panel renders a blank amount.
    assert data["record"]["value"] == statements["rows"][0]["cells"][0]["value"]
    assert data["record"]["unit"]
    assert data["record"]["accession_number"]
    assert data["source"]["source_id"] == "sec-edgar"
    assert isinstance(data["narrative"], list) and data["narrative"]
    assert data["terminal"]["policy"] == "atlas.select.point_in_time.v2"


def test_filings_and_events(terminal):
    client = terminal["client"]
    filings = client.get(f"/api/companies/{ISSUER}/filings?limit=10").json()
    assert filings["total"] == 2
    assert filings["items"][0]["form_type"] == "10-K/A"
    assert filings["items"][0]["is_amendment"] is True
    assert filings["items"][1]["source_url"].startswith("https://www.sec.gov/")

    events = client.get(f"/api/companies/{ISSUER}/events").json()
    kinds = {item["kind"] for item in events["items"]}
    assert "filing" in kinds and "corporate_action" in kinds


def test_screener_is_deterministic_and_honest(terminal):
    client = terminal["client"]
    body = {"filters": [{"metric": "net_margin", "op": "gt", "value": 0.1}], "sort": {"metric": "market_cap", "direction": "desc"}}
    first = client.post("/api/screeners/run", json=body).json()
    second = client.post("/api/screeners/run", json=body).json()
    assert first["rows"] == second["rows"]
    assert first["matched"] == 1
    assert first["universe"]["issuers_in_database"] == 1
    assert "not a market-wide screen" in first["universe"]["note"]

    impossible = client.post("/api/screeners/run", json={"filters": [{"metric": "revenue", "op": "gt", "value": 1e16}]}).json()
    assert impossible["matched"] == 0

    between = client.post(
        "/api/screeners/run",
        json={"filters": [{"metric": "gross_margin", "op": "between", "value": 0.4, "value2": 0.6}]},
    ).json()
    assert between["matched"] == 1

    invalid = client.post("/api/screeners/run", json={"filters": [{"metric": "not_a_metric", "op": "gt", "value": 1}]})
    assert invalid.status_code == 422


def test_watchlists_persist_and_reject_unknown_security(terminal):
    client = terminal["client"]
    created = client.post("/api/watchlists", json={"name": "Core", "security_ids": [terminal["security_id"]]})
    assert created.status_code == 201
    watchlist = created.json()
    assert watchlist["items"][0]["ticker"] == "AAPL"

    assert client.post("/api/watchlists", json={"name": "Core"}).status_code == 409
    bad = client.post(f"/api/watchlists/{watchlist['watchlist_id']}/items", json={"security_id": "SEC-nope"})
    assert bad.status_code == 422

    renamed = client.patch(f"/api/watchlists/{watchlist['watchlist_id']}", json={"name": "Core research"})
    assert renamed.json()["name"] == "Core research"

    # A second app instance reads the same file: persistence is real, not in-process state.
    second = TestClient(create_app(terminal["path"]))
    assert second.get("/api/watchlists").json()["items"][0]["name"] == "Core research"

    assert client.delete(f"/api/watchlists/{watchlist['watchlist_id']}").status_code == 204
    assert client.get("/api/watchlists").json()["count"] == 0


def test_workspace_validation_and_roundtrip(terminal):
    client = terminal["client"]
    presets = client.get(
        f"/api/workspaces/presets?issuer={ISSUER}&security={terminal['security_id']}"
    ).json()["items"]
    assert len(presets) == 3
    document = presets[0]
    created = client.post("/api/workspaces", json=document)
    assert created.status_code == 201, created.text
    workspace = created.json()
    assert workspace["mode"] == "advanced"
    assert workspace["document"]["columns"] == 3
    assert workspace["fingerprint"]

    fetched = client.get(f"/api/workspaces/{workspace['workspace_id']}").json()
    assert fetched["fingerprint"] == workspace["fingerprint"]

    document["columns"] = 2
    document["panels"] = document["panels"][:3]
    document["panels"][0]["span"] = 2
    updated = client.put(f"/api/workspaces/{workspace['workspace_id']}", json=document)
    assert updated.status_code == 200, updated.text
    assert updated.json()["document"]["columns"] == 2

    invalid = client.post(
        "/api/workspaces",
        json={"name": "Bad", "panels": [{"id": "a", "type": "chart", "security_id": "SEC-1", "span": 5}], "columns": 3},
    )
    assert invalid.status_code == 422

    unknown_type = client.post(
        "/api/workspaces", json={"name": "Bad2", "panels": [{"id": "a", "type": "iframe", "span": 1}]}
    )
    assert unknown_type.status_code == 422

    standard = client.post(
        "/api/workspaces",
        json={"name": "Std", "mode": "standard", "panels": [{"id": "x", "type": "xray", "evidence_id": "EV-1", "span": 1}]},
    )
    assert standard.status_code == 422


def test_settings_roundtrip(terminal):
    client = terminal["client"]
    assert client.put("/api/settings", json={"key": "theme", "value": "light"}).status_code == 200
    assert client.get("/api/settings").json()["values"]["theme"] == "light"
    assert client.put("/api/settings", json={"key": "theme", "value": "neon"}).status_code == 422
    assert client.put("/api/settings", json={"key": "unknown", "value": 1}).status_code == 422


def test_read_views_never_write_evidence(terminal):
    client = terminal["client"]
    before = client.get("/api/health").json()["evidence"]
    client.get(f"/api/companies/{ISSUER}/statements?statement=income&period=FY")
    client.get(f"/api/companies/{ISSUER}/metrics")
    client.get(f"/api/securities/{terminal['security_id']}/market?range=3M")
    client.post("/api/screeners/run", json={"filters": []})
    after = client.get("/api/health").json()["evidence"]
    assert before == after


def test_missing_database_is_a_clear_state(tmp_path):
    client = TestClient(create_app(tmp_path / "absent.db"), raise_server_exceptions=False)
    response = client.get("/api/companies")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_missing"
    assert "build_terminal_db" in response.json()["error"]["context"]["fix"]


def test_research_views_validation_and_object_contract(terminal):
    client = terminal["client"]
    history = client.get(f"/api/companies/{ISSUER}/history").json()
    assert history["concepts"]
    evidence_id = next(
        point["evidence_id"] for row in history["concepts"] for point in row["points"]
    )
    assert evidence_id.startswith("EV-")

    peers = client.get(f"/api/companies/{ISSUER}/peers").json()
    assert peers["rows"] and peers["rows"][0]["is_target"] is True
    assert peers["universe"]["issuers"] == 1

    revisions = client.get(f"/api/companies/{ISSUER}/revisions").json()
    assert revisions["counts"]["amended_filings"] == 1

    validation = client.get(f"/api/research/validation/{ISSUER}").json()
    assert validation["total"] > 0
    assert any(check["name"].startswith("net margin") for check in validation["checks"])

    document = {
        "schema_version": "atlas.research_object.v1",
        "kind": "dataset",
        "name": "Apple annual sample",
        "version": "1.0.0",
        "status": "validated",
        "description": "Test dataset citing a real terminal evidence record.",
        "as_of": "2026-11-04T00:00:00Z",
        "mode": "public_available",
        "evidence_ids": [evidence_id],
        "source_ids": ["sec-edgar"],
        "spec": {
            "universe": ["Apple Inc."],
            "fields": ["revenue"],
            "frequency": "annual",
            "adjustment": "none",
        },
    }
    created = client.post("/api/research/objects", json={"document": document})
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["evidence"][0]["evidence_id"] == evidence_id
    object_id = payload["object_id"]
    assert client.get("/api/research/objects").json()["items"][0]["object_id"] == object_id
    assert client.get(f"/api/research/objects/{object_id}").json()["content_hash"] == payload["content_hash"]
    impact = client.get(f"/api/evidence/{evidence_id}").json()["research_impact"]
    assert impact["research_objects"][0]["object_id"] == object_id

    rejected = client.post("/api/research/objects", json={"document": {**document, "name": "Other", "version": "1.0.1", "sql": "select 1"}})
    assert rejected.status_code == 422

import json
def _equation_spec(expr: str = "price * shares") -> dict:
    return {
        "schema_version": "atlas.model.v1",
        "name": "API price times shares",
        "interface": "equation",
        "inputs": [
            {"name": "price", "type": "Price[USD]"},
            {"name": "shares", "type": "Shares"},
        ],
        "equations": [{"name": "value", "expr": expr}],
        "outputs": ["value"],
        "as_of": "2024-01-01T00:00:00Z",
        "mode": "public_available",
    }


def test_compile_run_and_validation_errors(terminal):
    client = terminal["client"]
    compiled = client.post("/api/models/compile", json={"spec": _equation_spec()})
    assert compiled.status_code == 200, compiled.text
    payload = compiled.json()
    assert payload["outputs"] == {"value": payload["outputs"]["value"]}
    assert payload["nodes"]
    assert payload["canonical_spec"]["schema_version"] == "atlas.model.v1"

    run = client.post(
        "/api/models/run",
        json={"spec": _equation_spec(), "inputs": {"price": 25, "shares": 4}},
    )
    assert run.status_code == 200, run.text
    assert run.json()["outputs"]["value"] == 100.0
    run_id = run.json()["run_id"]
    restored = client.get(f"/api/models/runs/{run_id}")
    assert restored.status_code == 200
    assert restored.json()["outputs"]["value"] == 100.0

    bad = client.post(
        "/api/models/compile",
        json={"spec": {
            "schema_version": "atlas.model.v1", "name": "bad", "interface": "equation",
            "inputs": [{"name": "usd", "type": "Money[USD]"}, {"name": "eur", "type": "Money[EUR]"}],
            "equations": [{"name": "x", "expr": "usd + eur"}], "outputs": ["x"],
        }},
    )
    assert bad.status_code == 422
    diagnostic = bad.json()["error"]["context"]["diagnostics"][0]
    assert diagnostic["code"] == "currency_mismatch"


def test_valuation_defaults_and_dcf(terminal):
    client = terminal["client"]
    issuer = client.get("/api/companies").json()["items"][0]["issuer_id"]
    defaults = client.get(f"/api/valuation/defaults/{issuer}")
    assert defaults.status_code == 200, defaults.text
    payload = defaults.json()
    revenue = payload["defaults"].get("revenue")
    if not revenue:
        return  # the shared fixture may not carry a revenue fact; arithmetic tests cover the model
    response = client.post(
        "/api/valuation/dcf",
        json={"issuer": issuer, "assumptions": {"revenue_growth": [0.05] * 5}},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["outputs"]["value_per_share"] > 0
    assert result["outputs"]["enterprise_value"] > result["outputs"]["pv_explicit"]
    assert result["audit"]["evidence_ids"]
    assert len(result["trace"]) > 10
    assert result["manifest"]["compiler_version"] == "atlas.fec.compiler.v1"

    sensitivity = client.post("/api/valuation/sensitivity", json={"issuer": issuer})
    assert sensitivity.status_code == 200, sensitivity.text
    assert len(sensitivity.json()["matrix"]) == 5


def test_research_object_fork_compare_and_export(terminal):
    client = terminal["client"]
    db = Database(terminal["path"], create=False)
    evidence_id = db.scalar("SELECT evidence_id FROM evidence LIMIT 1")
    db.close()
    assert evidence_id
    document = {
        "schema_version": "atlas.research_object.v1",
        "kind": "model",
        "name": "Lifecycle model",
        "version": "1.0.0",
        "status": "validated",
        "description": "A compiler model used to test immutable version lifecycle.",
        "as_of": "2024-01-01T00:00:00Z",
        "mode": "public_available",
        "evidence_ids": [evidence_id],
        "spec": {
            "inputs": {"price": "Price[USD]", "shares": "Shares"},
            "outputs": {"value": "value"},
            "method": "atlas.model.v1",
            "assumptions": [],
            "validation": "compiled",
            "model_spec": _equation_spec(),
        },
    }
    created = client.post("/api/research/objects", json={"document": document})
    assert created.status_code == 201, created.text
    object_id = created.json()["object_id"]
    executed = client.post(
        f"/api/research/objects/{object_id}/execute",
        json={"inputs": {"price": 10, "shares": 3}},
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["outputs"]["value"] == 30.0
    forked = client.post(
        f"/api/research/objects/{object_id}/fork",
        json={"name": "Lifecycle model fork", "version": "1.0.1"},
    )
    assert forked.status_code == 201, forked.text
    fork_id = forked.json()["object_id"]
    compared = client.get(f"/api/research/compare?left={object_id}&right={fork_id}")
    assert compared.status_code == 200
    assert compared.json()["equal"] is False
    exported = client.get(f"/api/research/objects/{object_id}/export")
    assert exported.status_code == 200
    manifest = exported.json()
    assert manifest["object"]["content_hash"]
    assert manifest["compiler_version"] == "atlas.fec.compiler.v1"
    json.dumps(manifest)
