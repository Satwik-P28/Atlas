"""Evaluation-integrity regressions: source bytes, accession scope, operand units, scoring.

These tests are adversarial on purpose. They forge the conditions a research harness must
survive — altered snapshots, a right number from the wrong filing, arithmetic across unit
banners or currencies — and assert that the harness fails closed instead of publishing a
confident answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.research import answer_semantics as semantics
from atlas.research.geometry_resolution import (
    GeometryCellRef,
    GeometryDocument,
    GeometryResolution,
    GeometryResolver,
    SourceIntegrityError,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "answer_semantics"
DOC = ROOT / "docs" / "ANSWER_SEMANTICS_EVALUATION.md"

REVENUE = """<html><body><p>CONSOLIDATED STATEMENTS OF INCOME</p><p>(In millions)</p>
<table><tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>100,000</td><td>90,000</td></tr>
<tr><td>Cost of sales</td><td>60,000</td><td>55,000</td></tr>
<tr><td>Gross profit</td><td>40,000</td><td>35,000</td></tr></table></body></html>"""


def _doc(html: str, accession: str, cik: str = "0000000031") -> GeometryDocument:
    return GeometryDocument.from_html(html, accession=accession, cik=cik)


# ------------------------------------------------------------------ 1. source bytes
def test_document_refuses_bytes_that_do_not_match_the_manifest_digest():
    with pytest.raises(SourceIntegrityError):
        GeometryDocument.from_html(REVENUE.encode(), accession="A-1",
                                   document_sha256="0" * 64)


def _manifest_and_corpus(tmp_path: Path, html: bytes) -> tuple[Path, Path]:
    import hashlib
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "A-1.html").write_bytes(html)
    manifest = {
        "filings": [{
            "accession": "A-1", "cik": "0000000031",
            "document_sha256": hashlib.sha256(REVENUE.encode()).hexdigest(),
            "availability_time": "2023-02-10T12:00:00Z",
        }]
    }
    corpus = {"filings": [{"key": "T", "accession": "A-1", "cik": "0000000031"}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "corpus.json").write_text(json.dumps(corpus))
    return tmp_path / "manifest.json", tmp_path / "corpus.json"


def test_load_documents_fails_closed_on_altered_snapshot(tmp_path):
    manifest_path, corpus_path = _manifest_and_corpus(
        tmp_path, REVENUE.replace("100,000", "999,999").encode())
    with pytest.raises(SourceIntegrityError):
        semantics.load_documents(json.loads(manifest_path.read_text()),
                                 tmp_path / "snapshots",
                                 corpus=json.loads(corpus_path.read_text()))


def test_load_documents_fails_closed_on_missing_snapshot(tmp_path):
    manifest_path, corpus_path = _manifest_and_corpus(tmp_path, REVENUE.encode())
    (tmp_path / "snapshots" / "A-1.html").unlink()
    with pytest.raises(SourceIntegrityError):
        semantics.load_documents(json.loads(manifest_path.read_text()),
                                 tmp_path / "snapshots",
                                 corpus=json.loads(corpus_path.read_text()))


def test_load_documents_fails_closed_on_undeclared_filing(tmp_path):
    import hashlib
    manifest_path, corpus_path = _manifest_and_corpus(tmp_path, REVENUE.encode())
    manifest = json.loads(manifest_path.read_text())
    manifest["filings"].append({"accession": "B-2", "cik": "0000000031",
                                "document_sha256": hashlib.sha256(b"").hexdigest()})
    with pytest.raises(SourceIntegrityError):
        semantics.load_documents(manifest, tmp_path / "snapshots",
                                 corpus=json.loads(corpus_path.read_text()))


def test_load_documents_reports_a_verified_digest_for_the_parsed_bytes(tmp_path):
    manifest_path, corpus_path = _manifest_and_corpus(tmp_path, REVENUE.encode())
    documents = semantics.load_documents(json.loads(manifest_path.read_text()),
                                         tmp_path / "snapshots",
                                         corpus=json.loads(corpus_path.read_text()))
    assert documents["A-1"].document_sha256 == json.loads(
        manifest_path.read_text())["filings"][0]["document_sha256"]


# ------------------------------------------------------------------ 2. accession scope
def test_accession_pin_reads_only_the_named_filing():
    original = _doc(REVENUE, "A-1")
    amended = _doc(REVENUE.replace("100,000", "101,000"), "A-2")
    resolver = GeometryResolver([original, amended])
    pinned = resolver.resolve("revenue", "2022", cik="0000000031", accession="A-1")
    assert pinned.status == "resolved" and pinned.cell is not None
    assert (pinned.cell.accession, pinned.cell.raw) == ("A-1", "100,000")
    # The same corpus without a pin is a vintage ambiguity, which as-of mode must report.
    as_of = resolver.resolve("revenue", "2022", cik="0000000031")
    assert as_of.status == "ambiguous" and as_of.reason == "conflicting_row_values"


def test_accession_pin_that_is_absent_refuses_instead_of_falling_back():
    resolver = GeometryResolver([_doc(REVENUE, "A-1")])
    resolution = resolver.resolve("revenue", "2022", cik="0000000031", accession="A-9")
    assert resolution.status == "not_found"
    assert resolution.reason == "accession_not_in_corpus"


def _question(**overrides) -> semantics.Question:
    base = dict(
        id="T-1", question="q", cik="0000000031", accession="A-1",
        cutoff="2024-01-01T00:00:00Z", operator="lookup", concept="revenue", period="2022",
        xbrl=[], expect={"outcome": "answered", "scale": 6, "citations": [
            {"accession": "A-1", "row_labels": ["Net sales"], "raw": "100,000", "scale": 6,
             "period": "2022"}]},
        gold_class="xbrl_verified", tags=[], review={}, scope="accession")
    base.update(overrides)
    return semantics.Question(**base)


def test_accession_scoped_question_abstains_when_only_another_filing_has_the_row():
    # The corpus holds the prior-year filing only: an accession-scoped question must not
    # answer from it even though the row and period exist there.
    resolver = GeometryResolver([_doc(REVENUE, "A-2")])
    response = semantics.geometry_response(_question(accession="A-1"), resolver)
    assert response["outcome"] == "abstained"
    assert response["reason"].startswith("geometry:not_found:accession_not_in_corpus")


def test_as_of_scope_is_the_explicit_multi_filing_mode():
    resolver = GeometryResolver([_doc(REVENUE, "A-1"), _doc(REVENUE, "A-2")])
    question = _question(scope="as_of")
    response = semantics.geometry_response(question, resolver)
    assert response["outcome"] == "answered"
    assert response["citations"][0]["accession"] == "A-1"


# ------------------------------------------------------------------ 3. operand integrity
def _cell(**overrides) -> SimpleNamespace:
    base = dict(accession="A-1", document_sha256="d" * 64, row_label="Net sales",
                raw="100", scale=6, currency="USD", period="2022",
                statement_family="income", entity_scope="consolidated")
    base.update(overrides)
    return SimpleNamespace(**base)


def _ref(**overrides) -> GeometryCellRef:
    base = dict(accession="A-1", document_sha256="d" * 64, table_index=0, table_digest="t",
                table_sha="t", row=1, column=1, row_label="Net sales", column_header="2022",
                period="2022", scale=6, currency="USD", raw="100,000", value="100000",
                statement_family="income", statement_title="CONSOLIDATED STATEMENTS OF INCOME",
                entity_scope="consolidated")
    base.update(overrides)
    return GeometryCellRef(**base)


class _ForgedResolver:
    """A resolver whose cells are chosen by the test, so an adversarial filing can be forged.

    The point of these cases is not what a real filing prints but what the *response path* does
    with operands that do not share a unit, a source or a scope. Injecting the cells directly is
    the only way to forge exactly one incompatible dimension at a time.
    """

    def __init__(self, mapping: dict[tuple[str, str], GeometryCellRef]) -> None:
        self.mapping = mapping

    def resolve(self, concept: str, period: str, **_scope: object) -> GeometryResolution:
        cell = self.mapping.get((concept, period))
        if cell is None:
            return GeometryResolution("not_found", concept, period, reason="no_candidate_row")
        return GeometryResolution("resolved", concept, period, cell=cell, score=3.0)


def test_margin_refuses_operands_from_different_unit_scales():
    resolver = _ForgedResolver({
        ("gross_profit", "2022"): _ref(row_label="Gross profit", raw="400,000", value="400000",
                                       scale=3),
        ("revenue", "2022"): _ref(raw="1,000", value="1000", scale=6),
    })
    question = _question(operator="margin", expect={
        "outcome": "answered", "scale": 6, "numerator": "gross_profit",
        "citations": [{"accession": "A-1", "raw": "400,000", "scale": 3, "period": "2022"},
                      {"accession": "A-1", "raw": "1,000", "scale": 6, "period": "2022"}]})
    response = semantics.geometry_response(question, resolver)
    assert response["outcome"] == "abstained"
    assert response["reason"] == "unit_integrity:mixed_scale"


def test_percentage_change_refuses_operands_from_different_filings():
    resolver = _ForgedResolver({
        ("revenue", "2022"): _ref(accession="A-1", period="2022", raw="100,000"),
        ("revenue", "2021"): _ref(accession="A-2", period="2021", raw="90,000",
                                   document_sha256="e" * 64),
    })
    question = _question(scope="as_of", operator="percentage_change", expect={
        "outcome": "answered", "scale": 6, "prior_period": "2021",
        "citations": [{"accession": "A-1", "raw": "100,000", "scale": 6, "period": "2022"},
                      {"accession": "A-2", "raw": "90,000", "scale": 6, "period": "2021"}]})
    response = semantics.geometry_response(question, resolver)
    assert response["outcome"] == "abstained"
    assert response["reason"] == "unit_integrity:mixed_source_accession"


def test_percentage_change_refuses_operands_in_different_currencies():
    resolver = _ForgedResolver({
        ("revenue", "2022"): _ref(currency="USD", period="2022", raw="100,000"),
        ("revenue", "2021"): _ref(currency="EUR", period="2021", raw="90,000"),
    })
    question = _question(operator="percentage_change", expect={
        "outcome": "answered", "scale": 6, "prior_period": "2021",
        "citations": [{"accession": "A-1", "raw": "100,000", "scale": 6, "period": "2022"},
                      {"accession": "A-1", "raw": "90,000", "scale": 6, "period": "2021"}]})
    response = semantics.geometry_response(question, resolver)
    assert response["outcome"] == "abstained"
    assert response["reason"] == "unit_integrity:mixed_currency"


@pytest.mark.parametrize(("left", "right", "reason"), [
    ({"scale": 6}, {"scale": 3}, "mixed_scale"),
    ({"currency": "USD"}, {"currency": "EUR"}, "mixed_currency"),
    ({"accession": "A-1"}, {"accession": "A-2"}, "mixed_source_accession"),
    ({"document_sha256": "d" * 64}, {"document_sha256": "e" * 64}, "mixed_source_document"),
    ({"entity_scope": "consolidated"}, {"entity_scope": "segment"}, "mixed_entity_scope"),
    ({"period": "2022"}, {"period": "2021"}, "incompatible_periods"),
])
def test_operand_integrity_refuses_incompatible_operands(left, right, reason):
    assert semantics.operand_integrity([_cell(**left), _cell(**right)], "margin") == reason


def test_operand_integrity_refuses_segment_scope_even_when_consistent():
    cells = [_cell(entity_scope="segment"), _cell(entity_scope="segment")]
    assert semantics.operand_integrity(cells, "margin") == "non_consolidated_scope"


def test_operand_integrity_refuses_a_missing_scale():
    assert semantics.operand_integrity([_cell(scale=None), _cell()], "margin") == "missing_scale"


def test_operand_integrity_accepts_one_consolidated_filing():
    assert semantics.operand_integrity([_cell(), _cell()], "margin") is None


# ------------------------------------------------------------------ 4. scoring contract
def _gold(value: str = "100000000") -> dict:
    return {"class": "xbrl_verified", "inputs": [{"accn": "A-1", "value": value}],
            "value_display": value}


def _answer(**overrides) -> dict:
    base = {"runner": "geometry", "outcome": "answered", "value_economic": "100000000",
            "value_display": "100000", "period": "2022", "scale": 6, "currency": "USD",
            "accession": "A-1",
            "citations": [{"accession": "A-1", "row_label": "Net sales", "raw": "100,000",
                           "period": "2022", "scale": 6, "column_label": "2022"}],
            "elapsed_ms": 1.0}
    base.update(overrides)
    return base


def test_a_correct_amount_with_the_wrong_cited_row_is_not_correct():
    documents = {"A-1": _doc(REVENUE, "A-1")}
    response = _answer()
    response["citations"][0]["row_label"] = "Cost of sales"
    result = semantics.score(_question(), _gold(), response, documents)
    assert result["value_ok"] and result["period_ok"] and result["unit_ok"]
    assert result["citation_ok"] is False
    assert result["correct"] is False
    assert result["status"] == "citation_failure"


def test_a_correct_amount_from_the_wrong_filing_is_not_correct():
    documents = {"A-1": _doc(REVENUE, "A-1")}
    response = _answer(accession="A-2")
    response["citations"][0]["accession"] = "A-2"
    result = semantics.score(_question(), _gold(), response, documents)
    assert result["numerical_ok"] is True
    assert result["source_ok"] is False
    assert result["correct"] is False
    assert result["status"] == "citation_failure"


def test_summary_separates_numerical_citation_and_combined_accuracy():
    documents = {"A-1": _doc(REVENUE, "A-1")}
    question = _question()
    golds = {question.id: _gold()}
    good = semantics.score(question, _gold(), _answer(), documents)
    mislabelled = semantics.score(question, _gold(), _answer(accession="A-2", citations=[
        {"accession": "A-2", "row_label": "Net sales", "raw": "100,000", "period": "2022",
         "scale": 6, "column_label": "2022"}]), documents)
    summary = semantics.summarise([good, mislabelled], golds, [question])
    assert summary["numerical_accuracy"] == 1.0
    assert summary["citation_accuracy"] == 0.5
    assert summary["source_accuracy"] == 0.5
    assert summary["exact_answer_rate"] == 0.5
    assert summary["citation_failures"] == 1


# ------------------------------------------------------------------ 5. fixtures and report
def test_every_question_is_accession_scoped_unless_declared_as_of():
    questions = semantics.load_questions()
    as_of = {question.id for question in questions if question.scope == "as_of"}
    assert as_of == {"AS-23"}, as_of
    for question in questions:
        if question.scope != "accession":
            continue
        for selector in question.xbrl:
            assert selector["accn"] == question.accession, question.id
        for citation in question.expect.get("citations", []):
            assert citation.get("accession", question.accession) == question.accession


def test_ledger_records_every_dropped_or_replaced_question():
    ledger = json.loads((FIXTURES / "ledger.json").read_text())
    keys = {entry["key"] for entry in ledger["entries"]}
    assert {"WMT-total-revenues", "DE-operating-cash-flow", "DE-net-income-fy2018"} <= keys
    for entry in ledger["entries"]:
        assert entry["kind"] in {"dropped", "replaced", "included_abstention", "excluded"}
        assert entry["reason"] and entry["detail"], entry["key"]
        assert entry["status"] in {"not_scored", "scored"}, entry["key"]
    summary = ledger["summary"]
    dropped = [entry for entry in ledger["entries"] if entry["kind"] == "dropped"]
    replaced = [entry for entry in ledger["entries"] if entry["kind"] == "replaced"]
    assert summary["attempted"] == summary["scored"] + len(dropped) + len(replaced)
    assert summary["dropped"] == len(dropped) and summary["replaced"] == len(replaced)
    questions = semantics.load_questions()
    assert summary["scored"] == len(questions)
    scored_keys = {entry["key"] for entry in ledger["entries"] if entry["status"] == "scored"}
    assert scored_keys <= {question.id for question in questions}


def test_holdout_cohort_is_frozen_before_any_resolver_run():
    plan = json.loads((FIXTURES / "holdout_plan.json").read_text())
    universe = json.loads((FIXTURES / "holdout_universe.json").read_text())
    corpus = json.loads((FIXTURES / "corpus.json").read_text())
    development = {str(filing["cik"]).lstrip("0").zfill(10) for filing in corpus["filings"]}
    selected = {str(filing["cik"]).lstrip("0").zfill(10) for filing in plan["filings"]}
    assert plan["status"] == "selected_not_yet_ingested"
    assert len(plan["filings"]) == universe["selection_count"]
    assert not selected & development, "the holdout must not contain a development issuer"
    assert selected <= {str(filing["cik"]).lstrip("0").zfill(10)
                        for filing in universe["candidates"]}
    accessions = [filing["accession"] for filing in plan["filings"]]
    assert len(set(accessions)) == len(accessions)
    assert plan["commitment"] and plan["protocol"]["freeze"]
    assert all(filing["period_of_report"][:4] == str(universe["target_fiscal_year"])
               for filing in plan["filings"])


def test_report_corpus_table_is_generated_from_the_canonical_corpus():
    from atlas.research.report_tables import render_corpus_table, extract_block

    text = DOC.read_text()
    assert render_corpus_table() in text
    assert extract_block(text) == render_corpus_table()
    corpus = json.loads((FIXTURES / "corpus.json").read_text())
    for line in render_corpus_table().splitlines():
        if not line.startswith("| ") or line.startswith("| ---") or line.startswith("| key "):
            continue
        accession = line.split("|")[4].strip()
        assert accession in {filing["accession"] for filing in corpus["filings"]}, accession
