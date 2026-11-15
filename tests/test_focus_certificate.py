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
<tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table></body></html>"""
HTML_BYTES = HTML.encode("utf-8")


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
        (ISSUER, "0000000031", ISSUER_NAME, now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=HTML_BYTES,
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{ACCESSION}.htm")
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
