"""Research certificate construction, strict verification, and adversarial mutations.

The adversarial cases keep the artifact internally consistent: every mutation is re-signed with a
recomputed ``certificate_fingerprint``. A tampered certificate that merely fails the fingerprint
check proves nothing, because that is the trivial case. What matters is that a forged certificate
is refused when its own hashes all agree with its own altered body.

The earlier version of this file verified with ``trusted_sources`` built from the certificate's own
``source_table_sha256``. That is circular: the trusted input was copied from the artifact under
test. Verification now takes a pinned manifest plus the original document bytes, both supplied by
the caller from outside the certificate.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research.certificate import (
    build_certificate,
    fingerprint,
    verify_certificate_payload,
)
from atlas.research.certificate_verify import (
    VerificationLevel,
    build_source_manifest,
    TrustedEvidence,
    compute,
    parse_printed,
    round_half_up,
    verify_payload,
)
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver, bind
from atlas.research.financial_verification import REFERENCE_VECTORS
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

ISSUER = "ISS-FOCUS-CERT"
ACCESSION = "0000000031-24-000099"
CUTOFF = "2024-01-01T00:00:00Z"
ISSUER_NAME = "Fixture Co"

HTML = """<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p>
<table>
<tr><td>Year</td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table></body></html>"""
HTML_BYTES = HTML.encode("utf-8")


def _database(html: bytes = HTML_BYTES, accession: str = ACCESSION) -> Database:
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000031", ISSUER_NAME, now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=accession, form_type="10-K", html=html,
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{accession}.htm")
    return database


@pytest.fixture()
def fixture() -> dict:
    db = _database()
    knowledge = KnowledgeEngine(db)
    answers = FinancialAnswerEngine(knowledge)
    resolver = ConceptResolver(knowledge)
    resolution = resolver.resolve(ISSUER, "revenue", "2022", CUTOFF)
    binding = bind(resolution, ISSUER, "revenue")
    assert binding is not None, resolution.as_dict()
    assert binding.scale == 6
    answer = answers.lookup_bound(binding, CUTOFF)
    assert answer["outcome"] == "answered", answer
    document = db.query_one(
        "SELECT sha256, primary_document_url, form_type FROM knowledge_document"
        " WHERE document_id = ?", (binding.document_id,))
    certificate = build_certificate(
        research_question="What were net sales in 2022?",
        answer=answer,
        bindings=[binding],
        cutoff=CUTOFF,
        source_documents={binding.document_id: dict(document)},
        issuer_identity={"cik": "0000000031", "issuer_name": ISSUER_NAME},
    )
    manifest = build_source_manifest(db, [binding], generated_at="2024-01-01T00:00:00Z")
    evidence = TrustedEvidence(manifest=manifest, snapshots={ACCESSION: HTML_BYTES})
    return {"db": db, "binding": binding, "certificate": certificate, "evidence": evidence,
            "answer": answer, "manifest": manifest}


def _resign(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key != "certificate_fingerprint"}
    payload["certificate_fingerprint"] = fingerprint(body)
    return payload


# ------------------------------------------------------------------ arithmetic
def test_verifier_arithmetic_is_a_third_implementation():
    """The verifier must agree with the answer engine's independent verifier on known vectors."""
    from atlas.research import financial_verification

    for operator, raw_values, _expected in REFERENCE_VECTORS:
        assert compute(operator, list(raw_values)) == financial_verification.evaluate(
            operator, list(raw_values)), (operator, raw_values)
    assert parse_printed("34,229") == 34229
    assert parse_printed("(234)") == -234
    assert parse_printed("12.5%") == pytest.approx(12.5)
    with pytest.raises(Exception):
        parse_printed("-")
    with pytest.raises(Exception):
        compute("ratio", ["1", "0"])


