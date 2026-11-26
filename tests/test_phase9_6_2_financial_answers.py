"""Phase 9.6.2: verified table cells and the bounded financial-answer compiler.

Every expected number below is computed by hand from the fixture table, not copied from the
implementation's output.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.knowledge import KnowledgeEngine
from atlas.research.table_cells import detect_scale, extract_cells, parse_number
from atlas.storage.db import Database

ISSUER = "ISS-T-F"
ACCESSION = "0000000020-24-000001"
DOC = """<html><body>
<h1>Item 8. Financial Statements</h1>
<p>Consolidated results of operations (in millions):</p>
<table>
<caption>Consolidated results of operations (in millions)</caption>
<tr><td></td><td>2020</td><td>2019</td></tr>
<tr><td>Revenue</td><td>1,234</td><td>1,100</td></tr>
<tr><td>Cost of revenue</td><td>(234)</td><td>(200)</td></tr>
<tr><td>Gross profit</td><td>1,000</td><td>900</td></tr>
<tr><td>Net income</td><td>100</td><td>-50</td></tr>
<tr><td>Total assets</td><td>2,500</td><td>2,000</td></tr>
<tr><td>Shares outstanding</td><td>-</td><td>10</td></tr>
</table>
</body></html>"""


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
        (ISSUER, "0000000020", "Financial Fixture Corp", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=DOC,
        filed_date="2021-02-10", acceptance_time="2021-02-10T12:00:00Z",
        period_of_report="2020-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{ACCESSION}.htm")
    return database


def test_units_are_detected_and_conflicts_refused():
    assert detect_scale("in millions")[0] == 6
    assert detect_scale("(in thousands)")[2] == "detected"
    assert detect_scale("in millions", "thousands")[2] == "conflicting_units"


def test_numeric_parsing_variants():
    assert parse_number("1,234")[0] == Decimal("1234")
    assert parse_number("(234)")[0] == Decimal("-234")
    assert parse_number("(234)")[1] == "parentheses_negative"
    assert parse_number("-50")[0] == Decimal("-50")
    assert parse_number("12.5%")[0] == Decimal("12.5")
    # A dash is not zero and must not be inferred as one.
    assert parse_number("-")[0] is None
    assert parse_number("-")[2] == "dash_not_zero"
    assert parse_number("")[2] == "empty_cell"


def test_cells_preserve_provenance_and_sign(db: Database):
    engine = KnowledgeEngine(db)
    table = dict(engine.tables(document_id=db.query_one(
        "SELECT document_id FROM knowledge_document")["document_id"], limit=5)[0])
    document = engine.document(table["document_id"])
    cells = extract_cells({**table, "rows": table["rows"]}, document=document)
    verified = {(cell.row_label, cell.period): cell
                for cell in cells if cell.status == "verified"}
    revenue = verified[("Revenue", "2020")]
    assert revenue.value == "1234"
    assert revenue.scale == 6
    assert verified[("Revenue", "2019")].value == "1100"
    assert verified[("Cost of revenue", "2020")].value == "-234"
    assert verified[("Cost of revenue", "2020")].sign_convention == "parentheses_negative"
    assert revenue.cell_id.startswith("CELL-")
    assert revenue.source_sha256 == table["sha256"]
    dash = next(cell for cell in cells if cell.row_label == "Shares outstanding")
    assert dash.status == "unresolved" and dash.reason == "dash_not_zero"


def test_lookup_returns_a_quoted_cell_not_a_computation(db: Database):
    answer = FinancialAnswerEngine(KnowledgeEngine(db)).lookup(
        ISSUER, "2021-12-31T00:00:00Z", metric="revenue", period="2020")
    assert answer["outcome"] == "answered"
    assert answer["answer_type"] == "reported_value"
    assert answer["value"] == "1234.00"
    assert answer["verification"]["independent_recomputation"] is True
    assert answer["inputs"][0]["row_label"] == "Revenue"
    assert answer["inputs"][0]["unit_sha256"]


def test_percentage_change_matches_hand_calculation(db: Database):
    # (1234 - 1100) / 1100 * 100 = 12.181818... -> 12.18
    answer = FinancialAnswerEngine(KnowledgeEngine(db)).percentage_change(
        ISSUER, "2021-12-31T00:00:00Z", metric="revenue",
        current_period="2020", prior_period="2019")
    assert answer["outcome"] == "answered"
    assert answer["value"] == "12.18"
    assert answer["formula"] == "(current - prior) / prior * 100"
    assert len(answer["inputs"]) == 2


def test_margin_and_ratio_use_same_units(db: Database):
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    margin = engine.margin(ISSUER, "2021-12-31T00:00:00Z", numerator="gross profit",
                           revenue="revenue", period="2020")
    assert margin["value"] == "81.04"  # 1000 / 1234 * 100
    ratio = engine.ratio(ISSUER, "2021-12-31T00:00:00Z", numerator="total assets",
                         denominator="revenue", period="2020")
    assert ratio["value"] == "2.0259"  # 2500 / 1234 at typed ratio precision (4 dp)
    assert ratio["display_places"] == 4
    assert ratio["unit"]["kind"] == "ratio"


def test_missing_inputs_abstain_instead_of_guessing(db: Database):
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    missing = engine.lookup(ISSUER, "2021-12-31T00:00:00Z", metric="ebitda", period="2020")
    assert missing["outcome"] == "abstained" and missing["reason"] == "metric_not_found"
    dash = engine.lookup(ISSUER, "2021-12-31T00:00:00Z", metric="shares outstanding", period="2020")
    assert dash["outcome"] == "abstained"
    wrong_period = engine.percentage_change(
        ISSUER, "2021-12-31T00:00:00Z", metric="revenue",
        current_period="2020", prior_period="2018")
    assert wrong_period["outcome"] == "abstained" and wrong_period["reason"] == "missing_input"


def test_future_evidence_cannot_produce_an_answer(db: Database):
    # The filing became available 2021-02-10; a 2020 cutoff must find nothing.
    answer = FinancialAnswerEngine(KnowledgeEngine(db)).lookup(
        ISSUER, "2020-06-30T00:00:00Z", metric="revenue", period="2020")
    assert answer["outcome"] == "abstained"


def test_computed_value_is_labelled_and_fingerprinted(db: Database):
    answer = FinancialAnswerEngine(KnowledgeEngine(db)).percentage_change(
        ISSUER, "2021-12-31T00:00:00Z", metric="revenue",
        current_period="2020", prior_period="2019")
    assert answer["answer_type"] == "percentage_change"
    assert "never presented as quoted" in " ".join(answer["limitations"])
    again = FinancialAnswerEngine(KnowledgeEngine(db)).percentage_change(
        ISSUER, "2021-12-31T00:00:00Z", metric="revenue",
        current_period="2020", prior_period="2019")
    assert again["reproducibility_fingerprint"] == answer["reproducibility_fingerprint"]


def _table(rows, caption="", units=None, sha="deadbeef"):
    return {"table_id": "TAB-1", "unit_id": "U-1", "section_path": "Item 8",
            "caption": caption, "units": units, "rows": rows, "footnotes": [], "sha256": sha}


_DOC = {"document_id": "DOC-1", "accession": "0000000020-24-000001",
        "availability_time": "2021-02-10T00:00:00Z", "availability_precision": "observed",
        "rights": "public_domain"}


def test_multilevel_headers_combine_period_and_amount():
    cells = extract_cells(_table([["", "2020", "2019"], ["", "Amount", "Amount"],
                                  ["Revenue", "1,000", "900"]], "in thousands"), document=_DOC)
    revenue = [cell for cell in cells if cell.row_label == "Revenue"]
    assert [(cell.period, cell.value, cell.scale) for cell in revenue] == [
        ("2020", "1000", 3), ("2019", "900", 3)]


def test_merged_period_header_is_unresolved():
    cells = extract_cells(_table([["", "2020 2019"], ["Revenue", "1,000"]]), document=_DOC)
    assert cells[0].status == "unresolved"
    assert cells[0].reason == "merged_period_header"


def test_duplicate_labels_without_period_are_unresolved():
    cells = extract_cells(_table([["", "Amount"], ["Revenue", "1,000"],
                                  ["Revenue", "900"]], units="in millions"), document=_DOC)
    assert all(cell.status == "unresolved" for cell in cells)
    assert {cell.reason for cell in cells} == {"duplicate_row_label"}


def test_conflicting_units_are_unresolved():
    cells = extract_cells(_table([["", "2020"], ["Revenue", "1,000"]],
                                 caption="in millions", units="thousands"), document=_DOC)
    assert cells[0].reason == "conflicting_units"


def test_missing_scale_is_unresolved_not_ones():
    cells = extract_cells(_table([["", "2020"], ["Revenue", "1,000"]]), document=_DOC)
    assert cells[0].status == "unresolved"
    assert cells[0].reason == "scale_undetected"
    assert cells[0].scale is None


def test_corrupted_values_are_not_guessed_but_footnotes_are_preserved():
    cells = extract_cells(_table([["", "2020"], ["Revenue", "1,2x4"],
                                  ["Other", "1,234 (a)"]], units="in millions"), document=_DOC)
    assert cells[0].status == "unresolved" and cells[0].reason == "unparseable"
    assert cells[1].status == "verified"
    assert cells[1].value == "1234"
    assert cells[1].scale == 6
    assert cells[1].footnotes == ["a"]
