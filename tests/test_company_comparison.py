"""Cross-company comparison: real filings, real cells, explicit incompatibilities.

The comparison is only worth having if it refuses to compare things that are not comparable.
These tests build two issuers from real ingested filings and check both directions: a valid
comparison carries evidence identity, and a scale, currency, scope or coverage difference is
reported as a blocking finding instead of being normalised away.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")

from fastapi.testclient import TestClient  # noqa: E402

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.comparison import (  # noqa: E402
    BLOCKING_FINDINGS,
    availability,
    compatibility_findings,
)
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.terminal.api import create_app  # noqa: E402

LEFT = "ISS-CMP-LEFT"
RIGHT = "ISS-CMP-RIGHT"
CUTOFF = "2024-01-01"
LOCAL = {"host": "127.0.0.1:8000"}


def _html(sales: str, scale: str = "($ in millions)") -> bytes:
    return f"""<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>{scale}</p>
<table>
<tr><td>Year</td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>{sales}</td><td>9,999</td></tr>
<tr><td>Gross profit</td><td>3,000</td><td>2,500</td></tr>
</table></body></html>""".encode()


def _seed(path, *, right_sales: str = "50,000", right_scale: str = "($ in millions)"):
    database = Database(path)
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    for issuer_id, cik, name in ((LEFT, "0000000101", "Left Fixture Co"),
                                 (RIGHT, "0000000102", "Right Fixture Co")):
        database.execute(
            "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
            "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
            (issuer_id, cik, name, now, now))
    engine = KnowledgeEngine(database)
    engine.ingest_document(
        issuer_id=LEFT, accession="0000000101-24-000001", form_type="10-K", html=_html("34,229"),
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url="https://www.sec.gov/Archives/left.htm")
    engine.ingest_document(
        issuer_id=RIGHT, accession="0000000102-24-000001", form_type="10-K",
        html=_html(right_sales, right_scale), filed_date="2023-02-11",
        acceptance_time="2023-02-11T12:00:00Z", period_of_report="2022-12-31",
        rights="public_domain",
        primary_document_url="https://www.sec.gov/Archives/right.htm")
    database.execute(
        "UPDATE knowledge_document SET availability_precision = 'exact', "
        "availability_basis = 'sec_submissions.acceptance_datetime'")
    database.close()
    return path


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(_seed(tmp_path / "comparison.db")),
                      raise_server_exceptions=False)


@pytest.fixture()
def scaled_client(tmp_path):
    """The right-hand company reports in thousands, so the digits are not comparable."""
    return TestClient(create_app(_seed(tmp_path / "scaled.db", right_scale="($ in thousands)")),
                      raise_server_exceptions=False)


def _compare(client: TestClient, **over):
    body = {"issuers": [LEFT, RIGHT], "concepts": ["revenue"], "period": "2022",
            "as_of": CUTOFF}
    body.update(over)
    return client.post("/api/research/comparison", headers=LOCAL, json=body)


def test_comparable_figures_keep_their_evidence_identity(client: TestClient) -> None:
    response = _compare(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "atlas.company_comparison.v1"
    assert body["comparable"] is True
    block = body["concepts"][0]
    assert block["concept"] == "revenue"
    assert block["statement"]
    rows = {row["issuer_id"]: row for row in block["rows"]}
    assert Decimal(rows[LEFT]["value"]) == Decimal("34229")
    assert Decimal(rows[RIGHT]["value"]) == Decimal("50000")
    for row in rows.values():
        assert row["status"] == "resolved"
        assert row["currency"] == "USD"
        assert row["evidence"]["cell_id"]
        assert row["evidence"]["accession"]
        assert row["evidence"]["source_table_sha256"]
        assert row["availability"]["availability_precision"] == "exact"
        assert row["availability"]["is_estimated"] is False
    # A comparison is a stored-figures comparison, and it says so.
    assert "not an industry index" in body["note"]


def test_a_different_reported_scale_is_blocking(scaled_client: TestClient) -> None:
    response = _compare(scaled_client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["comparable"] is False
    block = body["concepts"][0]
    codes = {finding["code"] for finding in block["findings"]}
    assert "scale_mismatch" in codes
    assert block["comparable"] is False
    scales = {row["scale"] for row in block["rows"]}
    assert len(scales) == 2


def test_an_unknown_company_is_a_row_and_a_coverage_finding(client: TestClient) -> None:
    response = _compare(client, issuers=[LEFT, "NOT-A-COMPANY"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["comparable"] is False
    rows = {row["requested"]: row for row in body["concepts"][0]["rows"]}
    assert rows["NOT-A-COMPANY"]["status"] == "unknown_issuer"
    assert rows["NOT-A-COMPANY"]["value"] is None
    assert rows[LEFT]["status"] == "resolved"
    codes = {finding["code"] for finding in body["concepts"][0]["findings"]}
    assert {"partial_coverage", "insufficient_coverage"} <= codes


def test_an_unsupported_concept_is_refused(client: TestClient) -> None:
    response = _compare(client, concepts=["ebitda_magic"])
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["context"]["unsupported"] == ["ebitda_magic"]
    assert "revenue" in error["context"]["supported"]


def test_one_company_is_not_a_comparison(client: TestClient) -> None:
    response = _compare(client, issuers=[LEFT])
    assert response.status_code == 422


def test_findings_classify_currency_scope_and_coverage() -> None:
    def row(**over):
        base = {"issuer_id": "ISS-A", "status": "resolved", "value": "1", "currency": "USD",
                "entity_scope": "consolidated", "scale": 6, "statement_family": "income",
                "period": "2022"}
        base.update(over)
        return base

    findings = compatibility_findings([
        row(),
        row(issuer_id="ISS-B", currency="EUR", entity_scope="parent_only"),
    ])
    by_code = {finding["code"]: finding for finding in findings}
    assert by_code["currency_mismatch"]["severity"] == "blocking"
    assert by_code["entity_scope_mismatch"]["severity"] == "blocking"
    assert {"currency_mismatch", "entity_scope_mismatch"} <= BLOCKING_FINDINGS
    assert "partial_coverage" not in by_code


def test_availability_matches_the_answer_surface_semantics() -> None:
    observed = availability("exact", "2023-02-10T12:00:00Z")
    modelled = availability("unknown", "2023-03-15T00:00:00Z")
    assert observed["is_estimated"] is False
    assert modelled["is_estimated"] is True
    assert "modelled upper bound" in modelled["note"]
