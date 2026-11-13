"""Phase 9.6.1 security and recovery: untrusted source content and bounded inputs."""

from __future__ import annotations

import gzip

import pytest

from atlas.core.errors import ValidationError
from atlas.core.temporal import iso, utcnow
from atlas.research import knowledge
from atlas.research.knowledge import KnowledgeEngine, extract_units, normalise_document
from atlas.research.knowledge_claims import build_document_claim, verify_document_claim
from atlas.storage.db import Database

ISSUER = "ISS-T-S"
ACCESSION = "0000000010-24-000001"
DOC = ("<html><body><h1>Item 1A. Risk Factors</h1>"
       "<p>We face customer concentration risk.</p></body></html>")


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
        (ISSUER, "0000000010", "Secure Corp", now, now))
    return database


def ingest(db: Database, html: str = DOC, accession: str = ACCESSION) -> dict:
    return KnowledgeEngine(db).ingest_document(
        issuer_id=ISSUER, accession=accession, form_type="10-K", html=html,
        filed_date="2024-03-01", acceptance_time="2024-03-01T12:00:00Z",
        period_of_report="2023-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{accession}.htm")


def test_corrupted_passage_cannot_verify_a_claim(db: Database):
    ingest(db)
    engine = KnowledgeEngine(db)
    claim = build_document_claim(engine, issuer_id=ISSUER, cutoff="2024-06-01T00:00:00Z",
                                 key="concentration", question="customer concentration risk",
                                 epistemic_status="observed_fact")
    assert claim["verification"]["outcome"] == "verified"
    unit_id = claim["citations"][0]["unit_id"]
    db.execute("UPDATE knowledge_unit SET body = body || ' amended in place' WHERE unit_id = ?",
               (unit_id,))
    verified = verify_document_claim(engine, claim)
    assert verified["outcome"] != "verified"
    codes = {item["code"] for item in verified["diagnostics"]}
    assert "passage_corruption" in codes


def test_script_content_is_stored_as_data(db: Database):
    document = ingest(db, html="<html><body><script>alert('x')</script>"
                               "<p>We face customer concentration risk.</p></body></html>")
    text, _ = normalise_document(extract_units(
        "<html><body><script>alert('x')</script><p>We face customer concentration risk.</p></body></html>"))
    body = text
    assert "<script" not in body.lower()
    assert "alert(" not in body.lower()


def test_oversized_document_is_rejected(db: Database, monkeypatch):
    monkeypatch.setattr(knowledge, "MAX_DOCUMENT_BYTES", 50)
    with pytest.raises(ValidationError):
        ingest(db)


def test_truncated_gzip_is_rejected():
    payload = gzip.compress(DOC.encode())
    with pytest.raises(Exception):
        knowledge._decoded(payload[: len(payload) // 2], "gzip")


def test_query_resource_exhaustion_is_bounded(db: Database):
    ingest(db)
    engine = KnowledgeEngine(db)
    with pytest.raises(ValidationError):
        engine.search(" ".join(f"term{i}" for i in range(knowledge.MAX_QUERY_TERMS + 20)))
