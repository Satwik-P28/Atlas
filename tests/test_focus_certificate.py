"""Research certificate construction, independent verification, and adversarial mutations."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research.certificate import build_certificate, verify_certificate_payload
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver, bind
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

ISSUER = "ISS-FOCUS-CERT"
ACCESSION = "0000000031-24-000099"

HTML = """<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p>
<table>
<tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table></body></html>"""


def _engine() -> tuple[Database, FinancialAnswerEngine, ConceptResolver]:
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000031", "Fixture Co", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=HTML,
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{ACCESSION}.htm")
    knowledge = KnowledgeEngine(database)
    return database, FinancialAnswerEngine(knowledge), ConceptResolver(knowledge)


def _certificate():
    _db, answers, resolver = _engine()
    resolution = resolver.resolve(ISSUER, "revenue", "2022", "2024-01-01T00:00:00Z")
    binding = bind(resolution, ISSUER, "revenue")
    assert binding is not None
    assert binding.scale == 6
    answer = answers.lookup_bound(binding, "2024-01-01T00:00:00Z")
    assert answer["outcome"] == "answered"
    certificate = build_certificate(
        research_question="What were net sales in 2022?",
        answer=answer, bindings=[binding], cutoff="2024-01-01T00:00:00Z",
    )
    trusted = {ACCESSION: {"sha256": binding.source_table_sha256,
                           "availability_time": binding.availability_time,
                           "body_present": True}}
    return certificate, trusted, binding


def test_certificate_round_trip_verifies():
    certificate, trusted, _binding = _certificate()
    result = verify_certificate_payload(certificate, trusted_sources=trusted)
    assert result["status"] == "valid"
    assert result["problems"] == []


@pytest.mark.parametrize("mutator,expected", [
    (lambda c: c["issuer_identity"].__setitem__("issuer_id", "ISS-OTHER") or c, "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("accession", "0000000000-00-000000") or c,
     "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("period", "2019") or c, "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("currency", "EUR") or c, "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("scale", 0) or c, "certificate_fingerprint_mismatch"),
    (lambda c: c["result"].__setitem__("value", "1.00") or c, "certificate_fingerprint_mismatch"),
    (lambda c: c["typed_computation"].__setitem__("formula", "hacked") or c, "certificate_fingerprint_mismatch"),
    (lambda c: c["typed_computation"].__setitem__("operator_version", "0.0.0") or c,
     "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("source_table_sha256", "0" * 64) or c,
     "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("availability_time", "2099-01-01T00:00:00Z") or c,
     "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("entity_scope", "segment") or c,
     "certificate_fingerprint_mismatch"),
    (lambda c: c["input_bindings"][0].__setitem__("row", 99) or c, "certificate_fingerprint_mismatch"),
])
def test_adversarial_mutations_fail(mutator, expected):
    certificate, trusted, _binding = _certificate()
    mutated = mutator(copy.deepcopy(certificate))
    # Recompute fingerprint only when we mutate after issue — attackers who keep the old
    # fingerprint must fail fingerprint check; attackers who resign must fail arithmetic/identity.
    result = verify_certificate_payload(mutated, trusted_sources=trusted)
    assert result["status"] == "invalid"
    assert expected in result["problems"] or "result_mismatch" in result["problems"] \
        or "source_hash_mismatch" in result["problems"] or "future_evidence" in result["problems"]


def test_resigned_value_mutation_fails_arithmetic():
    certificate, trusted, _binding = _certificate()
    mutated = copy.deepcopy(certificate)
    mutated["result"]["value"] = "99999.00"
    body = {key: value for key, value in mutated.items() if key != "certificate_fingerprint"}
    from atlas.research.certificate import fingerprint
    mutated["certificate_fingerprint"] = fingerprint(body)
    result = verify_certificate_payload(mutated, trusted_sources=trusted)
    assert result["status"] == "invalid"
    assert "result_mismatch" in result["problems"]


def test_historical_cutoff_refuses_binding():
    _db, answers, resolver = _engine()
    resolution = resolver.resolve(ISSUER, "revenue", "2022", "2024-01-01T00:00:00Z")
    binding = bind(resolution, ISSUER, "revenue")
    answer = answers.lookup_bound(binding, "2017-01-01T00:00:00Z")
    assert answer["outcome"] == "abstained"
    assert "future_evidence" in answer["context"]["problems"]


def test_cli_verify_certificate(tmp_path: Path):
    certificate, _trusted, _binding = _certificate()
    path = tmp_path / "cert.json"
    path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    completed = subprocess.run(
        [sys.executable, "-m", "atlas", "verify-certificate", str(path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "valid"
