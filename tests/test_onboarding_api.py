"""Guided onboarding is tested through the HTTP surface it actually ships.

The important properties are that preview writes nothing, import requires an explicit
confirmation, duplicates are reported rather than merged silently, and the declared licence
travels with the stored source. A user-supplied file is never presented as Atlas-owned data.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")

from fastapi.testclient import TestClient  # noqa: E402

from atlas.entities.master import SecurityMaster  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402
from atlas.terminal.api import create_app  # noqa: E402

LOCAL = {"host": "127.0.0.1:8000"}
MIC = "XNAS"

CSV = """date,open,high,low,close,volume
2024-01-02,100.0,102.0,99.0,101.0,1000
2024-01-03,101.0,103.0,100.0,102.0,1100
2024-01-04,102.0,104.0,101.0,103.0,1200
"""

ADJUSTED_ONLY = """date,Adj Close
2024-01-02,101.0
2024-01-03,102.0
"""


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "onboarding.db"
    database = Database(path)
    database.migrate()
    ensure_default_sources(database)
    master = SecurityMaster(database)
    issuer = master.register_issuer(
        legal_name="Onboarding Co", cik="0000000035", entity_type="corporation",
        sic="3571", fiscal_year_end="1231", source_id="sec-edgar",
    )
    master.ensure_venue(MIC, "Nasdaq", country="US", timezone="America/New_York")
    master.ensure_security(issuer, class_designation="common stock", currency="USD")
    database.close()
    return path


@pytest.fixture()
def client(db_path):
    return TestClient(create_app(db_path), raise_server_exceptions=False)


def _security_id(db_path) -> str:
    database = Database(db_path, create=False)
    try:
        return database.query_one("SELECT security_id FROM security")["security_id"]
    finally:
        database.close()


def _body(db_path, csv: str = CSV, **overrides) -> dict:
    body = {
        "security_id": _security_id(db_path),
        "mic": MIC,
        "csv": csv,
        "source_name": "User broker export",
        "licence": "personal research use; redistribution not granted",
        "currency": "USD",
    }
    body.update(overrides)
    return body


def _bar_count(db_path) -> int:
    database = Database(db_path, create=False)
    try:
        return int(database.scalar("SELECT COUNT(*) FROM bar", default=0) or 0)
    finally:
        database.close()


def test_status_reports_capabilities_it_actually_has(client: TestClient) -> None:
    body = client.get("/api/onboarding/status", headers=LOCAL).json()
    assert body["imports"]["market_csv"]["available"] is True
    assert body["imports"]["fred_alfred"]["available"] is False
    assert "offline" in body["imports"]["fred_alfred"]["note"]
    assert body["imports"]["sec_edgar"]["user_agent_configured"] in {True, False}
    assert body["credentials"]["accepted_by_this_interface"] == []
    assert body["database"]["securities"] == 1


def test_preview_maps_columns_and_writes_nothing(client: TestClient, db_path) -> None:
    response = client.post("/api/onboarding/market/preview", headers=LOCAL,
                           json=_body(db_path))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["wrote_anything"] is False
    assert body["columns"]["date"] == "date"
    assert body["columns"]["close"] == "close"
    assert body["rows_read"] == 3
    assert body["bars_accepted"] == 3
    assert body["coverage"]["first_session"] == "2024-01-02"
    assert body["coverage"]["last_session"] == "2024-01-04"
    assert body["rights"]["redistribution"] == "user_responsibility"
    assert body["rights"]["licence"] == "personal research use; redistribution not granted"
    assert _bar_count(db_path) == 0


def test_an_adjusted_only_file_is_refused_rather_than_stored(
        client: TestClient, db_path) -> None:
    response = client.post("/api/onboarding/market/preview", headers=LOCAL,
                           json=_body(db_path, csv=ADJUSTED_ONLY))
    assert response.status_code in {200, 422}
    if response.status_code == 200:
        body = response.json()
        assert body["adjusted_columns_ignored"] == ["Adj Close"]
        assert any(issue["code"] == "adjusted_column_ignored" for issue in body["issues"])
        assert body["issues"]
    assert _bar_count(db_path) == 0


def test_import_requires_an_explicit_confirmation(client: TestClient, db_path) -> None:
    response = client.post("/api/onboarding/market/import", headers=LOCAL,
                           json=_body(db_path))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "confirmation_required"
    assert _bar_count(db_path) == 0


def test_import_stores_bars_registers_the_source_and_reports_duplicates(
        client: TestClient, db_path) -> None:
    payload = {**_body(db_path), "confirm": True}
    response = client.post("/api/onboarding/market/import", headers=LOCAL, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["wrote_anything"] is True
    assert body["stored"]["inserted"] == 3
    assert _bar_count(db_path) == 3

    database = Database(db_path, create=False)
    try:
        source = database.query_one("SELECT redistribution, licence FROM source WHERE source_id = ?",
                                    (body["source_id"],))
    finally:
        database.close()
    assert source["redistribution"] == "user_responsibility"
    assert "personal research use" in source["licence"]

    again = client.post("/api/onboarding/market/import", headers=LOCAL, json=payload).json()
    assert again["stored"]["inserted"] == 0
    assert again["stored"]["duplicates"] == 3
    assert again["duplicates"]["bars_already_stored_for_series"] == 3
    assert _bar_count(db_path) == 3


def test_unknown_security_is_a_structured_404(client: TestClient, db_path) -> None:
    response = client.post("/api/onboarding/market/preview", headers=LOCAL,
                           json=_body(db_path, security_id="SEC-DOES-NOT-EXIST"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_security"


def test_a_missing_licence_is_refused(client: TestClient, db_path) -> None:
    payload = _body(db_path)
    payload.pop("licence")
    response = client.post("/api/onboarding/market/preview", headers=LOCAL, json=payload)
    assert response.status_code == 422
