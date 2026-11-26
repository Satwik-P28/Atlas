"""Answer-semantics milestone: geometry, resolution scope, gold integrity and scoring.

Everything here is offline. The geometry and resolver cases use small project-authored HTML
that reproduces a layout class seen in real filings (merged header groups, in-table segment
banners, "except share amounts" unit lines); it contains no filing text. The gold-integrity
tests read the committed corpus, question and XBRL fact files and need no network.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research import answer_semantics as semantics
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.geometry_resolution import GeometryDocument, GeometryResolver
from atlas.research.knowledge import KnowledgeEngine
from atlas.research.table_geometry import detect_statement_scale, parse_tables
from atlas.storage.db import Database

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "answer_semantics"


# --------------------------------------------------------------------------- geometry
MERGED_HEADER = """<html><body>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p>
<table>
<tr><td colspan="3">Year Ended December 31,</td><td colspan="3">2022</td><td colspan="3">2021</td></tr>
<tr><td colspan="3">Net Operating Revenues</td><td>$</td><td>43,004</td><td></td><td>$</td><td>38,655</td><td></td></tr>
<tr><td colspan="3">Cost of goods sold</td><td>18,000</td><td>18,000</td><td></td><td>15,357</td><td>15,357</td><td></td></tr>
</table></body></html>"""

SEGMENT_BANNER = """<html><body>
<p>Item 8. Financial Statements</p>
<p>Note 4. Segment information</p>
<table>
<tr><td>Year ended December 31, 2018</td><td></td></tr>
<tr><td>Net Sales (Millions)</td><td>United States</td><td>Asia Pacific</td><td>Worldwide</td></tr>
<tr><td>Industrial</td><td>$</td><td>4,538</td><td>$</td><td>12,267</td></tr>
<tr><td>Total Company</td><td>$</td><td>12,840</td><td>$</td><td>32,765</td></tr>
</table></body></html>"""

CONSOLIDATED = """<html><body>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions, except number of shares which are reflected in thousands and per share amounts)</p>
<table>
<tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>32,765</td><td>31,657</td></tr>
<tr><td>Cost of sales</td><td>16,682</td><td>16,055</td></tr>
<tr><td>Gross profit</td><td>16,083</td><td>15,602</td></tr>
</table></body></html>"""


def _document(html: str, *, accession: str, cik: str = "0000000031",
              availability: str = "2023-02-10T12:00:00Z") -> GeometryDocument:
    # No digest argument: from_html hashes the bytes it parses, so every document carries its
    # own true digest and a test cannot accidentally assert a digest it never checked.
    return GeometryDocument.from_html(html, accession=accession, cik=cik,
                                      availability_time=availability)


def test_merged_header_columns_inherit_their_year():
    tables = parse_tables(MERGED_HEADER)
    table = tables[0]
    assert table.statement_family == "income"
    values = [(row, column, cell.text, table.period_for(column, row))
              for row, column, cell, _period in table.values()
              if cell.text == "43,004"]
    assert values, "the revenue cell was not extracted"
    _row, _column, _text, period = values[0]
    assert period == "2022"


def test_flattened_header_would_assign_the_wrong_year():
    """The defect this module exists for: dropping empty cells shifts the header index."""
    flattened_header = ["Year Ended December 31,", "2022", "2021"]
    flattened_row = ["Net Operating Revenues", "$", "43,004", "", "$", "38,655", ""]
    assert flattened_header[flattened_row.index("43,004")] == "2021"
    table = parse_tables(MERGED_HEADER)[0]
    cell = next(cell for row, column, cell, _ in table.values() if cell.text == "43,004")
    column = next(column for row, column, cell, _ in table.values() if cell.text == "43,004")
    assert table.period_for(column, 1) == "2022"
    assert cell.text == "43,004"


def test_segment_banner_row_is_not_a_data_row():
    tables = parse_tables(SEGMENT_BANNER)
    table = tables[0]
    banner_rows = [row for row in range(len(table.grid))
                   if table.label_of(row) == "Net Sales (Millions)"]
    assert banner_rows, "the banner row should still be parsed"
    for row in banner_rows:
        assert table.numeric_columns(row) == []


def test_unit_line_with_except_clause_is_read_as_the_amount_unit():
    assert detect_statement_scale(
        "(In millions, except number of shares which are reflected in thousands and per "
        "share amounts)")[0] == 6
    assert detect_statement_scale("(In thousands)")[0] == 3
    # Two units in the main clause is a genuine conflict, not a per-share exception.
    assert detect_statement_scale("(Dollars in millions and thousands)")[0] is None


def test_scale_comes_from_the_banner_above_a_statement():
    table = parse_tables(CONSOLIDATED)[0]
    assert table.scale == 6
    assert table.unit_basis == "detected"


# --------------------------------------------------------------------------- resolver
def test_resolver_reads_the_requested_period_column():
    resolver = GeometryResolver([_document(CONSOLIDATED, accession="A-1")])
    current = resolver.resolve("revenue", "2022", cik="0000000031")
    prior = resolver.resolve("revenue", "2021", cik="0000000031")
    assert current.status == "resolved" and current.cell is not None
    assert prior.status == "resolved" and prior.cell is not None
    assert (current.cell.raw, current.cell.period) == ("32,765", "2022")
    assert (prior.cell.raw, prior.cell.period) == ("31,657", "2021")
    assert "2021" in prior.cell.column_header


def test_resolver_never_reads_another_issuer():
    other = CONSOLIDATED.replace("32,765", "99,999")
    resolver = GeometryResolver([
        _document(CONSOLIDATED, accession="A-1", cik="0000000031"),
        _document(other, accession="B-1", cik="0000000099"),
    ])
    resolution = resolver.resolve("revenue", "2022", cik="0000000031")
    assert resolution.status == "resolved" and resolution.cell is not None
    assert resolution.cell.accession == "A-1"
    assert resolution.cell.value == "32765"


def test_resolver_refuses_conflicting_amounts_for_one_period():
    amended = CONSOLIDATED.replace("32,765", "32,700")
    resolver = GeometryResolver([
        _document(CONSOLIDATED, accession="A-1"),
        _document(amended, accession="A-2"),
    ])
    resolution = resolver.resolve("revenue", "2022", cik="0000000031",
                                  cutoff="2024-01-01T00:00:00Z")
    assert resolution.status == "ambiguous"
    assert resolution.reason == "conflicting_row_values"
    assert {candidate["value"] for candidate in resolution.candidates} == {"32765", "32700"}


def test_resolver_prefers_the_printed_total_over_a_component():
    html = """<html><body>
    <p>CONSOLIDATED STATEMENTS OF EARNINGS</p><p>(In millions)</p>
    <table>
    <tr><td></td><td>2018</td></tr>
    <tr><td>Sales</td><td>26,641</td></tr>
    <tr><td>Services</td><td>52,950</td></tr>
    <tr><td>Total revenue</td><td>79,591</td></tr>
    </table></body></html>"""
    resolver = GeometryResolver([_document(html, accession="A-3")])
    resolution = resolver.resolve("revenue", "2018", cik="0000000031")
    assert resolution.status == "resolved" and resolution.cell is not None
    assert resolution.cell.raw == "79,591"


def test_resolver_refuses_segment_tables_and_unknown_scale():
    resolver = GeometryResolver([_document(SEGMENT_BANNER, accession="A-4")])
    resolution = resolver.resolve("revenue", "2018", cik="0000000031")
    assert resolution.status in {"not_found", "period_not_located", "unit_unresolved"}


# --------------------------------------------------------------------------- gold
def test_gold_is_derived_from_committed_xbrl_facts_without_network():
    questions = semantics.load_questions()
    facts = semantics.load_facts()
    assert questions, "the held-out question set is empty"
    for question in questions:
        gold = semantics.derive_gold(question, facts)
        assert gold["class"] in {"xbrl_verified", "conflicting_evidence",
                                 "structurally_unanswerable"}, (question.id, gold)
        if gold["class"] == "xbrl_verified":
            assert gold["inputs"], question.id
            for item in gold["inputs"]:
                assert item["value"].lstrip("-").isdigit(), question.id


def test_gold_question_set_is_internally_consistent():
    corpus = {filing["accession"] for filing in semantics.load_corpus()["filings"]}
    questions = semantics.load_questions()
    ids = [question.id for question in questions]
    assert len(ids) == len(set(ids))
    for question in questions:
        assert question.accession in corpus, question.id
        for citation in question.expect.get("citations", []):
            assert citation.get("accession", question.accession) == question.accession, question.id
            assert citation.get("scale") == question.expect["scale"], question.id
        for selector in question.xbrl:
            assert selector["accn"] == question.accession, question.id
        if question.operator == "lookup" and question.gold_class == "xbrl_verified":
            assert len(question.expect["citations"]) == 1, question.id
        if question.gold_class in semantics.ABSTENTION_CLASSES:
            assert not question.xbrl, question.id


def test_select_fact_disambiguates_dimensional_duplicates():
    candidates = [{"val": 125_843_000_000, "tag": "Revenue"}, {"val": 33_717_000_000, "tag": "Revenue"}]
    from fractions import Fraction
    assert semantics.select_fact(candidates, Fraction(125_843_000_000), 6)["val"] == 125_843_000_000
    assert semantics.select_fact(candidates, None, None) is None
    assert semantics.select_fact(candidates, Fraction(7), 6) is None


def test_printed_cell_that_disagrees_with_xbrl_is_excluded_not_repaired():
    question = semantics.load_questions()[0]
    facts = semantics.load_facts()
    broken = dataclasses.replace(question, expect={
        **question.expect,
        "citations": [{**question.expect["citations"][0], "raw": "1,234"}]})
    gold = semantics.derive_gold(broken, facts)
    assert gold["class"] == "gold_inconsistent"


# --------------------------------------------------------------------------- scoring
def _question(**overrides) -> semantics.Question:
    base = dict(
        id="T-1", question="q", cik="0000000031", accession="A-1",
        cutoff="2024-01-01T00:00:00Z", operator="lookup", concept="revenue", period="2022",
        xbrl=[], expect={"outcome": "answered", "scale": 6, "citations": [
            {"accession": "A-1", "row_labels": ["Net sales"], "raw": "32,765", "scale": 6,
             "period": "2022"}]},
        gold_class="xbrl_verified", tags=[], review={})
    base.update(overrides)
    return semantics.Question(**base)


def _gold(value: str = "32765000000") -> dict:
    return {"class": "xbrl_verified", "inputs": [{"accn": "A-1", "value": value}],
            "value_display": value}


def _answer(**overrides) -> dict:
    base = {"runner": "geometry", "outcome": "answered", "value_economic": "32765000000",
            "value_display": "32765", "period": "2022", "scale": 6, "accession": "A-1",
            "citations": [{"accession": "A-1", "row_label": "Net sales", "raw": "32,765",
                           "period": "2022", "scale": 6, "column_label": "2022"}],
            "elapsed_ms": 1.0}
    base.update(overrides)
    return base


def test_correct_answer_requires_value_period_unit_and_citation():
    documents = {"A-1": _document(CONSOLIDATED, accession="A-1")}
    result = semantics.score(_question(), _gold(), _answer(), documents)
    assert result["status"] == "correct"
    assert result["citation_ok"] and result["header_confirmed"]


def test_wrong_period_is_a_false_answer():
    documents = {"A-1": _document(CONSOLIDATED, accession="A-1")}
    response = _answer(period="2021")
    response["citations"][0]["period"] = "2021"
    result = semantics.score(_question(), _gold(), response, documents)
    assert result["status"] == "false_answer"
    assert result["period_ok"] is False


def test_mislabelled_column_is_not_a_confirmed_period():
    documents = {"A-1": _document(CONSOLIDATED, accession="A-1")}
    response = _answer()
    response["citations"][0]["column_label"] = "2021"
    result = semantics.score(_question(), _gold(), response, documents)
    assert result["status"] == "correct"
    assert result["header_confirmed"] is False


def test_abstaining_on_printed_evidence_is_a_resolution_failure():
    documents = {"A-1": _document(CONSOLIDATED, accession="A-1")}
    response = {"runner": "baseline", "outcome": "abstained", "reason": "metric_not_found",
                "elapsed_ms": 1.0}
    result = semantics.score(_question(), _gold(), response, documents)
    assert result["status"] == "resolution_failure"


def test_abstaining_when_nothing_is_printed_is_evidence_missing():
    without_row = CONSOLIDATED.replace("<tr><td>Net sales</td><td>32,765</td><td>31,657</td></tr>",
                                       "")
    documents = {"A-1": _document(without_row, accession="A-1")}
    response = {"runner": "baseline", "outcome": "abstained", "reason": "no_candidate_row",
                "elapsed_ms": 1.0}
    result = semantics.score(_question(), _gold(), response, documents)
    assert result["status"] == "evidence_missing"


def test_conflict_abstention_is_justified_but_an_answer_is_not():
    question = _question(gold_class="conflicting_evidence",
                         expect={"outcome": "abstained", "note": "two vintages"})
    documents = {"A-1": _document(CONSOLIDATED, accession="A-1")}
    justified = semantics.score(question, {"class": "conflicting_evidence", "inputs": []},
                                {"runner": "geometry", "outcome": "abstained",
                                 "reason": "geometry:ambiguous:conflicting_row_values"},
                                documents)
    assert justified["status"] == "justified_abstention"
    answered = semantics.score(question, {"class": "conflicting_evidence", "inputs": []},
                               _answer(), documents)
    assert answered["status"] == "unsupported_confident_answer"


def test_answering_a_structurally_unanswerable_question_is_unsupported():
    question = _question(gold_class="structurally_unanswerable", concept="gross_profit",
                         expect={"outcome": "abstained", "note": "no such line"})
    documents = {"A-1": _document(CONSOLIDATED, accession="A-1")}
    answered = semantics.score(question, {"class": "structurally_unanswerable", "inputs": []},
                               _answer(), documents)
    assert answered["status"] == "unsupported_confident_answer"


# --------------------------------------------------------------------------- answer path
def test_decimal_printed_value_produces_an_exact_economic_amount():
    """A printed \"2,368.4\" million must scale to 2,368,400,000, not crash the answer path."""
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES ('ISS-T','0000000031','Fixture',"
        "'company',1,'test',?,?)", (now, now))
    html = """<html><body><p>CONSOLIDATED STATEMENTS OF INCOME</p><p>(In millions)</p>
    <table><tr><td></td><td>2018</td></tr>
    <tr><td>Net income</td><td>2,368.4</td></tr>
    <tr><td>Cost of sales</td><td>16,682</td></tr></table></body></html>"""
    engine = KnowledgeEngine(database)
    engine.ingest_document(
        issuer_id="ISS-T", accession="A-1", form_type="10-K", html=html,
        filed_date="2019-01-01", acceptance_time="2019-01-01T12:00:00Z",
        period_of_report="2018-10-28", rights="public_domain",
        primary_document_url="https://www.sec.gov/Archives/A-1.htm")
    answers = FinancialAnswerEngine(engine)
    cells = [cell for cell in answers.cells("ISS-T", None)
             if cell.row_label == "Net income" and cell.status == "verified"]
    assert cells, "the decimal cell was not verified"
    binding = type("B", (), {})()
    for field in ("document_id", "accession", "table_id", "unit_id", "row", "column",
                  "row_label", "column_label", "period", "currency", "scale", "value", "raw",
                  "statement_title", "statement_family", "entity_scope",
                  "availability_time", "availability_precision", "rights"):
        setattr(binding, field, getattr(cells[0], field))
    binding.issuer_id = "ISS-T"
    binding.source_table_sha256 = cells[0].source_sha256
    packet = answers.lookup_bound(binding, "2024-01-01T00:00:00Z")
    assert packet["outcome"] == "answered", packet.get("reason")
    assert Decimal(packet["economic_amount"]) == Decimal("2368400000")


def test_committed_fixtures_are_small_and_not_filing_bodies():
    for name in ("corpus.json", "questions.json", "xbrl_facts.json"):
        path = FIXTURES / name
        assert path.exists(), name
        assert path.stat().st_size < 2_000_000, f"{name} is too large to be metadata"
    payload = json.loads((FIXTURES / "corpus.json").read_text())
    assert all("<html" not in json.dumps(filing).lower() for filing in payload["filings"])
    assert all("<table" not in json.dumps(filing).lower() for filing in payload["filings"])
