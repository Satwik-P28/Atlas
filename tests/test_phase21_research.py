"""Phase 2.1 research tests: contracts, evidence links, ratio/market validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.core.errors import ValidationError
from atlas.evidence.kernel import EvidenceKernel
from atlas.research import objects, validation


def _document(**overrides):
    document = {
        "schema_version": objects.SCHEMA_VERSION,
        "kind": "dataset",
        "name": "IBM annual fundamentals",
        "version": "1.0.0",
        "status": "validated",
        "description": "Annual IBM observations used by the demo research notebook.",
        "as_of": "2026-11-04T00:00:00Z",
        "mode": "public_available",
        "evidence_ids": ["EV-PLACEHOLDER"],
        "spec": {
            "universe": ["IBM"],
            "fields": ["revenue", "net_income"],
            "frequency": "annual",
            "adjustment": "split-adjusted",
        },
        "limitations": ["Single issuer; not a peer universe."],
    }
    document.update(overrides)
    return document


def test_contract_rejects_unknown_fields_code_and_bad_semver():
    with pytest.raises(ValidationError):
        objects.validate_document(_document(extra="nope"))
    with pytest.raises(ValidationError):
        objects.validate_document(_document(spec={"universe": ["IBM"], "fields": [], "frequency": "annual",
                                                   "adjustment": "raw", "code": "print(1)"}))
    with pytest.raises(ValidationError):
        objects.validate_document(_document(version="v1"))
    with pytest.raises(ValidationError):
        objects.validate_document(_document(kind="black_box"))


def test_contract_requires_spec_fields_per_kind():
    with pytest.raises(ValidationError):
        objects.validate_document(_document(spec={"universe": ["IBM"]}))
    model = _document(kind="model", spec={"inputs": ["price"], "outputs": ["signal"], "method": "sma",
                                          "assumptions": [], "validation": "walk-forward"})
    assert model["kind"] == "model"


def test_store_roundtrip_links_evidence_and_reports_impact(db, make_fact):
    fact = make_fact()
    EvidenceKernel(db).ingest(fact)
    document = _document(evidence_ids=[fact.evidence_id])
    store = objects.ResearchObjectStore(db)
    created = store.create(document)
    assert created["content_hash"] == objects.content_hash(document)
    assert created["evidence"][0]["evidence_id"] == fact.evidence_id
    assert created["document"]["name"] == document["name"]
    assert store.list(kind="dataset")[0]["object_id"] == created["object_id"]
    impact = store.evidence_impact(fact.evidence_id)
    assert impact["research_objects"][0]["object_id"] == created["object_id"]
    with pytest.raises(ValidationError):
        store.create(document)


def test_store_rejects_unknown_evidence(db):
    with pytest.raises(ValidationError):
        objects.ResearchObjectStore(db).create(_document(evidence_ids=["EV-missing"]))


def _metrics():
    metrics = {
        "revenue": {"value": 100.0, "evidence_ids": ["E-rev"]},
        "net_income": {"value": 10.0, "evidence_ids": ["E-ni"]},
        "equity": {"value": 50.0, "evidence_ids": ["E-eq"]},
        "shares_outstanding": {"value": 10.0, "evidence_ids": ["E-sh"]},
        "market_cap": {"value": 1000.0, "evidence_ids": ["E-sh"]},
        "pe": {"value": 100.0, "evidence_ids": ["E-ni", "E-sh"]},
        "earnings_yield": {"value": 0.01, "evidence_ids": ["E-ni", "E-sh"]},
        "net_margin": {"value": 0.1, "evidence_ids": ["E-ni", "E-rev"]},
        "total_debt": {"value": 20.0, "evidence_ids": ["E-d"]},
        "cash_and_equivalents": {"value": 5.0, "evidence_ids": ["E-c"]},
        "ev": {"value": 1015.0, "evidence_ids": ["E-sh"]},
        "operating_cash_flow": {"value": 10.0, "evidence_ids": ["E-ocf"]},
        "capex": {"value": 2.0, "evidence_ids": ["E-capex"]},
        "free_cash_flow": {"value": 8.0, "evidence_ids": ["E-ocf"]},
        "fcf_yield": {"value": 0.008, "evidence_ids": ["E-ocf"]},
        "book_to_market": {"value": 0.05, "evidence_ids": ["E-eq"]},
    }
    return {**metrics, "price": 100.0, "price_as_of": "2024-01-02"}


def test_ratio_validator_passes_consistent_metrics_and_catches_a_tampered_value():
    checks = validation.validate_ratios(_metrics())
    assert checks and all(check["passed"] for check in checks)
    tampered = _metrics()
    tampered["net_margin"]["value"] = 0.2
    failed = validation.validate_ratios(tampered)
    assert any(not check["passed"] and "net margin" in check["name"] for check in failed)


def test_valuation_identity_pe_times_yield():
    checks = validation.validate_ratios(_metrics())
    identity = next(check for check in checks if check["name"] == "P/E x earnings yield = 1")
    assert identity["passed"]
    assert Decimal(identity["difference"]) <= Decimal("1e-9")
