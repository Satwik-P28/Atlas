"""Reverse dependency index: recording, traversal, staleness, integrity."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from atlas.core.errors import MissingDataError, ValidationError
from atlas.core.temporal import ReportingPeriod, availability_from_instant
from atlas.dependencies import DependencyIndex, computation_id
from atlas.evidence.kernel import EvidenceKernel
from atlas.evidence.model import EvidenceRecord, lineage_step

ENTITY = "ISS-CIK0000320193"
PERIOD = ReportingPeriod(end=date(2024, 3, 31), start=date(2024, 1, 1), fiscal_year=2024, fiscal_period="Q1")
GROSS_PROFIT_RULE = "atlas.derived.gross_profit.v1"
TOTAL_DEBT_RULE = "atlas.derived.total_debt.v1"


def source_fact(
    kernel: EvidenceKernel,
    *,
    concept: str,
    value: str,
    instant: str,
    accession: str,
) -> EvidenceRecord:
    record = EvidenceRecord.build(
        entity_id=ENTITY,
        entity_kind="issuer",
        concept=concept,
        source_id="sec-edgar",
        unit="USD",
        availability=availability_from_instant(instant, "test.acceptance"),
        period=PERIOD,
        value=Decimal(value),
        quality="verified",
        verification="source_primary",
        accession_number=accession,
        form_type="10-Q",
        observed_at="2024-09-01T00:00:00Z",
        taxonomy="us-gaap",
        source_concept="Revenues",
    )
    kernel.ingest(record)
    return record


def derived_fact(
    kernel: EvidenceKernel,
    *,
    concept: str,
    value: str,
    rule: str,
    inputs: list[EvidenceRecord],
    instant: str = "2024-09-02T00:00:00Z",
) -> EvidenceRecord:
    lineage = {
        "rule": rule,
        "description": "test derivation",
        "steps": [lineage_step("subtract", detail="inputs combined", rule=rule)],
        "inputs": [
            {
                "evidence_id": item.evidence_id,
                "concept": item.concept,
                "value": item.value_numeric,
                "unit": item.unit,
            }
            for item in inputs
        ],
    }
    record = EvidenceRecord.build(
        entity_id=ENTITY,
        entity_kind="issuer",
        concept=concept,
        source_id="atlas-synthetic",
        unit="USD",
        availability=availability_from_instant(instant, "test.derivation"),
        period=PERIOD,
        value=Decimal(value),
        quality="unverified",
        verification="unchecked",
        derivation_kind="derived_calculation",
        derivation_rule=rule,
        lineage=lineage,
        observed_at=instant,
    )
    kernel.ingest(record)
    return record


@pytest.fixture()
def graph(kernel):
    revenue = source_fact(kernel, concept="revenue", value="100", instant="2024-05-01T10:00:00Z", accession="A1")
    cost = source_fact(
        kernel, concept="cost_of_revenue", value="60", instant="2024-05-01T10:00:00Z", accession="A1"
    )
    gross = derived_fact(
        kernel, concept="gross_profit", value="40", rule=GROSS_PROFIT_RULE, inputs=[revenue, cost]
    )
    return kernel, revenue, cost, gross


def test_derived_ingest_is_indexed_automatically(graph):
    _, revenue, cost, gross = graph
    index = DependencyIndex(graph[0].db)
    computation = index.for_output(gross.evidence_id)
    assert computation is not None
    assert computation.rule_id == GROSS_PROFIT_RULE
    assert computation.computation_id == computation_id(GROSS_PROFIT_RULE, gross.evidence_id)
    roles = {item["role"]: item["evidence_id"] for item in computation.inputs}
    assert roles == {"revenue": revenue.evidence_id, "cost_of_revenue": cost.evidence_id}


def test_reverse_lookup_finds_direct_dependents(graph):
    _, revenue, cost, gross = graph
    index = DependencyIndex(graph[0].db)
    assert [c.output_evidence_id for c in index.dependents(revenue.evidence_id)] == [gross.evidence_id]
    assert [c.output_evidence_id for c in index.dependents(cost.evidence_id)] == [gross.evidence_id]
    assert index.dependents(gross.evidence_id) == []


def test_impact_reports_outputs_and_notes(graph):
    kernel, revenue, _, gross = graph
    impact = DependencyIndex(kernel.db).impact(revenue.evidence_id)
    assert impact.affected_outputs == [gross.evidence_id]
    assert impact.stale == []
    assert any("no derived computation" in note for note in DependencyIndex(kernel.db).impact(gross.evidence_id).notes)


def test_transitive_dependents_walk_multiple_levels(graph):
    kernel, revenue, cost, gross = graph
    total = derived_fact(
        kernel,
        concept="total_debt",
        value="40",
        rule=TOTAL_DEBT_RULE,
        inputs=[gross],
        instant="2024-09-03T00:00:00Z",
    )
    index = DependencyIndex(kernel.db)
    levels = index.transitive_dependents(revenue.evidence_id)
    depth_by_output = {computation.output_evidence_id: depth for depth, computation in levels}
    assert depth_by_output[gross.evidence_id] == 1
    assert depth_by_output[total.evidence_id] == 2


def test_superseding_an_input_marks_computations_stale(graph):
    kernel, revenue, _, gross = graph
    index = DependencyIndex(kernel.db)
    assert index.stale([revenue.evidence_id]) == []

    newer = source_fact(
        kernel, concept="revenue", value="120", instant="2024-08-01T10:00:00Z", accession="A2"
    )
    stale = index.stale([revenue.evidence_id])
    assert len(stale) == 1
    assert stale[0]["output_evidence_id"] == gross.evidence_id
    assert stale[0]["stale_reasons"][0]["reason"] == "input_superseded"
    assert newer.evidence_id in stale[0]["stale_reasons"][0]["superseded_by"]

    impact = index.impact(revenue.evidence_id)
    assert impact.stale and impact.stale[0]["computation_id"] == stale[0]["computation_id"]


def test_reasserting_the_same_value_does_not_mark_stale(graph):
    kernel, revenue, _, _ = graph
    source_fact(kernel, concept="revenue", value="100", instant="2024-08-01T10:00:00Z", accession="A3")
    assert DependencyIndex(kernel.db).stale([revenue.evidence_id]) == []


def test_recording_is_idempotent(graph):
    kernel, revenue, cost, gross = graph
    index = DependencyIndex(kernel.db)
    first = index.for_output(gross.evidence_id)
    again = index.record(
        rule_id=GROSS_PROFIT_RULE,
        output_evidence_id=gross.evidence_id,
        inputs=[(revenue.evidence_id, "revenue"), (cost.evidence_id, "cost_of_revenue")],
    )
    assert again.computation_id == first.computation_id
    assert len(again.inputs) == 2
    assert index.summary()["computations"] == 1
    assert index.summary()["inputs"] == 2


def test_record_rejects_non_derived_output(graph):
    kernel, revenue, _, _ = graph
    with pytest.raises(ValidationError):
        DependencyIndex(kernel.db).record(
            rule_id=GROSS_PROFIT_RULE,
            output_evidence_id=revenue.evidence_id,
            inputs=[revenue.evidence_id],
        )


def test_record_rejects_missing_input(graph):
    kernel, _, _, gross = graph
    with pytest.raises(MissingDataError):
        DependencyIndex(kernel.db).record(
            rule_id=GROSS_PROFIT_RULE,
            output_evidence_id=gross.evidence_id,
            inputs=["EV-DOES-NOT-EXIST"],
        )


def test_record_rejects_empty_inputs(graph):
    kernel, _, _, gross = graph
    with pytest.raises(ValidationError):
        DependencyIndex(kernel.db).record(
            rule_id=GROSS_PROFIT_RULE, output_evidence_id=gross.evidence_id, inputs=[]
        )


def test_record_rejects_self_reference(graph):
    kernel, _, _, gross = graph
    with pytest.raises(ValidationError):
        DependencyIndex(kernel.db).record(
            rule_id=GROSS_PROFIT_RULE, output_evidence_id=gross.evidence_id, inputs=[gross.evidence_id]
        )


def test_derived_record_without_inputs_is_not_indexed(graph, kernel_fixture=None):
    kernel, _, _, _ = graph
    index = DependencyIndex(kernel.db)
    record = EvidenceRecord.build(
        entity_id=ENTITY,
        entity_kind="issuer",
        concept="free_cash_flow",
        source_id="atlas-synthetic",
        unit="USD",
        availability=availability_from_instant("2024-09-05T00:00:00Z", "test.derivation"),
        period=PERIOD,
        value=Decimal("7"),
        derivation_kind="derived_calculation",
        derivation_rule="atlas.derived.free_cash_flow.v1",
        lineage={"rule": "atlas.derived.free_cash_flow.v1"},
        observed_at="2024-09-05T00:00:00Z",
    )
    kernel.ingest(record)
    assert index.for_output(record.evidence_id) is None
    assert index.backfill() == 0


def test_backfill_indexes_preexisting_derived_records(graph):
    kernel, revenue, cost, gross = graph
    db = kernel.db
    # Simulate a record stored before the index existed by removing the index rows.
    db.execute("DELETE FROM computation_input")
    db.execute("DELETE FROM computation")
    index = DependencyIndex(db)
    assert index.for_output(gross.evidence_id) is None
    assert index.backfill() == 1
    computation = index.for_output(gross.evidence_id)
    assert computation is not None
    assert {item["evidence_id"] for item in computation.inputs} == {revenue.evidence_id, cost.evidence_id}


def test_integrity_reports_structural_problems(graph):
    kernel, revenue, _, gross = graph
    index = DependencyIndex(kernel.db)
    assert index.integrity()["ok"] is True

    # An index row whose input has vanished is only possible with FK enforcement off,
    # which is exactly the kind of drift this check exists to surface.
    db = kernel.db
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute(
        "INSERT INTO computation_input (computation_id, evidence_id, role) VALUES (?,?,?)",
        (index.for_output(gross.evidence_id).computation_id, "EV-GONE", "ghost"),
    )
    db.execute("PRAGMA foreign_keys=ON")
    report = index.integrity()
    assert report["ok"] is False
    assert report["findings"][0]["code"] == "dangling_computation_input"
