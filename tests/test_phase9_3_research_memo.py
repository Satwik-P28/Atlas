"""Phase 9.3 adversarial acceptance: claims, memos, exports and change detection.

Every test names the failure it is meant to catch. Nothing here asserts that a benchmark
passed; these are contract and adversarial tests over synthetic evidence.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from atlas.core.errors import ValidationError
from atlas.fec.compiler import COMPILER_VERSION
from atlas.research import changes as change_detection
from atlas.research import claims as claim_contract
from atlas.research.equity import methodology_narrative
from atlas.research.memo import (
    MEMO_SCHEMA,
    MEMO_VERSION,
    ResearchMemoService,
    integrity_report,
    memo_hash,
    render_html,
    render_json,
    render_markdown,
    verify_export,
)

ISSUER = "ISS-CIK0000320193"
CUTOFF = "2024-06-30T00:00:00Z"
CONTRACT = "atlas.model.v1"


# --------------------------------------------------------------------------- helpers
def _evidence(db, **over: Any) -> dict[str, Any]:
    row = {
        "evidence_id": "EVD-1",
        "entity_id": ISSUER,
        "concept": "revenue",
        "value": "100000000",
        "unit": "USD",
        "currency": "USD",
        "period_end": "2024-03-31",
        "availability": "2024-05-01T16:05:12Z",
        "revision_kind": "original",
        "supersedes": None,
    }
    row.update(over)
    db.execute(
        "INSERT INTO evidence (evidence_id, record_kind, entity_id, entity_kind, concept, source_id,"
        " value_numeric, unit, unit_kind, currency, period_start, period_end, period_type, fiscal_period,"
        " availability_time, availability_precision, availability_basis, filed_date, acceptance_datetime,"
        " observed_at, ingest_seq, content_hash, accession_number, form_type, revision_kind, supersedes,"
        " derivation_kind, quality, verification)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["evidence_id"], "financial_fact", row["entity_id"], "issuer", row["concept"],
            "sec-edgar", row["value"], row["unit"], "monetary", row["currency"], "2024-01-01",
            row["period_end"], "duration", "Q1", row["availability"], "second", "test.acceptance",
            "2024-05-01", "2024-05-01T16:05:12Z", "2024-09-01T12:00:00Z", 0,
            f"hash-{row['evidence_id']}", "0000320193-24-000001", "10-Q", row["revision_kind"],
            row["supersedes"], "source_observation", "verified", "source_primary",
        ),
    )
    return row


def _metrics() -> dict[str, Any]:
    def item(value: str, unit: str = "USD", evidence: str = "EVD-1") -> dict[str, Any]:
        return {"value": value, "unit": unit, "currency": "USD", "evidence_ids": [evidence]}

    return {
        "metrics": {
            "revenue": item("100000000", evidence="EVD-1"),
            "net_income": item("20000000", evidence="EVD-2"),
            "equity": item("50000000", evidence="EVD-3"),
            "operating_cash_flow": item("30000000", evidence="EVD-4"),
            "capex": item("5000000", evidence="EVD-5"),
            "net_margin": item("0.2", unit="ratio", evidence="EVD-2"),
            "free_cash_flow": item("25000000", evidence="EVD-4"),
            "roe": item("0.4", unit="ratio", evidence="EVD-3"),
        },
        "period_end": "2024-03-31",
        "period_start": "2024-01-01",
        "period_type": "duration",
        "fiscal_period": "Q1",
        "as_of": CUTOFF,
        "mode": "public_available",
    }


def _analysis(*, institution: bool = False, arithmetic: bool = True,
              sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    eligibility = {
        "status": "unsupported_methodology" if institution else "eligible",
        "method": "residual_income_equity" if institution else "unlevered_fcff_dcf",
        "rejected_method": "unlevered_fcff_dcf" if institution else None,
        "financial_institution": institution,
        "business_model": "bank holding company" if institution else "operating company",
        "sic": "6021" if institution else "3571",
        "method_basis": "SIC range 6000-6799",
        "reasons": ["reason one"],
    }
    valuation: dict[str, Any] = {
        "eligibility": eligibility,
        "method": eligibility["method"],
        "findings": [],
        "economically_supported": arithmetic,
        "scenarios": {"scenarios": {}},
        "sensitivity": {"matrix": [[1.0]]},
    }
    if institution:
        valuation["institution"] = {
            "method": eligibility["method"],
            "model_version": "atlas.bank.residual_income.v3",
            "fingerprint": "FP-BANK",
            "outputs": {"value_per_share": 295.4643539226478, "calculated_equity_value": 1.0},
            "assumptions": {"cost_of_equity": 0.1, "sustainable_roe": 0.17},
            "audit": {"passed": arithmetic, "checks": [{}, {}, {}], "version": "v3"},
            "limitations": ["residual income is not a market price"],
            "executes": True,
        }
    else:
        valuation["dcf"] = {
            "assumptions": {"wacc": 0.09, "horizon": 5},
            "outputs": {"value_per_share": 101.2158, "equity_value": 2.0, "enterprise_value": 3.0,
                        "pv_terminal": 1.5},
            "manifest": {"compiler_version": COMPILER_VERSION, "model_version": "1.0.0"},
            "fingerprint": "FP-DCF",
        }
        valuation["audit"] = {
            "arithmetic_valid": arithmetic,
            "verdict": "supported" if arithmetic else "arithmetic_failure",
            "checks": [{"name": "value per share", "status": "pass" if arithmetic else "fail"}],
        }
    workspace = {
        "as_of": CUTOFF,
        "mode": "public_available",
        "company": {"issuer_id": ISSUER, "legal_name": "Apple Inc.", "cik": "0000320193", "sic": "3571"},
        "metrics": _metrics(),
        "coverage": {
            "evidence_records": 5, "concepts": 5, "annual_periods": 3,
            "first_period": "2022-09-30", "last_period": "2024-03-31",
            "missing_core_concepts": [], "filings": 4, "market_observations": 0,
            "price_source": None, "ticker": "AAPL",
            "limitations": ["The compact fixture is not a complete SEC archive."],
        },
        "limitations": ["SEC XBRL is the financial source."],
        "provenance": {
            "sources": sources if sources is not None else [{
                "source_id": "sec-edgar", "licence": "public domain",
                "redistribution": "public_domain", "name": "SEC EDGAR", "kind": "sec_edgar",
            }],
        },
        "market_price": {"status": "unavailable"},
    }
    return {"schema": "atlas.equity_research.v1", "workspace": workspace,
            "valuation": valuation, "metadata": {}, "report": "", "report_sha256": ""}


def _seed(db) -> None:
    _evidence(db, evidence_id="EVD-1", concept="revenue", value="100000000")
    _evidence(db, evidence_id="EVD-2", concept="net_income", value="20000000")
    _evidence(db, evidence_id="EVD-3", concept="equity", value="50000000")
    _evidence(db, evidence_id="EVD-4", concept="operating_cash_flow", value="30000000")
    _evidence(db, evidence_id="EVD-5", concept="capex", value="5000000")


def _claims(db, analysis=None) -> list[dict[str, Any]]:
    analysis = analysis or _analysis()
    built = claim_contract.build_claims(analysis, cutoff=CUTOFF)
    return claim_contract.verify_claims(db, built)


def _memo(db, analysis=None, *, claims=None, sources=None, pins=None,
          compiler: str = COMPILER_VERSION, cutoff: str = CUTOFF) -> dict[str, Any]:
    analysis = analysis or _analysis()
    verified = claims if claims is not None else _claims(db, analysis)
    integrity = integrity_report(analysis, verified)
    rights = claim_contract.rights_decision(
        sources if sources is not None else analysis["workspace"]["provenance"]["sources"]
    )
    evidence_ids = sorted({eid for claim in verified for eid in claim["evidence_ids"]})
    memo: dict[str, Any] = {
        "schema": MEMO_SCHEMA,
        "memo_version": MEMO_VERSION,
        "memo_id": None,
        "name": "Apple Inc. equity research memo",
        "workspace_id": None,
        "issuer": {"issuer_id": ISSUER, "legal_name": "Apple Inc.", "cik": "0000320193",
                   "sic": "3571", "ticker": "AAPL", "business_model": "operating company",
                   "valuation_method": "unlevered_fcff_dcf"},
        "cutoff": cutoff,
        "mode": "public_available",
        "objective": "Test objective.",
        "claims": verified,
        "sections": [{
            "id": "source_limitations", "title": "Source limitations",
            "claim_ids": [], "items": [{"label": "Limitation", "value": "compact fixture"}],
            "notes": [],
        }],
        "integrity": integrity,
        "citations": {"evidence": [claim_contract.evidence_citation(db, eid) for eid in evidence_ids],
                      "market_observation": None, "model": []},
        "rights": rights,
        "manifest": {"schema": "atlas.research_memo.manifest.v1", "compiler_version": compiler,
                     "evidence_dependencies": evidence_ids, "observation_pins": pins or [],
                     "model_fingerprints": [], "assumptions": []},
        "generated_at": "2024-06-30T00:00:00Z",
    }
    memo["content_hash"] = memo_hash(memo)
    memo["memo_id"] = f"RMO-{memo['content_hash'][:16]}"
    memo["manifest"]["content_hash"] = memo["content_hash"]
    return memo


def _by_key(claims: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(claim for claim in claims if claim["key"] == key)


# --------------------------------------------------------------- claim verification
def test_observed_fact_resolves_to_stored_evidence(db):
    _seed(db)
    claims = _claims(db)
    revenue = _by_key(claims, "revenue")
    assert revenue["verification"]["outcome"] == "verified"
    assert "EVD-1" in revenue["evidence_ids"]


def test_factual_claim_without_evidence_is_missing_evidence(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    revenue["evidence_ids"] = []
    assert claim_contract.verify_claim(db, revenue)["verification"]["outcome"] == "missing_evidence"


def test_claim_citing_another_issuer_is_rejected(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    revenue["issuer_id"] = "ISS-CIK9999999999"
    result = claim_contract.verify_claim(db, revenue)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "issuer_mismatch" for d in result["verification"]["diagnostics"])


def test_claim_period_mismatch_is_rejected(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    revenue["period"]["end"] = "2023-03-31"
    result = claim_contract.verify_claim(db, revenue)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "period_mismatch" for d in result["verification"]["diagnostics"])


def test_claim_value_mismatch_is_rejected(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    revenue["value"] = "100000001"
    result = claim_contract.verify_claim(db, revenue)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "value_mismatch" for d in result["verification"]["diagnostics"])


def test_claim_currency_mismatch_is_rejected(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    db.execute("UPDATE evidence SET currency='EUR' WHERE evidence_id='EVD-1'")
    result = claim_contract.verify_claim(db, revenue)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "currency_mismatch" for d in result["verification"]["diagnostics"])


def test_claim_unit_mismatch_is_rejected(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    db.execute("UPDATE evidence SET unit='shares' WHERE evidence_id='EVD-1'")
    result = claim_contract.verify_claim(db, revenue)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "unit_mismatch" for d in result["verification"]["diagnostics"])


def test_evidence_available_after_cutoff_is_rejected(db):
    _seed(db)
    revenue = _by_key(_claims(db), "revenue")
    revenue["cutoff"] = "2024-01-01T00:00:00Z"
    result = claim_contract.verify_claim(db, revenue)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "availability_after_cutoff" for d in result["verification"]["diagnostics"])


def test_derived_metric_reproduces_from_its_inputs(db):
    _seed(db)
    claims = _claims(db)
    margin = _by_key(claims, "net_margin")
    assert margin["verification"]["outcome"] == "verified"
    assert margin["computation"]["operator_version"] == claim_contract.ARITHMETIC_VERSION


def test_tampered_derived_metric_does_not_reproduce(db):
    _seed(db)
    margin = _by_key(_claims(db), "net_margin")
    margin["value"] = "0.5"
    result = claim_contract.verify_claim(db, margin)
    assert result["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "value_mismatch" for d in result["verification"]["diagnostics"])


def test_model_output_verifies_against_its_audit(db):
    _seed(db)
    claim = _by_key(_claims(db), "dcf.value_per_share")
    assert claim["verification"]["outcome"] == "verified"
    assert claim["model"]["fingerprint"] == "FP-DCF"


def test_incompatible_compiler_is_reported(db):
    _seed(db)
    claim = _by_key(_claims(db), "dcf.value_per_share")
    claim["model"]["compiler_version"] = "atlas.fec.compiler.v0"
    result = claim_contract.verify_claim(db, claim)
    assert result["verification"]["outcome"] == "incompatible_model"
    assert any(d["code"] == "model_incompatible" for d in result["verification"]["diagnostics"])


def test_failed_arithmetic_audit_is_not_a_verified_model(db):
    _seed(db)
    analysis = _analysis(arithmetic=False)
    claim = _by_key(_claims(db, analysis), "dcf.value_per_share")
    assert claim["verification"]["outcome"] == "unsupported"
    assert any(d["code"] == "model_audit_failed" for d in claim["verification"]["diagnostics"])


def test_bank_model_claim_verifies_with_institution_audit_shape(db):
    _seed(db)
    claim = _by_key(_claims(db, _analysis(institution=True)), "institution.value_per_share")
    assert claim["verification"]["outcome"] == "verified"
    assert claim["model"]["audit_verdict"] == "arithmetic_pass"


def test_analyst_hypothesis_is_never_a_verified_fact(db):
    _seed(db)
    hypothesis = _by_key(_claims(db), "research_question")
    assert hypothesis["claim_type"] == "analyst_hypothesis"
    assert hypothesis["verification"]["outcome"] == claim_contract.NON_FACTUAL_OUTCOME
    assert hypothesis["evidence_ids"] == []


def test_assumptions_and_disclosures_are_not_factual_claims(db):
    _seed(db)
    claims = _claims(db)
    assumption = _by_key(claims, "assumption.wacc")
    disclosure = _by_key(claims, "disclosure.business_model")
    assert assumption["claim_type"] == "analyst_assumption"
    assert disclosure["claim_type"] == "methodology_disclosure"
    for claim in (assumption, disclosure):
        assert claim["verification"]["outcome"] == claim_contract.NON_FACTUAL_OUTCOME


def test_claim_build_is_deterministic(db):
    _seed(db)
    first = _claims(db)
    second = _claims(db)
    assert [claim["claim_id"] for claim in first] == [claim["claim_id"] for claim in second]
    assert [claim["verification"]["outcome"] for claim in first] == [
        claim["verification"]["outcome"] for claim in second
    ]


# ------------------------------------------------------------------------ citations
def test_citation_resolves_and_reports_a_missing_document(db):
    _seed(db)
    resolved = claim_contract.evidence_citation(db, "EVD-1")
    assert resolved["status"] == "resolved"
    assert resolved["accession_number"] == "0000320193-24-000001"
    assert resolved["passage"] is None
    missing = claim_contract.evidence_citation(db, "EVD-does-not-exist")
    assert missing["status"] == "unavailable"


def test_unresolved_observation_pin_is_reported_unavailable():
    citation = claim_contract.observation_citation({"security_id": "SEC-1", "session": "2024-06-28"})
    assert citation["status"] == "unavailable"


# --------------------------------------------------------------------------- exports
def test_html_escapes_injected_source_text(db):
    _seed(db)
    claims = _claims(db)
    revenue = _by_key(claims, "revenue")
    revenue["statement"] = '<script>alert("x")</script> revenue'
    memo = _memo(db, claims=claims)
    memo["sections"].append({
        "id": "financial_summary", "title": "Financial summary",
        "claim_ids": [revenue["claim_id"]],
        "items": [{"label": revenue["statement"], "value": "100000000"}],
        "notes": [revenue["statement"]],
    })
    rendered = render_html(memo)
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered


def test_export_manifest_detects_tampering(db):
    _seed(db)
    memo = _memo(db)
    service = ResearchMemoService(db)
    saved = service.save(memo)
    export = service.export(saved["object_id"], format="markdown")
    assert verify_export(export)["content_hash_matches"] is True
    export["content"] = export["content"] + "\ntampered"
    assert verify_export(export)["content_hash_matches"] is False


def test_export_formats_agree_on_the_same_claims(db):
    _seed(db)
    memo = _memo(db)
    service = ResearchMemoService(db)
    saved = service.save(memo)
    markdown = service.export(saved["object_id"], format="markdown")["content"]
    html = service.export(saved["object_id"], format="html")["content"]
    payload = json.loads(service.export(saved["object_id"], format="json")["content"])
    assert payload["memo"]["content_hash"] == memo["content_hash"]
    for claim_id in (claim["claim_id"] for claim in memo["claims"]):
        assert claim_id in markdown
        assert claim_id in html


def test_export_is_refused_when_a_source_is_restricted(db):
    _seed(db)
    restricted = [{"source_id": "vendor-x", "licence": "proprietary", "redistribution": "restricted"}]
    memo = _memo(db, sources=restricted)
    service = ResearchMemoService(db)
    saved = service.save(memo)
    with pytest.raises(ValidationError):
        service.export(saved["object_id"], format="markdown")


def test_markdown_is_byte_stable_across_renders(db):
    _seed(db)
    memo = _memo(db)
    assert render_markdown(memo) == render_markdown(memo)


def test_coverage_disclosure_states_the_fixture_is_incomplete(db):
    _seed(db)
    claims = _claims(db)
    coverage = _by_key(claims, "disclosure.coverage")
    assert "not a complete SEC archive" in " ".join(coverage["limitations"])


# --------------------------------------------------------------------- persistence
def test_saved_memo_version_is_immutable(db):
    _seed(db)
    memo = _memo(db)
    service = ResearchMemoService(db)
    first = service.save(memo, version="1.0.0")
    original = service.get(first["object_id"])
    changed_claims = _claims(db)
    _by_key(changed_claims, "revenue")["statement"] = "Revenue changed."
    second_memo = _memo(db, claims=changed_claims)
    second = service.save(second_memo, version="1.1.0")
    assert service.get(first["object_id"])["content_hash"] == original["content_hash"]
    assert second["object_id"] != first["object_id"]
    assert service.get(second["object_id"])["content_hash"] != original["content_hash"]


def test_same_evidence_produces_the_same_memo_hash(db):
    """The preview/save guard is only meaningful if a rebuild is deterministic."""
    _seed(db)
    first = _memo(db)
    second = _memo(db)
    assert first["content_hash"] == second["content_hash"]
    assert [claim["claim_id"] for claim in first["claims"]] == [
        claim["claim_id"] for claim in second["claims"]
    ]


def test_save_refuses_a_memo_that_differs_from_the_reviewed_preview(db):
    """A stale preview must never persist a different research object than was reviewed."""
    _seed(db)
    preview = _memo(db)
    service = ResearchMemoService(db)
    changed = _claims(db)
    _by_key(changed, "revenue")["statement"] = "Revenue changed after the review."
    rebuilt = _memo(db, claims=changed)
    assert rebuilt["content_hash"] != preview["content_hash"]
    with pytest.raises(ValidationError) as failure:
        service.save(rebuilt, expected_content_hash=preview["content_hash"])
    context = failure.value.context
    assert context.get("code") == "memo_content_changed"
    assert context.get("expected_content_hash") == preview["content_hash"]
    assert context.get("actual_content_hash") == rebuilt["content_hash"]
    assert service.list() == [], "a refused save must not persist anything"


def test_save_accepts_the_reviewed_hash_and_keeps_it(db):
    _seed(db)
    preview = _memo(db)
    service = ResearchMemoService(db)
    saved = service.save(preview, expected_content_hash=preview["content_hash"])
    stored = service.get(saved["object_id"])
    assert stored["memo"]["content_hash"] == preview["content_hash"]
    assert [claim["claim_id"] for claim in stored["memo"]["claims"]] == [
        claim["claim_id"] for claim in preview["claims"]
    ]


def test_save_without_a_reviewed_hash_remains_supported(db):
    _seed(db)
    service = ResearchMemoService(db)
    saved = service.save(_memo(db), version="1.0.0")
    assert saved["object_id"].startswith("URO-")


def test_compare_reports_changed_claims(db):
    _seed(db)
    service = ResearchMemoService(db)
    first = service.save(_memo(db), version="1.0.0")
    changed = _claims(db)
    _by_key(changed, "revenue")["statement"] = "Revenue restated."
    second = service.save(_memo(db, claims=changed), version="1.1.0")
    comparison = service.compare(first["object_id"], second["object_id"])
    assert comparison["equal"] is False
    assert any(item["key"] == "revenue" for item in comparison["claims"]["changed"])


def test_reopening_an_old_memo_keeps_its_own_evidence_set(db):
    _seed(db)
    service = ResearchMemoService(db)
    first = service.save(_memo(db), version="1.0.0")
    _evidence(db, evidence_id="EVD-6", concept="assets", value="9", availability="2024-08-01T00:00:00Z")
    reopened = service.get(first["object_id"])
    assert "EVD-6" not in reopened["memo"]["manifest"]["evidence_dependencies"]


# ------------------------------------------------------------------- change detection
def test_superseding_evidence_names_the_affected_claim(db):
    _seed(db)
    memo = _memo(db)
    _evidence(db, evidence_id="EVD-1A", concept="revenue", value="111000000",
              revision_kind="amendment", supersedes="EVD-1",
              availability="2024-09-01T00:00:00Z")
    report = change_detection.check(db, memo)
    assert report["status"] == "requires_review"
    finding = next(item for item in report["findings"] if item["category"] == "superseded_evidence")
    assert finding["original_evidence_id"] == "EVD-1"
    assert finding["replacement_evidence_id"] == "EVD-1A"
    assert finding["original_value"] == "100000000"
    assert finding["replacement_value"] == "111000000"
    assert finding["auto_replay_performed"] is False
    assert any(claim["key"] == "revenue" for claim in finding["affected_claims"])
    assert report["replay"]["automatic"] is False


def test_unrelated_new_evidence_does_not_require_review(db):
    _seed(db)
    memo = _memo(db)
    _evidence(db, evidence_id="EVD-9", concept="assets", value="1",
              availability="2024-09-01T00:00:00Z")
    report = change_detection.check(db, memo)
    assert report["status"] == "unchanged"
    assert report["review_required"] is False
    finding = next(item for item in report["findings"] if item["category"] == "new_relevant_evidence")
    assert finding["affected_claims"] == []


def test_revised_market_observation_is_detected(db, master, apple_security):
    _seed(db)
    security_id = (
        apple_security if isinstance(apple_security, str) else apple_security["security_id"]
    )
    for revision in (1, 2):
        db.execute(
            "INSERT INTO bar (security_id, mic, interval, ts_utc, revision_seq, open, high, low,"
            " close, volume, currency, adjustment_status, source_id, observed_at, ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (security_id, "XNAS", "1d", "2024-06-28T20:00:00Z", revision, "1", "1", "1",
             "100" if revision == 1 else "101", "10", "USD", "raw", "sec-edgar",
             "2024-06-28T20:00:00Z", "2024-06-29T00:00:00Z"),
        )
    memo = _memo(db, pins=[{
        "kind": "market_observation", "security_id": security_id, "session": "2024-06-28",
        "revision": 1, "observation_id": "MOB-TEST", "provider": "sec-edgar",
    }])
    report = change_detection.check(db, memo)
    finding = next(item for item in report["findings"]
                   if item["category"] == "revised_market_observation")
    assert finding["recorded_revision"] == 1
    assert finding["stored_revision"] == 2


def test_missing_dependency_is_reported_not_repaired(db):
    _seed(db)
    memo = _memo(db)
    memo["manifest"]["evidence_dependencies"] = ["EVD-missing"]
    report = change_detection.check(db, memo)
    finding = next(item for item in report["findings"] if item["category"] == "missing_dependency")
    assert finding["replay_possible"] is False
    assert report["status"] == "requires_review"


def test_model_compiler_drift_is_detected(db):
    _seed(db)
    memo = _memo(db, compiler="atlas.fec.compiler.v0")
    report = change_detection.check(db, memo)
    assert any(item["category"] == "model_version_incompatible" for item in report["findings"])


def test_unchanged_memo_reports_unchanged(db):
    _seed(db)
    report = change_detection.check(db, _memo(db))
    assert report["status"] == "unchanged"
    assert report["categories"] == ["unchanged"]
    assert report["impact"]["claims_affected"] == []


# ----------------------------------------------------------------------- integrity
def test_statistical_integrity_is_never_passed_by_a_model(db):
    _seed(db)
    analysis = _analysis()
    integrity = integrity_report(analysis, _claims(db, analysis))
    assert integrity["dimensions"]["statistical"]["outcome"] == "not_applicable"
    assert "pass" not in integrity["dimensions"]["statistical"]["outcome"]
    assert set(integrity["dimensions"]) == {"evidence", "computational", "statistical", "decision"}


def test_integrity_failure_is_named(db):
    _seed(db)
    analysis = _analysis(arithmetic=False)
    integrity = integrity_report(analysis, _claims(db, analysis))
    assert integrity["dimensions"]["computational"]["outcome"] == "fail"
    assert any(item["dimension"] == "computational" for item in integrity["failures"])


# ---------------------------------------------------------------------- narration
def test_bank_report_narrative_names_the_bank_method():
    bank = methodology_narrative({
        "method": "residual_income_equity", "business_model": "bank holding company",
        "sic": "6021", "financial_institution": True, "rejected_method": "unlevered_fcff_dcf",
    })
    assert "residual_income_equity" in bank
    assert "bank holding company" in bank
    assert "non-financial operating company" not in bank



def test_clause_registry_is_consistent():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "artifacts" / "research_memo_clauses.json").read_text())
    assert payload["spec_version"] == "3.0.0"
    ids = [item["clause_id"] for item in payload["clauses"]]
    assert len(ids) == len(set(ids))
    statuses = {
        "vision_only", "implemented_unverified", "prototype_verified",
        "implemented_verified", "production_eligible", "deprecated_or_invalidated",
    }
    for item in payload["clauses"]:
        assert item["status"] in statuses, item["clause_id"]
        assert 1 <= item["section"] <= 61
        if item["status"] != "vision_only":
            assert item["implemented_by"], item["clause_id"]
            assert item["tests"], item["clause_id"]
        for node in item["tests"]:
            assert (root / node.split("::")[0]).exists(), node


def test_industrial_report_narrative_names_the_dcf():
    industrial = methodology_narrative({
        "method": "unlevered_fcff_dcf", "business_model": "operating company",
        "sic": "3571", "financial_institution": False,
    })
    assert "unlevered_fcff_dcf" in industrial
    assert "operating company" in industrial
    assert "not applied" not in industrial
