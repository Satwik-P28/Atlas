"""Modelled publication-time bounds must never become verified availability.

Branch integration introduced a modelled public-release instant: EDGAR acceptance plus a
fixed publication lag. That bound is usable for ordering and for excluding evidence at a
cutoff, because the document was certainly public at or before it. It is *not* an observed
instant, and no human or machine consumer may read it back as one.

These tests pin the three places the bound surfaces — the filing resolver, the answer
engine's certificate, and the corpus record — so a future refactor cannot quietly upgrade
an estimate into a fact.
"""

from __future__ import annotations

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research.certificate import build_certificate
from atlas.research.filing_evidence import (
    DOC_NOT_AT_CUTOFF,
    DOC_UNKNOWN_AVAILABILITY,
    MODELLED_AVAILABILITY_BASIS,
    resolve_document,
)
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver, bind
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

ISSUER = "ISS-BOUND"
ACCESSION = "0000000034-24-000102"
BOUND = "2023-03-15T00:00:00Z"

HTML = b"""<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>($ in millions)</p>
<table>
<tr><td>Year</td><td>2022</td></tr>
<tr><td>Net sales</td><td>34,229</td></tr>
</table></body></html>"""


def _database(*, basis: str, precision: str) -> Database:
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000034", "Bound Fixture Co", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=HTML,
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{ACCESSION}.htm")
    database.execute(
        "UPDATE knowledge_document SET availability_time = ?, availability_precision = ?, "
        "availability_basis = ?, availability_model = 'acceptance+lag'",
        (BOUND, precision, basis))
    return database


def _row() -> dict:
    return {
        "cik": "0000000034",
        "accession_number": ACCESSION,
        "primary_document": "primary.htm",
        "filed_date": "2023-02-10",
        "acceptance_datetime": "2023-02-10T12:00:00Z",
        "form_type": "10-K",
        "is_amendment": 0,
        "amends_accession": None,
        "period_of_report": "2022-12-31",
    }


@pytest.fixture()
def modelled() -> Database:
    return _database(basis=f"{MODELLED_AVAILABILITY_BASIS}_v1", precision="unknown")


def test_modelled_bound_is_reported_as_a_bound_and_never_as_a_date(modelled: Database) -> None:
    payload = resolve_document(modelled, row=_row(), cutoff="2024-01-01T23:59:59Z",
                               mode_historical=True)
    assert payload["status"] == "resolved"
    assert payload["availability_is_upper_bound"] is True
    assert payload["availability_precision"] == "modeled_bound"
    # The stored precision stays "unknown": the bound cannot be read back as observed.
    assert payload["availability_stored_precision"] == "unknown"
    assert payload["availability_basis"].startswith(MODELLED_AVAILABILITY_BASIS)
    assert "upper bound" in payload["availability_note"]


def test_a_cutoff_before_the_bound_still_excludes_the_document(modelled: Database) -> None:
    payload = resolve_document(modelled, row=_row(), cutoff="2023-03-01T00:00:00Z",
                               mode_historical=True)
    assert payload["status"] == DOC_NOT_AT_CUTOFF
    assert payload["passage_status"] == "not_available_at_cutoff"


def test_unknown_availability_without_a_model_is_never_promoted() -> None:
    database = _database(basis="sec_submissions:no_publication_time", precision="unknown")
    payload = resolve_document(database, row=_row(), cutoff="2024-01-01T23:59:59Z",
                               mode_historical=True)
    assert payload["status"] == DOC_UNKNOWN_AVAILABILITY
    assert payload["availability_is_upper_bound"] is False
    assert payload["availability_precision"] == "unknown"


def test_a_certificate_over_a_modelled_source_says_so(modelled: Database) -> None:
    engine = KnowledgeEngine(modelled)
    resolver = ConceptResolver(engine)
    cutoff = "2024-01-01T23:59:59Z"
    resolution = resolver.resolve(ISSUER, "revenue", "2022", cutoff)
    binding = bind(resolution, ISSUER, "revenue")
    assert binding is not None, resolution.as_dict()
    assert binding.availability_precision == "unknown"
    answer = FinancialAnswerEngine(engine).lookup_bound(binding, cutoff)
    assert answer["outcome"] == "answered"
    certificate = build_certificate(
        research_question="What were net sales in 2022?",
        answer=answer,
        bindings=[binding],
        cutoff=cutoff,
    )
    assert certificate["input_bindings"][0]["availability_is_estimated"] is True
    assert certificate["selected_sources"][0]["availability_is_estimated"] is True
    assert any("modelled upper bound" in item for item in certificate["limitations"])


def test_an_observed_instant_is_not_flagged_as_estimated() -> None:
    database = _database(basis="sec_submissions.acceptance_datetime", precision="exact")
    database.execute("UPDATE knowledge_document SET availability_time = '2023-02-10T12:00:00Z'")
    payload = resolve_document(database, row=_row(), cutoff="2024-01-01T23:59:59Z",
                               mode_historical=True)
    assert payload["status"] == "resolved"
    assert payload["availability_is_upper_bound"] is False
    assert payload["availability_precision"] == "exact"
