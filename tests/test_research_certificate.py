"""Research certificates and strict source verification (v10.0.0).

The adversarial cases are the point of this file. Each one keeps the certificate internally
consistent — the attacker recomputes every hash the certificate owns — so that only evidence the
certificate does not control can detect the change. If the verifier accepted any of them, the
certificate's fingerprint would be acting as an authority it does not have.

Every expected number here is hand-computed from the fixture table.
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research import financial_verification
from atlas.research.certificate import (
    CertificateError,
    build_certificate,
    load_certificate,
    payload_fingerprint,
    structural_problems,
)
from atlas.research.certificate_verify import (
    TrustedEvidence,
    VerificationLevel,
    build_source_manifest,
    compute,
    parse_printed,
    round_half_up,
    verify,
)
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.knowledge import KnowledgeEngine
from atlas.research.table_cells import extract_cells
from atlas.storage.db import Database

ISSUER = "ISS-CERT-F"
ACCESSION = "0000000030-24-000001"
CUTOFF = "2023-06-30T00:00:00Z"
DOC = """<html><body>
<h1>Item 8. Financial Statements</h1>
<p>Consolidated statements of income (in millions):</p>
<table>
<caption>Consolidated statements of income (in millions)</caption>
<tr><td></td><td>2020</td><td>2019</td></tr>
<tr><td>Revenue</td><td>1,234</td><td>1,100</td></tr>
<tr><td>Cost of revenue</td><td>(234)</td><td>(200)</td></tr>
<tr><td>Gross profit</td><td>1,000</td><td>900</td></tr>
<tr><td>Operating income</td><td>300</td><td>250</td></tr>
<tr><td>Net income</td><td>100</td><td>-50</td></tr>
<tr><td>Total assets</td><td>2,500</td><td>2,000</td></tr>
</table>
</body></html>"""
DOC_BYTES = DOC.encode("utf-8")


def _database() -> Database:
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000030", "Certificate Fixture Corp", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=DOC_BYTES,
        filed_date="2021-02-10", acceptance_time="2021-02-10T12:00:00Z",
        period_of_report="2020-12-31", rights="public_domain",
        primary_document_url="https://www.sec.gov/Archives/edgar/data/30/000000003024000001/doc.htm")
    return database


@pytest.fixture()
def db() -> Database:
    database = _database()
    yield database
    database.close()


def _cell(db: Database, row_label: str, period: str):
    document = KnowledgeEngine(db).document_by_accession(ACCESSION)
    table = dict(db.query_one("SELECT * FROM knowledge_table WHERE document_id = ?",
                              (document["document_id"],)))
    import json

    table["rows"] = json.loads(table["rows_json"])
    table["footnotes"] = []
    cells = extract_cells(table, document=document)
    matched = [cell for cell in cells
               if cell.status == "verified" and cell.row_label == row_label
               and cell.period == period]
    assert len(matched) == 1, (row_label, period, [(c.row_label, c.period) for c in cells])
    return matched[0]


def _binding(db: Database, cell) -> SimpleNamespace:
    """A resolver binding is a plain value object; the certificate only reads its fields."""
    document = KnowledgeEngine(db).document_by_accession(ACCESSION)
    concept = "revenue" if cell.row_label == "Revenue" else cell.row_label.lower().replace(" ", "_")
    return SimpleNamespace(
        concept=concept, issuer_id=ISSUER, document_id=cell.document_id,
        accession=ACCESSION, table_id=cell.table_id, unit_id=cell.unit_id,
        row=cell.row, column=cell.column, row_label=cell.row_label,
        column_label=cell.column_label, raw=cell.raw, value=cell.value, scale=cell.scale,
        currency=cell.currency, period=cell.period, availability_time=document["availability_time"],
        availability_precision=document["availability_precision"], rights=document["rights"],
        source_table_sha256=cell.source_sha256, statement_title=cell.statement_title,
        statement_family=cell.statement_family, entity_scope=cell.entity_scope)


def _certificate(db: Database, binding) -> object:
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    packet = engine.lookup_bound(binding, CUTOFF)
    assert packet["outcome"] == "answered", packet
    return build_certificate(db, packet, [binding])


def _evidence(db: Database, binding, *, snapshots: bool = True) -> TrustedEvidence:
    manifest = build_source_manifest(db, [binding], generated_at="2024-01-01T00:00:00Z")
    return TrustedEvidence(
        manifest=manifest,
        snapshots={ACCESSION: DOC_BYTES} if snapshots else {})


# ------------------------------------------------------------------ independent arithmetic
def test_verifier_arithmetic_matches_a_second_independent_implementation():
    """Two implementations that share no code must agree on known vectors."""
    for operator, raw_values, expected in financial_verification.REFERENCE_VECTORS:
        if operator == "lookup" and raw_values[0].strip().lower() in {"-", ""}:
            continue
        ours = compute(operator, list(raw_values))
        theirs = financial_verification.evaluate(operator, list(raw_values))
        assert ours == theirs, (operator, raw_values)

    assert parse_printed("1,234") == Fraction(1234)
    assert parse_printed("(234)") == Fraction(-234)
    assert parse_printed("12.5%") == Fraction("12.5")
    assert round_half_up(Fraction(1, 3)) == Decimal("0.33")
    assert round_half_up(Fraction(2, 3)) == Decimal("0.67")
    assert str(round_half_up(Fraction(43004))) == "43004.00"


def test_verifier_refuses_non_numeric_and_zero_denominators():
    from atlas.research.certificate_verify import VerificationError

    for text in ("", "-", "n/a", "1,2x4", "(5"):
        with pytest.raises(VerificationError):
            parse_printed(text)
    with pytest.raises(VerificationError):
        compute("ratio", ["1", "0"])
    with pytest.raises(VerificationError):
        compute("percentage_change", ["100", "0"])


# ------------------------------------------------------------------ construction
def test_certificate_carries_source_binding_and_fingerprint(db: Database):
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    certificate = _certificate(db, binding)
    assert structural_problems(certificate) == []
    assert certificate.fingerprint == payload_fingerprint(certificate.payload)
    assert certificate.subject["accession"] == ACCESSION
    assert certificate.subject["document_sha256"] == hashlib.sha256(DOC_BYTES).hexdigest()
    assert certificate.result["value"] == "1234.00"
    assert certificate.evidence[0]["raw"] == "1,234"
    assert certificate.evidence[0]["period"] == "2020"
    assert certificate.evidence[0]["concept"] == "revenue"
    assert certificate.evidence[0]["table_sha256"] == binding.source_table_sha256


def test_a_refusal_cannot_be_certified(db: Database):
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    refused = engine.lookup(ISSUER, CUTOFF, metric="gross profit margin percentage", period="2020")
    if refused["outcome"] != "abstained":
        refused = {"outcome": "abstained", "reason": "metric_not_found"}
    with pytest.raises(CertificateError):
        build_certificate(db, refused, [_binding(db, _cell(db, "Revenue", "2020"))])


def test_certificate_round_trips_through_json(db: Database):
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    certificate = _certificate(db, binding)
    import json

    reloaded = load_certificate(json.loads(certificate.to_json()))
    assert reloaded.fingerprint == certificate.fingerprint
    assert verify(reloaded, None).level is VerificationLevel.ARITHMETIC_VERIFIED


# ------------------------------------------------------------------ verification levels
def test_arithmetic_verification_alone_does_not_claim_source_authenticity(db: Database):
    certificate = _certificate(db, _binding(db, _cell(db, "Revenue", "2020")))
    report = verify(certificate, None)
    assert report.level is VerificationLevel.ARITHMETIC_VERIFIED
    assert "No trusted source evidence" in " ".join(report.limitations)
    assert report.recomputed_value == "1234.00"


def test_strict_verification_authenticates_the_original_bytes(db: Database):
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    certificate = _certificate(db, binding)
    report = verify(certificate, _evidence(db, binding))
    assert report.level is VerificationLevel.SOURCE_VERIFIED, report.reasons
    assert report.source_route == "snapshot"
    assert all(check["passed"] for check in report.checks)
    names = {check["check"] for check in report.checks}
    for required in ("certificate_fingerprint", "independent_arithmetic", "manifest_document",
                     "manifest_cell_0", "source_bytes_sha256", "source_cell_text_0",
                     "source_arithmetic"):
        assert required in names, required


def test_manifest_without_source_bytes_is_not_source_verification(db: Database):
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    report = verify(_certificate(db, binding), _evidence(db, binding, snapshots=False))
    assert report.level is VerificationLevel.SOURCE_UNVERIFIED
    assert "no_source_bytes" in report.reasons


def test_altered_source_bytes_are_rejected(db: Database):
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    manifest = build_source_manifest(db, [binding])
    tampered = DOC_BYTES.replace(b"1,234", b"1,299")
    report = verify(_certificate(db, binding),
                    TrustedEvidence(manifest=manifest, snapshots={ACCESSION: tampered}))
    assert report.level is VerificationLevel.INVALID
    assert any("source_bytes_sha256" in reason for reason in report.reasons)


# ------------------------------------------------------------------ adversarial matrix
def _tamper(certificate, mutate) -> object:
    payload = copy.deepcopy(certificate.payload)
    mutate(payload)
    return load_certificate({**payload, "fingerprint": payload_fingerprint(payload)})


def _tamper_result(payload):
    payload["result"]["value"] = "99999.00"


def _tamper_raw(payload):
    payload["evidence"][0]["raw"] = "1,334"


def _tamper_raw_and_result(payload):
    payload["evidence"][0]["raw"] = "1,334"
    payload["result"]["value"] = "1334.00"


def _tamper_fingerprint_only(payload):
    pass  # the caller re-fingerprints; this case is checked separately below


def _tamper_source_fingerprint(payload):
    payload["subject"]["document_sha256"] = "0" * 64
    payload["evidence"][0]["document_sha256"] = "0" * 64


def _tamper_issuer(payload):
    payload["subject"]["issuer_name"] = "Unrelated Industries Inc"
    payload["subject"]["issuer_id"] = "ISS-CIK0000000001"


def _tamper_accession(payload):
    payload["subject"]["accession"] = "0000000000-00-000000"


def _tamper_period(payload):
    payload["evidence"][0]["period"] = "1999"


def _tamper_currency(payload):
    payload["evidence"][0]["currency"] = "EUR"
    payload["result"]["currency"] = "EUR"


def _tamper_scale(payload):
    payload["evidence"][0]["scale"] = 9


def _tamper_availability(payload):
    payload["evidence"][0]["availability_time"] = "1999-01-01T00:00:00Z"


def _tamper_coordinates(payload):
    payload["evidence"][0]["row"] = 2


def _tamper_concept(payload):
    payload["evidence"][0]["concept"] = "net_income"


def _tamper_table_fingerprint(payload):
    payload["evidence"][0]["table_sha256"] = "f" * 64


def _tamper_operator(payload):
    payload["computation"]["operator"] = "ratio"


def _tamper_row_label(payload):
    payload["evidence"][0]["row_label"] = "Other revenue"


ATTACKS = [
    ("changed_result", _tamper_result),
    ("changed_raw_input", _tamper_raw),
    ("changed_input_and_result", _tamper_raw_and_result),
    ("changed_source_fingerprint", _tamper_source_fingerprint),
    ("changed_issuer", _tamper_issuer),
    ("changed_accession", _tamper_accession),
    ("changed_period", _tamper_period),
    ("changed_currency", _tamper_currency),
    ("changed_scale", _tamper_scale),
    ("changed_availability", _tamper_availability),
    ("changed_coordinates", _tamper_coordinates),
    ("changed_concept", _tamper_concept),
    ("changed_table_fingerprint", _tamper_table_fingerprint),
    ("changed_operator", _tamper_operator),
    ("changed_row_label", _tamper_row_label),
]


@pytest.mark.parametrize("name,mutate", ATTACKS)
def test_strict_verification_refuses_every_self_consistent_tamper(db: Database, name, mutate):
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    certificate = _certificate(db, binding)
    tampered = _tamper(certificate, mutate)
    # The tampered artifact is internally consistent: its fingerprint matches its body.
    assert tampered.fingerprint == payload_fingerprint(tampered.payload), name
    report = verify(tampered, _evidence(db, binding))
    assert report.level is VerificationLevel.INVALID, (name, report.level, report.reasons)


@pytest.mark.parametrize("name,mutate", ATTACKS)
def test_arithmetic_verification_alone_cannot_detect_a_consistent_tamper(db: Database, name, mutate):
    """Documents the limitation honestly: without source evidence, a forgery is undetectable."""
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    tampered = _tamper(_certificate(db, binding), mutate)
    report = verify(tampered, None)
    if name in {"changed_input_and_result", "changed_source_fingerprint", "changed_issuer",
                "changed_accession", "changed_period", "changed_currency", "changed_scale",
                "changed_availability", "changed_coordinates", "changed_concept",
                "changed_table_fingerprint", "changed_row_label"}:
        assert report.level is VerificationLevel.ARITHMETIC_VERIFIED, (name, report.reasons)


def test_the_headline_attack_is_refused_by_pinned_evidence(db: Database):
    """Change the input and the result together, recompute every hash: still refused."""
    binding = _binding(db, _cell(db, "Revenue", "2020"))
    certificate = _certificate(db, binding)
    tampered = _tamper(certificate, _tamper_raw_and_result)
    assert verify(tampered, None).level is VerificationLevel.ARITHMETIC_VERIFIED

    manifest = build_source_manifest(db, [binding])
    # Refused by the pinned manifest, before any bytes are consulted.
    manifest_only = verify(tampered, TrustedEvidence(manifest=manifest))
    assert manifest_only.level is VerificationLevel.INVALID
    assert any("manifest_raw_0" in reason for reason in manifest_only.reasons)

    # And refused again against the original bytes.
    strict = verify(tampered, TrustedEvidence(manifest=manifest,
                                              snapshots={ACCESSION: DOC_BYTES}))
    assert strict.level is VerificationLevel.INVALID


def test_a_changed_certificate_fingerprint_is_invalid(db: Database):
    certificate = _certificate(db, _binding(db, _cell(db, "Revenue", "2020")))
    forged = load_certificate({**certificate.payload, "fingerprint": "a" * 64})
    report = verify(forged, None)
    assert report.level is VerificationLevel.INVALID
    assert any("certificate_fingerprint" in reason for reason in report.reasons)


def test_structurally_incomplete_certificates_are_invalid(db: Database):
    certificate = _certificate(db, _binding(db, _cell(db, "Revenue", "2020")))
    for field in ("subject", "evidence", "computation", "result"):
        payload = copy.deepcopy(certificate.payload)
        payload.pop(field)
        report = verify(load_certificate(
            {**payload, "fingerprint": payload_fingerprint(payload)}), None)
        assert report.level is VerificationLevel.INVALID, field
        assert structural_problems(load_certificate(
            {**payload, "fingerprint": payload_fingerprint(payload)})) != []


def test_operator_mismatch_with_evidence_count_is_structural(db: Database):
    certificate = _certificate(db, _binding(db, _cell(db, "Revenue", "2020")))
    payload = copy.deepcopy(certificate.payload)
    payload["computation"]["operator"] = "percentage_change"
    problems = structural_problems(load_certificate(
        {**payload, "fingerprint": payload_fingerprint(payload)}))
    assert any(problem.startswith("evidence_count_mismatch") for problem in problems)


def test_two_binding_certificate_verifies_and_resists_tampering(db: Database):
    current = _binding(db, _cell(db, "Revenue", "2020"))
    prior = _binding(db, _cell(db, "Revenue", "2019"))
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    packet = engine.percentage_change_bound(current, prior, CUTOFF, metric="revenue growth")
    assert packet["outcome"] == "answered", packet
    certificate = build_certificate(db, packet, [current, prior])
    assert certificate.result["value"] == "12.18"
    evidence = _evidence(db, current)
    evidence.manifest = build_source_manifest(db, [current, prior])
    assert verify(certificate, evidence).level is VerificationLevel.SOURCE_VERIFIED

    payload = copy.deepcopy(certificate.payload)
    payload["evidence"][1]["raw"] = "1,000"
    payload["result"]["value"] = "23.40"
    tampered = load_certificate({**payload, "fingerprint": payload_fingerprint(payload)})
    assert verify(tampered, evidence).level is VerificationLevel.INVALID
