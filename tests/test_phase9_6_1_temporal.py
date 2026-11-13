"""Phase 9.6.1 temporal contract tests.

Availability derived from EDGAR acceptance plus a publication lag is a modelled bound. These
tests pin the boundary to the second, pin the labels, and check that the two availability
policies can legitimately disagree without either silently mutating history.
"""

from __future__ import annotations

import pytest

from atlas.core.errors import ValidationError
from atlas.core.temporal import iso, utcnow
from atlas.research.knowledge import SEC_PUBLICATION_LAG_SECONDS, KnowledgeEngine
from atlas.research.knowledge_claims import build_document_claim
from atlas.storage.db import Database

ISSUER = "ISS-T-A"
ACCESSION = "0000000009-24-000001"
ACCEPTED = "2024-03-01T12:00:00.000Z"
AVAILABLE = "2024-03-01T12:15:00Z"
DOC = ("<html><body><h1>Item 1A. Risk Factors</h1>"
       "<p>We face customer concentration risk because two customers account for most revenue."
       "</p></body></html>")


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000009", "Temporal Corp", now, now))
    return database


def ingest(db: Database, *, accepted: str | None = ACCEPTED, html: str = DOC,
           accession: str = ACCESSION) -> dict:
    return KnowledgeEngine(db).ingest_document(
        issuer_id=ISSUER, accession=accession, form_type="10-K", html=html,
        filed_date="2024-03-01", acceptance_time=accepted, period_of_report="2023-12-31",
        rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{accession}.htm")


def test_lag_is_modelled_not_exact(db: Database):
    document = ingest(db)
    assert document["availability_time"] == AVAILABLE
    assert document["availability_precision"] == "unknown"
    assert document["availability_model"] == "sec_acceptance_plus_publication_lag_v1"
    assert document["acceptance_time"] == ACCEPTED
    assert document["public_availability_time"] is None
    assert SEC_PUBLICATION_LAG_SECONDS == 900


def test_boundary_second_is_inclusive_and_one_second_earlier_is_not(db: Database):
    ingest(db)
    engine = KnowledgeEngine(db)
    at_boundary = engine.search("customer concentration", issuer_id=ISSUER, cutoff=AVAILABLE)
    assert at_boundary["count"] > 0
    before = engine.search("customer concentration", issuer_id=ISSUER,
                           cutoff="2024-03-01T12:14:59Z")
    assert before["count"] == 0
    assert before["excluded"]["later_than_cutoff"] >= 1


def test_daily_policy_verifies_modelled_bound_but_intraday_refuses(db: Database):
    ingest(db)
    engine = KnowledgeEngine(db)
    daily = build_document_claim(engine, issuer_id=ISSUER, cutoff="2024-06-01T00:00:00.000Z",
                                 key="concentration", question="customer concentration risk",
                                 epistemic_status="observed_fact")
    assert daily["verification"]["outcome"] == "verified"
    codes = {item["code"] for item in daily["verification"]["diagnostics"]}
    assert "availability_modeled_bound" in codes

    intraday = build_document_claim(engine, issuer_id=ISSUER, cutoff="2024-06-01T00:00:00.000Z",
                                    key="concentration", question="customer concentration risk",
                                    epistemic_status="observed_fact", as_of_precision="intraday")
    assert intraday["verification"]["outcome"] == "unverifiable_historical_availability"


def test_date_only_metadata_is_never_treated_as_available_in_time(db: Database):
    document = ingest(db, accepted=None)
    assert document["availability_precision"] == "date"
    assert document["availability_model"] == "sec_filing_date_v1"
    claim = build_document_claim(KnowledgeEngine(db), issuer_id=ISSUER,
                                 cutoff="2024-06-01T00:00:00.000Z", key="concentration",
                                 question="customer concentration risk",
                                 epistemic_status="observed_fact")
    assert claim["verification"]["outcome"] == "unverifiable_historical_availability"


def test_reingestion_is_immutable(db: Database):
    first = ingest(db)
    again = ingest(db)
    assert again["document_id"] == first["document_id"]
    with pytest.raises(ValidationError):
        ingest(db, html=DOC.replace("two customers", "three customers"), accession=ACCESSION)


def test_corpus_growth_does_not_mutate_earlier_snapshot(db: Database):
    ingest(db)
    engine = KnowledgeEngine(db)
    cutoff = "2024-03-01T12:16:00Z"
    before = engine.search("customer concentration", issuer_id=ISSUER, cutoff=cutoff)
    ingest(db, accession="0000000009-24-000002", accepted="2024-03-05T12:00:00Z",
           html="<html><body><p>Customer concentration risk increased in 2024.</p></body></html>")
    after = engine.search("customer concentration", issuer_id=ISSUER, cutoff=cutoff)
    assert [r["unit_id"] for r in before["results"]] == [r["unit_id"] for r in after["results"]]


def test_availability_policies_can_differ_without_corruption(db: Database):
    ingest(db)
    engine = KnowledgeEngine(db)
    cutoff = "2024-03-01T12:20:00.000Z"
    public = engine.search("customer concentration", issuer_id=ISSUER, cutoff=cutoff,
                           policy="public_available")
    ingested = engine.search("customer concentration", issuer_id=ISSUER, cutoff=cutoff,
                             policy="atlas_ingested")
    assert public["count"] > 0
    # The document was ingested after this cutoff even though it was publicly available.
    assert ingested["count"] == 0