# ------------------------------------------------------------------ levels
def test_unmodified_certificate_is_source_verified(fixture):
    payload = fixture["certificate"]
    report = verify_payload(payload, evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.SOURCE_VERIFIED.value, report["reasons"]
    assert report["status"] == "valid"
    assert report["source_route"] == "snapshot"
    assert all(check["passed"] for check in report["checks"])


def test_certificate_without_evidence_is_only_arithmetically_verified(fixture):
    report = verify_payload(fixture["certificate"])
    assert report["level"] == VerificationLevel.ARITHMETIC_VERIFIED.value
    assert "No trusted source evidence" in " ".join(report["limitations"])


def test_manifest_without_bytes_is_not_source_verified(fixture):
    evidence = TrustedEvidence(manifest=fixture["manifest"])
    report = verify_payload(fixture["certificate"], evidence=evidence)
    assert report["level"] == VerificationLevel.SOURCE_UNVERIFIED.value
    assert "no_source_bytes" in report["reasons"]


def test_legacy_caller_supplied_hashes_are_treated_as_insufficient(fixture):
    """A hash the caller copied from the certificate proves nothing about the bytes."""
    binding = fixture["binding"]
    legacy = {ACCESSION: {"sha256": binding.source_table_sha256,
                          "availability_time": binding.availability_time,
                          "body_present": True}}
    report = verify_payload(fixture["certificate"], trusted_sources=legacy)
    assert report["level"] == VerificationLevel.SOURCE_UNVERIFIED.value
    assert "legacy_trusted_sources_insufficient" in report["reasons"]


def test_historical_cutoff_refuses_binding(fixture):
    answers = FinancialAnswerEngine(KnowledgeEngine(fixture["db"]))
    answer = answers.lookup_bound(fixture["binding"], "2017-01-01T00:00:00Z")
    assert answer["outcome"] == "abstained"
    assert "future_evidence" in answer["context"]["problems"]


# ------------------------------------------------------------------ adversarial matrix
def _mutate(name: str, payload: dict) -> dict:
    mutated = copy.deepcopy(payload)
    binding = mutated["input_bindings"][0]
    source = mutated["selected_sources"][0]
    if name == "changed_result":
        mutated["result"]["value"] = "99999.00"
        mutated["result"]["value_exact"] = "99999"
    elif name == "changed_raw_input":
        binding["raw"] = "35,229"
    elif name == "changed_input_and_result":
        binding["raw"] = "35,229"
        binding["value"] = "35229"
        mutated["result"]["value"] = "35229.00"
        mutated["result"]["value_exact"] = "35229"
        mutated["result"]["economic_amount"] = "35229000000"
    elif name == "changed_certificate_fingerprint":
        mutated["certificate_fingerprint"] = "a" * 64
        return mutated
    elif name == "changed_source_fingerprint":
        binding["document_sha256"] = "0" * 64
        source["document_sha256"] = "0" * 64
    elif name == "changed_issuer":
        mutated["issuer_identity"]["issuer_id"] = "ISS-CIK0000000001"
        binding["issuer_id"] = "ISS-CIK0000000001"
    elif name == "changed_accession":
        binding["accession"] = "0000000000-00-000000"
        source["accession"] = "0000000000-00-000000"
    elif name == "changed_period":
        binding["period"] = "1999"
    elif name == "changed_currency":
        binding["currency"] = "EUR"
        mutated["result"]["currency"] = "EUR"
    elif name == "changed_scale":
        binding["scale"] = 9
        mutated["result"]["economic_amount"] = "34229000000000"
    elif name == "changed_availability":
        binding["availability_time"] = "1999-01-01T00:00:00Z"
        source["availability_time"] = "1999-01-01T00:00:00Z"
    elif name == "changed_coordinates":
        binding["row"] = int(binding["row"]) + 1
    elif name == "changed_concept":
        binding["concept"] = "net_income"
    elif name == "changed_table_fingerprint":
        binding["source_table_sha256"] = "f" * 64
        source["source_table_sha256"] = "f" * 64
    elif name == "changed_operator":
        mutated["normalized_requirement"]["operator"] = "ratio"
        mutated["typed_computation"]["operator"] = "ratio"
    elif name == "changed_row_label":
        binding["row_label"] = "Other revenue"
    # --- top-level result and requirement metadata, mutated independently of the bindings ---
    elif name == "changed_result_period":
        mutated["result"]["period"] = "2019"
    elif name == "changed_result_currency":
        mutated["result"]["currency"] = "EUR"
    elif name == "changed_result_unit_scale":
        mutated["result"]["unit"]["scale"] = 9
    elif name == "changed_result_unit_kind":
        mutated["result"]["unit"]["kind"] = "EUR"
    elif name == "removed_value_exact":
        mutated["result"].pop("value_exact")
    elif name == "removed_economic_amount":
        mutated["result"].pop("economic_amount")
    elif name == "changed_result_economic_amount":
        mutated["result"]["economic_amount"] = "99999000000"
    elif name == "changed_requirement_period":
        mutated["normalized_requirement"]["period"] = "2019"
    elif name == "changed_requirement_concept":
        mutated["normalized_requirement"]["concept"] = "net_income"
    elif name == "changed_requirement_operator":
        mutated["typed_computation"]["operator"] = "margin"
    elif name == "changed_financial_concepts":
        mutated["financial_concepts"] = ["net_income"]
    elif name == "changed_reporting_scope":
        mutated["reporting_entity_scope"] = "segment"
    elif name == "changed_answer_type":
        mutated["typed_computation"]["answer_type"] = "ratio"
    else:  # pragma: no cover - parametrisation guard
        raise AssertionError(name)
    return _resign(mutated)


ATTACKS = [
    "changed_result",
    "changed_raw_input",
    "changed_input_and_result",
    "changed_certificate_fingerprint",
    "changed_source_fingerprint",
    "changed_issuer",
    "changed_accession",
    "changed_period",
    "changed_currency",
    "changed_scale",
    "changed_availability",
    "changed_coordinates",
    "changed_concept",
    "changed_table_fingerprint",
    "changed_operator",
    "changed_row_label",
    "changed_result_period",
    "changed_result_currency",
    "changed_result_unit_scale",
    "changed_result_unit_kind",
    "removed_value_exact",
    "removed_economic_amount",
    "changed_result_economic_amount",
    "changed_requirement_period",
    "changed_requirement_concept",
    "changed_requirement_operator",
    "changed_financial_concepts",
    "changed_reporting_scope",
    "changed_answer_type",
]


@pytest.mark.parametrize("name", ATTACKS)
def test_self_consistent_tamper_is_refused(fixture, name):
    tampered = _mutate(name, fixture["certificate"])
    if name != "changed_certificate_fingerprint":
        # Re-signing worked: the forged artifact is internally consistent.
        body = {key: value for key, value in tampered.items() if key != "certificate_fingerprint"}
        assert tampered["certificate_fingerprint"] == fingerprint(body)
    report = verify_payload(tampered, evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value, (name, report["reasons"])


def test_headline_attack_passes_arithmetic_and_fails_source_verification(fixture):
    tampered = _mutate("changed_input_and_result", fixture["certificate"])
    arithmetic_only = verify_payload(tampered)
    assert arithmetic_only["level"] == VerificationLevel.ARITHMETIC_VERIFIED.value
    strict = verify_payload(tampered, evidence=fixture["evidence"])
    assert strict["level"] == VerificationLevel.INVALID.value
    assert any("manifest_raw" in reason for reason in strict["reasons"])


def test_changed_result_alone_fails_even_without_evidence(fixture):
    tampered = _mutate("changed_result", fixture["certificate"])
    report = verify_payload(tampered)
    assert report["level"] == VerificationLevel.INVALID.value
    assert "independent_arithmetic" in " ".join(report["reasons"])


def test_altered_snapshot_bytes_are_rejected(fixture):
    evidence = TrustedEvidence(
        manifest=fixture["manifest"],
        snapshots={ACCESSION: HTML_BYTES.replace(b"34,229", b"34,999")})
    report = verify_payload(fixture["certificate"], evidence=evidence)
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("source_bytes_sha256" in reason for reason in report["reasons"])


def test_missing_bindings_are_structural(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["input_bindings"] = []
    report = verify_payload(_resign(payload))
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("bindings" in reason for reason in report["reasons"])


def test_old_style_verify_entry_point_still_works(fixture):
    """``verify_certificate_payload`` remains the public compatibility entry point."""
    report = verify_certificate_payload(fixture["certificate"], evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.SOURCE_VERIFIED.value


# ------------------------------------------------------------------ CLI
def _write_evidence(tmp_path: Path, fixture: dict) -> tuple[Path, Path]:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(fixture["manifest"]), encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / f"{ACCESSION}.html").write_bytes(HTML_BYTES)
    return manifest_path, snapshots


def _run_cli(arguments: list[str]) -> tuple[int, dict]:
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "atlas", *arguments],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
    payload = {}
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {}
    return completed.returncode, payload


def test_cli_accepts_verified_certificate_and_rejects_tampered(tmp_path: Path, fixture):
    certificate = fixture["certificate"]
    manifest_path, snapshots = _write_evidence(tmp_path, fixture)
    path = tmp_path / "certificate.json"
    path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    code, payload = _run_cli(["verify-certificate", str(path)])
    assert code == 0, payload
    assert payload["level"] == "ARITHMETIC_VERIFIED"

    code, payload = _run_cli(["verify-certificate", str(path), "--manifest", str(manifest_path),
                              "--snapshots", str(snapshots), "--strict"])
    assert code == 0, payload
    assert payload["level"] == "SOURCE_VERIFIED"

    tampered = _mutate("changed_input_and_result", certificate)
    bad = tmp_path / "tampered.json"
    bad.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    code, payload = _run_cli(["verify-certificate", str(bad), "--manifest", str(manifest_path),
                              "--snapshots", str(snapshots), "--strict"])
    assert code == 1
    assert payload["level"] == "INVALID"

    # Strict mode also refuses a merely arithmetic result.
    code, _payload = _run_cli(["verify-certificate", str(path), "--strict"])
    assert code == 1


# ------------------------------------------------------------------ verifier boundary regressions
def test_malformed_root_is_invalid_not_an_exception():
    for malformed in (None, [], "not a certificate", 42):
        report = verify_payload(malformed)
        assert report["level"] == VerificationLevel.INVALID.value
        assert any("structure" in reason for reason in report["reasons"])


@pytest.mark.parametrize("invalid_cutoff", ["", "2024-01-01T00:00:00", "not-a-date"])
def test_invalid_or_timezone_naive_cutoff_is_refused(fixture, invalid_cutoff):
    payload = copy.deepcopy(fixture["certificate"])
    payload["information_cutoff"] = invalid_cutoff
    report = verify_payload(_resign(payload))
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("cutoff_valid" in reason for reason in report["reasons"])


def test_offset_timestamp_cannot_disguise_future_evidence(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["information_cutoff"] = "2024-01-01T00:00:00Z"
    payload["input_bindings"][0]["availability_time"] = "2024-01-01T00:01:00+00:00"
    report = verify_payload(_resign(payload))
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("not_future_evidence" in reason for reason in report["reasons"])


def test_equivalent_utc_offsets_compare_as_instants(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["information_cutoff"] = "2024-01-01T00:00:00Z"
    payload["input_bindings"][0]["availability_time"] = "2023-12-31T19:00:00-05:00"
    report = verify_payload(_resign(payload))
    assert report["level"] == VerificationLevel.ARITHMETIC_VERIFIED.value


@pytest.mark.parametrize("places", ["nan", 1000000, -1])
def test_malformed_or_unbounded_display_precision_is_refused(fixture, places):
    payload = copy.deepcopy(fixture["certificate"])
    payload["result"]["display_places"] = places
    report = verify_payload(_resign(payload))
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("display_places_valid" in reason for reason in report["reasons"])


def test_strict_verifier_rejects_cross_document_input(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["input_bindings"][0]["accession"] = "0000000000-00-000000"
    report = verify_payload(_resign(payload), evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value



def test_binding_issuer_claim_cannot_diverge_from_manifest(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["input_bindings"][0]["issuer_id"] = "ISS-FORGED"
    report = verify_payload(_resign(payload), evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("binding_issuer" in reason for reason in report["reasons"])


def test_selected_source_identity_cannot_diverge_from_binding(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["selected_sources"][0]["accession"] = "0000000000-00-000000"
    report = verify_payload(_resign(payload), evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("selected_accession" in reason for reason in report["reasons"])


def test_selected_source_url_must_match_pinned_manifest(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["selected_sources"][0]["primary_document_url"] = (
        "https://www.sec.gov/Archives/edgar/data/31/forged.htm")
    report = verify_payload(_resign(payload), evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("manifest_source_primary_document_url" in reason
               for reason in report["reasons"])


def test_false_issuer_name_is_rejected_even_with_matching_source_bytes(fixture):
    payload = copy.deepcopy(fixture["certificate"])
    payload["issuer_identity"]["issuer_name"] = "Not Fixture Co"
    report = verify_payload(_resign(payload), evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("manifest_issuer_name" in reason for reason in report["reasons"])


# ------------------------------------------------------------------ displayed result metadata
#: Mutations that leave every binding authentic and only relabel the displayed answer. They must
#: fail on internal consistency alone, before any source evidence is consulted.
RESULT_METADATA_ATTACKS = [
    "changed_result_period",
    "changed_result_currency",
    "changed_result_unit_scale",
    "changed_result_unit_kind",
    "removed_value_exact",
    "removed_economic_amount",
    "changed_result_economic_amount",
    "changed_requirement_period",
    "changed_requirement_concept",
    "changed_requirement_operator",
    "changed_financial_concepts",
    "changed_reporting_scope",
    "changed_answer_type",
]


@pytest.mark.parametrize("name", RESULT_METADATA_ATTACKS)
def test_result_metadata_tamper_fails_without_any_evidence(fixture, name):
    """The review's finding: authentic bindings plus a relabelled result must not verify."""
    tampered = _mutate(name, fixture["certificate"])
    report = verify_payload(tampered)
    assert report["level"] == VerificationLevel.INVALID.value, (name, report["reasons"])
    strict = verify_payload(tampered, evidence=fixture["evidence"])
    assert strict["level"] == VerificationLevel.INVALID.value, (name, strict["reasons"])


def test_result_period_disagreement_names_the_period_check(fixture):
    report = verify_payload(_mutate("changed_result_period", fixture["certificate"]))
    assert any("result_period" in reason for reason in report["reasons"])


def test_mandatory_result_fields_cannot_be_deleted(fixture):
    for name, reason in (("removed_value_exact", "result_fields_present"),
                         ("removed_economic_amount", "result_fields_present")):
        report = verify_payload(_mutate(name, fixture["certificate"]))
        assert report["level"] == VerificationLevel.INVALID.value
        assert any(reason in item for item in report["reasons"]), (name, report["reasons"])


def test_unresolved_currency_is_preserved_and_disclosed(fixture):
    """A null currency is legitimate when the statement prints no currency marker."""
    certificate = fixture["certificate"]
    assert certificate["result"]["currency"] is None
    report = verify_payload(certificate, evidence=fixture["evidence"])
    assert report["level"] == VerificationLevel.SOURCE_VERIFIED.value, report["reasons"]
    currencies = {check["check"]: check for check in report["checks"]}
    assert currencies["result_currency"]["passed"] is True


def test_header_confirmed_period_is_reported(fixture):
    report = verify_payload(fixture["certificate"], evidence=fixture["evidence"])
    assert report["semantic_status"]["period_assignment"] == "header_confirmed"


def test_period_assignment_conflict_is_unresolved_not_certified(fixture):
    """The Coca-Cola shape: value authentic, header prints the previous year."""
    payload = copy.deepcopy(fixture["certificate"])
    payload["input_bindings"][0]["column_label"] = "2021"
    manifest = copy.deepcopy(fixture["manifest"])
    next(iter(manifest["documents"].values()))["cells"][0]["column_label"] = "2021"
    evidence = TrustedEvidence(manifest=manifest, snapshots={ACCESSION: HTML_BYTES})
    report = verify_payload(_resign(payload), evidence=evidence)
    assert report["level"] == VerificationLevel.SOURCE_VERIFIED.value, report["reasons"]
    assert report["semantic_status"]["period_assignment"] == "unresolved"
    assert any("period_assignment_unresolved" in item for item in report["limitations"])


# ------------------------------------------------------------------ dimensionless results
@pytest.fixture()
def margin_fixture(fixture) -> dict:
    """A margin certificate: two bound inputs, a percentage, and no scaled amount."""
    db = fixture["db"]
    knowledge = KnowledgeEngine(db)
    revenue = fixture["binding"]
    resolution = ConceptResolver(knowledge).resolve(ISSUER, "gross_profit", "2022", CUTOFF)
    gross_profit = bind(resolution, ISSUER, "gross_profit")
    assert gross_profit is not None, resolution.as_dict()
    answer = FinancialAnswerEngine(knowledge).margin_bound(gross_profit, revenue, CUTOFF)
    assert answer["outcome"] == "answered", answer
    document = db.query_one(
        "SELECT sha256, primary_document_url, form_type FROM knowledge_document"
        " WHERE document_id = ?", (revenue.document_id,))
    documents = {revenue.document_id: dict(document),
                 gross_profit.document_id: dict(document)}
    certificate = build_certificate(
        research_question="What was the gross margin in 2022?",
        answer=answer,
        bindings=[gross_profit, revenue],
        cutoff=CUTOFF,
        source_documents=documents,
        issuer_identity={"cik": "0000000031", "issuer_name": ISSUER_NAME},
    )
    manifest = build_source_manifest(db, [gross_profit, revenue],
                                     generated_at="2024-01-01T00:00:00Z")
    evidence = TrustedEvidence(manifest=manifest, snapshots={ACCESSION: HTML_BYTES})
    return {"certificate": certificate, "evidence": evidence, "manifest": manifest}


def test_dimensionless_result_declares_null_economic_amount(margin_fixture):
    certificate = margin_fixture["certificate"]
    assert certificate["normalized_requirement"]["operator"] == "margin"
    assert certificate["result"]["unit"] == {"kind": "percent", "scale": 0}
    assert certificate["result"]["economic_amount"] is None
    report = verify_payload(certificate, evidence=margin_fixture["evidence"])
    assert report["level"] == VerificationLevel.SOURCE_VERIFIED.value, report["reasons"]


def test_dimensionless_result_may_not_invent_an_economic_amount(margin_fixture):
    payload = copy.deepcopy(margin_fixture["certificate"])
    payload["result"]["economic_amount"] = "13229000000"
    report = verify_payload(_resign(payload), evidence=margin_fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("economic_amount_not_applicable" in reason for reason in report["reasons"])


def test_dimensionless_percentage_change_period_label_is_checked(margin_fixture):
    """``percentage_change`` displays "current vs prior"; that label must follow the inputs."""
    db = margin_fixture["certificate"]["input_bindings"][0]
    assert db["period"] == "2022"
    payload = copy.deepcopy(margin_fixture["certificate"])
    payload["result"]["period"] = "2021 vs 2022"
    report = verify_payload(_resign(payload), evidence=margin_fixture["evidence"])
    assert report["level"] == VerificationLevel.INVALID.value
    assert any("result_period" in reason for reason in report["reasons"])


# ------------------------------------------------------------------ cross-input scale
#: One authentic filing with two statements printed at different exponents: millions on the income
#: statement, thousands on the cash-flow statement. Both cells are real, pinned, and reproducible.
MIXED_ACCESSION = "0000000031-24-000100"
HTML_MIXED_SCALE = """<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p>
<table>
<tr><td>Year</td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table>
<p>CONSOLIDATED STATEMENTS OF CASH FLOWS</p>
<p>(In thousands)</p>
<table>
<tr><td>Year</td><td>2022</td><td>2021</td></tr>
<tr><td>Net cash provided by operating activities</td><td>6,000</td><td>5,000</td></tr>
<tr><td>Purchases of property and equipment</td><td>2,500</td><td>2,000</td></tr>
<tr><td>Net cash used in investing activities</td><td>(2,500)</td><td>(2,000)</td></tr>
</table>
</body></html>"""
HTML_MIXED_SCALE_BYTES = HTML_MIXED_SCALE.encode("utf-8")


@pytest.fixture()
def mixed_scale_fixture() -> dict:
    """Authentic bindings, and genuine ratio/margin/change certificates, at two printed scales."""
    db = _database(HTML_MIXED_SCALE_BYTES, MIXED_ACCESSION)
    knowledge = KnowledgeEngine(db)
    answers = FinancialAnswerEngine(knowledge)
    resolver = ConceptResolver(knowledge)
    bindings: dict[tuple[str, str], object] = {}
    for concept, period in (("revenue", "2022"), ("revenue", "2021"),
                            ("gross_profit", "2022"),
                            ("capital_expenditures", "2022"),
                            ("capital_expenditures", "2021")):
        resolution = resolver.resolve(ISSUER, concept, period, CUTOFF)
        bound = bind(resolution, ISSUER, concept)
        assert bound is not None, (concept, period, resolution.as_dict())
        bindings[(concept, period)] = bound
    assert bindings[("revenue", "2022")].scale == 6
    assert bindings[("capital_expenditures", "2022")].scale == 3
    assert bindings[("capital_expenditures", "2022")].accession == MIXED_ACCESSION

    documents: dict[str, dict] = {}
    for bound in bindings.values():
        document = db.query_one(
            "SELECT sha256, primary_document_url, form_type FROM knowledge_document"
            " WHERE document_id = ?", (bound.document_id,))
        documents[bound.document_id] = dict(document)
    manifest = build_source_manifest(db, list(bindings.values()),
                                     generated_at="2024-01-01T00:00:00Z")
    evidence = TrustedEvidence(manifest=manifest,
                               snapshots={MIXED_ACCESSION: HTML_MIXED_SCALE_BYTES})

    def certify(answer: dict, chosen: list) -> dict:
        return build_certificate(
            research_question="Mixed-scale operands regression", answer=answer,
            bindings=chosen, cutoff=CUTOFF, source_documents=documents,
            issuer_identity={"cik": "0000000031", "issuer_name": ISSUER_NAME})

    revenue_2022 = bindings[("revenue", "2022")]
    revenue_2021 = bindings[("revenue", "2021")]
    gross_profit = bindings[("gross_profit", "2022")]
    capex_2022 = bindings[("capital_expenditures", "2022")]
    capex_2021 = bindings[("capital_expenditures", "2021")]
    ratio = answers.ratio_bound(gross_profit, revenue_2022, CUTOFF)
    margin = answers.margin_bound(gross_profit, revenue_2022, CUTOFF)
    change = answers.percentage_change_bound(revenue_2022, revenue_2021, CUTOFF,
                                             metric="net sales")
    for packet in (ratio, margin, change):
        assert packet["outcome"] == "answered", packet
    return {
        "answers": answers,
        "bindings": bindings,
        "evidence": evidence,
        "certificates": {
            "ratio": certify(ratio, [gross_profit, revenue_2022]),
            "margin": certify(margin, [gross_profit, revenue_2022]),
            "percentage_change": certify(change, [revenue_2022, revenue_2021]),
        },
        "donors": {
            "capex_2022": certify(answers.lookup_bound(capex_2022, CUTOFF), [capex_2022]),
            "capex_2021": certify(answers.lookup_bound(capex_2021, CUTOFF), [capex_2021]),
        },
    }


def _splice_forged_binding(certificate: dict, donor: dict, index: int) -> dict:
    """Swap one operand for a second authentic cell, then recompute the answer and fingerprint."""
    forged = copy.deepcopy(certificate)
    forged["input_bindings"][index] = copy.deepcopy(donor["input_bindings"][0])
    forged["selected_sources"][index] = copy.deepcopy(donor["selected_sources"][0])
    forged["financial_concepts"] = [str(binding["concept"])
                                    for binding in forged["input_bindings"]]
    operator = str(forged["normalized_requirement"]["operator"])
    exact = compute(operator, [str(binding["raw"]) for binding in forged["input_bindings"]])
    places = int(forged["result"]["display_places"])
    forged["result"]["value"] = str(round_half_up(exact, places=places))
    forged["result"]["value_exact"] = str(exact)
    return _resign(forged)


#: (operator, operand to replace, donor lookup certificate). Each pair of operands is authentic
#: and pinned, but one is printed in thousands and the other in millions.
MIXED_SCALE_ATTACKS = [
    ("ratio", 1, "capex_2022"),
    ("margin", 1, "capex_2022"),
    ("percentage_change", 1, "capex_2021"),
]


@pytest.mark.parametrize("operator,index,donor", MIXED_SCALE_ATTACKS)
def test_mixed_scale_operands_cannot_reach_source_verified(mixed_scale_fixture, operator,
                                                           index, donor):
    """A ratio of thousands to millions is not made true by authentic cells and matching pins."""
    genuine = mixed_scale_fixture["certificates"][operator]
    control = verify_payload(genuine, evidence=mixed_scale_fixture["evidence"])
    assert control["level"] == VerificationLevel.SOURCE_VERIFIED.value, control["reasons"]
    # The permitted same-scale case keeps the dimensionless semantics: null amount, zero scale.
    assert genuine["result"]["economic_amount"] is None
    expected_kind = "ratio" if operator == "ratio" else "percent"
    assert genuine["result"]["unit"] == {"kind": expected_kind, "scale": 0}
    assert genuine["result"]["currency"] is None

    forged = _splice_forged_binding(genuine, mixed_scale_fixture["donors"][donor], index)
    body = {key: value for key, value in forged.items() if key != "certificate_fingerprint"}
    assert forged["certificate_fingerprint"] == fingerprint(body)
    assert {binding["scale"] for binding in forged["input_bindings"]} == {3, 6}
    assert forged["result"]["value_exact"] == str(
        compute(operator, [binding["raw"] for binding in forged["input_bindings"]]))

    strict = verify_payload(forged, evidence=mixed_scale_fixture["evidence"])
    assert strict["level"] == VerificationLevel.INVALID.value, strict["reasons"]
    assert len(strict["reasons"]) == 1, strict["reasons"]
    assert strict["reasons"][0].startswith("binding_scale_consistent")
    assert "['3', '6']" in strict["reasons"][0]


def test_engine_and_verifier_both_refuse_mixed_scales(mixed_scale_fixture):
    """The verifier reaches the engine's refusal independently, not by trusting it."""
    answers = mixed_scale_fixture["answers"]
    bindings = mixed_scale_fixture["bindings"]
    gross = bindings[("gross_profit", "2022")]
    revenue = bindings[("revenue", "2022")]
    capex_2022 = bindings[("capital_expenditures", "2022")]
    capex_2021 = bindings[("capital_expenditures", "2021")]
    packets = (
        answers.ratio_bound(gross, capex_2022, CUTOFF),
        answers.margin_bound(gross, capex_2022, CUTOFF),
        answers.percentage_change_bound(revenue, capex_2021, CUTOFF, metric="net sales"),
    )
    for packet in packets:
        assert packet["outcome"] == "abstained", packet
        assert packet["reason"] == "unit_mismatch", packet
