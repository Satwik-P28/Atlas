"""The answer and certificate API is exercised through the real application.

The certificates here are built by the server from a real ingested filing, then verified by
the server's independent verifier. The tests also pin the availability rule: a document
whose public-release instant was modelled rather than observed can still be cited, but the
answer and the certificate must both mark that availability as estimated.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")

from fastapi.testclient import TestClient  # noqa: E402

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.terminal.api import create_app  # noqa: E402

ISSUER = "ISS-ANSWER-API"
ACCESSION = "0000000033-24-000101"
CUTOFF = "2024-01-01"
LOCAL = {"host": "127.0.0.1:8000"}

HTML = b"""<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>($ in millions)</p>
<table>
<tr><td>Year</td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table></body></html>"""


def _database(path) -> Database:
    database = Database(path)
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000033", "Answer Fixture Co", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=HTML,
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{ACCESSION}.htm")
    return database


def _observed(database: Database) -> Database:
    """Record an observed release instant, covering the non-estimated branch.

    Ingestion always stores a modelled bound (EDGAR acceptance plus a publication lag) with
    precision ``unknown``. A deployment that has an observed instant records it explicitly;
    this fixture models that state so both branches of the availability contract are tested.
    """
    database.execute(
        "UPDATE knowledge_document SET availability_precision = 'exact', "
        "availability_basis = 'sec_submissions.acceptance_datetime', "
        "availability_time = '2023-02-10T12:00:00Z'"
    )
    return database


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "answers.db"
    _observed(_database(path)).close()
    return path


@pytest.fixture()
def client(db_path):
    return TestClient(create_app(db_path), raise_server_exceptions=False)


@pytest.fixture()
def modelled_client(tmp_path):
    """The same corpus, but with an unobserved (modelled) public-release instant."""
    path = tmp_path / "modelled.db"
    database = _database(path)
    database.execute(
        "UPDATE knowledge_document SET availability_precision = 'unknown', "
        "availability_basis = 'sec_acceptance_plus_publication_lag_v1', "
        "availability_time = '2023-03-15T00:00:00Z', availability_model = 'acceptance+30d'"
    )
    database.close()
    return TestClient(create_app(path), raise_server_exceptions=False)


def _resolve(client: TestClient, period: str = "2022", concept: str = "revenue"):
    return client.post("/api/answers/resolve", headers=LOCAL, json={
        "issuer_id": ISSUER, "concept": concept, "period": period, "as_of": CUTOFF,
    })


def test_concept_registry_is_exposed(client: TestClient) -> None:
    response = client.get("/api/answers/concepts", headers=LOCAL)
    assert response.status_code == 200
    body = response.json()
    keys = {item["key"] for item in body["items"]}
    assert {"revenue", "total_assets", "gross_profit"} <= keys
    assert body["count"] == len(body["items"])


def test_answer_resolution_returns_evidence_not_just_a_number(client: TestClient) -> None:
    response = _resolve(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]["outcome"] == "answered"
    assert Decimal(body["answer"]["value"]) == Decimal("34229")
    assert body["evidence"]["accession"] == ACCESSION
    assert body["evidence"]["cell_id"]
    assert body["evidence"]["currency"] == "USD"
    assert body["evidence"]["scale"] == 6
    assert body["availability"]["availability_precision"] == "exact"
    assert body["availability"]["is_estimated"] is False
    assert body["semantics"]["verified_but_not_proven_correct"] is True


def test_an_unresolvable_period_is_a_refusal_with_candidates(client: TestClient) -> None:
    response = _resolve(client, period="2019")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "answer_refused"
    assert "candidates" in error["context"]
    assert error["context"]["reason"]


def test_an_unregistered_concept_is_refused_with_the_supported_list(
        client: TestClient) -> None:
    response = _resolve(client, concept="ebitda_magic")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unsupported_concept"
    assert "revenue" in error["context"]["supported"]


def test_certificate_round_trips_through_the_independent_verifier(
        client: TestClient) -> None:
    response = client.post("/api/answers/certificate", headers=LOCAL, json={
        "issuer_id": ISSUER, "concept": "revenue", "period": "2022", "as_of": CUTOFF,
        "research_question": "What were net sales in 2022?",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    certificate = body["certificate"]
    assert certificate["schema"] == "atlas.research_certificate.v1"
    assert len(certificate["certificate_fingerprint"]) == 64
    assert certificate["input_bindings"][0]["availability_precision"] == "exact"
    assert certificate["input_bindings"][0]["availability_is_estimated"] is False
    assert Decimal(certificate["result"]["value"]) == Decimal("34229")
    assert any("fingerprint proves internal consistency" in item
               for item in certificate["limitations"])

    verified = client.post("/api/certificates/verify", headers=LOCAL,
                           json={"certificate": certificate})
    assert verified.status_code == 200
    report = verified.json()["report"]
    assert report["status"] != "invalid"
    assert report["certificate_fingerprint"] == certificate["certificate_fingerprint"]
    assert report["recomputed_value"]

    tampered = dict(certificate)
    tampered["result"] = {**certificate["result"], "value": "99999"}
    refused = client.post("/api/certificates/verify", headers=LOCAL,
                          json={"certificate": tampered}).json()["report"]
    assert refused["status"] == "invalid"


def test_modelled_availability_is_never_presented_as_exact(modelled_client: TestClient) -> None:
    resolved = _resolve(modelled_client)
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["availability"]["is_estimated"] is True
    assert body["availability"]["availability_precision"] == "unknown"
    assert "modelled upper bound" in body["availability"]["note"]

    certificate = modelled_client.post("/api/answers/certificate", headers=LOCAL, json={
        "issuer_id": ISSUER, "concept": "revenue", "period": "2022", "as_of": CUTOFF,
    }).json()["certificate"]
    binding = certificate["input_bindings"][0]
    assert binding["availability_is_estimated"] is True
    assert binding["availability_precision"] == "unknown"
    assert any("modelled upper bound" in item for item in certificate["limitations"])
    report = modelled_client.post("/api/certificates/verify", headers=LOCAL,
                                 json={"certificate": certificate}).json()["report"]
    assert report["status"] != "invalid"


def test_command_index_points_every_entry_at_real_functionality(
        client: TestClient) -> None:
    response = client.get("/api/command/index", headers=LOCAL)
    assert response.status_code == 200
    body = response.json()
    expected = {"companies", "concepts", "filings", "questions", "models", "strategies",
                "research", "experiments", "workspaces", "packages"}
    assert set(body["categories"]) == expected
    assert body["counts"]["companies"] == 1
    assert body["counts"]["filings"] == 1
    assert body["counts"]["questions"] > 0
    assert body["counts"]["models"] > 0
    for name, items in body["categories"].items():
        for item in items:
            assert item["category"] == name
            assert item["action"]["kind"]
            assert item["label"]
    filing = body["categories"]["filings"][0]
    assert filing["metadata"]["accession"] == ACCESSION
    assert filing["metadata"]["availability_is_estimated"] is False


def test_the_command_index_marks_a_modelled_filing_as_estimated(
        modelled_client: TestClient) -> None:
    body = modelled_client.get("/api/command/index", headers=LOCAL).json()
    filing = body["categories"]["filings"][0]
    assert filing["metadata"]["availability_is_estimated"] is True
