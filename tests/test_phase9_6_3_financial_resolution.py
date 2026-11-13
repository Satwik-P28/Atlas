"""Phase 9.6.3: FEC execution, independent verification and concept resolution."""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.fec.compiler import COMPILER_VERSION
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver
from atlas.research.financial_verification import (
    REFERENCE_VECTORS,
    VerificationError,
    evaluate,
    parse_raw,
    round_half_up,
)
from atlas.research.knowledge import KnowledgeEngine
from atlas.research.table_cells import Cell, extract_cells
from atlas.storage.db import Database

DOC_A = """<html><body><h1>Item 8. Financial Statements</h1>
<table><caption>Consolidated results (in millions)</caption>
<tr><td></td><td>2020</td><td>2019</td></tr>
<tr><td>Revenue</td><td>1,234</td><td>1,100</td></tr>
<tr><td>North America segment revenue</td><td>800</td><td>750</td></tr>
<tr><td>Net income</td><td>100</td><td>-50</td></tr>
<tr><td>Total assets</td><td>2,500</td><td>2,000</td></tr>
</table></body></html>"""

DOC_B = """<html><body><h1>Item 8. Financial Statements</h1>
<table><caption>Consolidated results (in millions)</caption>
<tr><td></td><td>2021</td><td>2020</td></tr>
<tr><td>Revenue</td><td>1,500</td><td>1,300</td></tr>
</table></body></html>"""

DOC_AMBIGUOUS = """<html><body><h1>Item 8</h1>
<table><caption>(in millions)</caption>
<tr><td></td><td>2020</td></tr>
<tr><td>Revenue</td><td>1,234</td></tr>
<tr><td>Total revenue</td><td>1,250</td></tr>
</table></body></html>"""


def _db(html: str, *, accession: str, period: str, filed: str, accepted: str,
        issuer: str = "ISS-T") -> Database:
    db = Database(":memory:")
    db.migrate()
    stamp = iso(utcnow())
    db.execute("INSERT INTO source (source_id, name, kind, redistribution, created_at) "
               "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (stamp,))
    db.execute("INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
               "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
               (issuer, "0000000099", "Fixture Corp", stamp, stamp))
    KnowledgeEngine(db).ingest_document(
        issuer_id=issuer, accession=accession, form_type="10-K", html=html, filed_date=filed,
        acceptance_time=accepted, period_of_report=period, rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{accession}.htm")
    return db


@pytest.fixture()
def single() -> Database:
    return _db(DOC_A, accession="0000000099-21-000001", period="2020-12-31",
               filed="2021-02-10", accepted="2021-02-10T12:00:00Z")


def test_reference_vectors_are_independent_of_production_code():
    for operator, raw_values, expected in REFERENCE_VECTORS:
        result = evaluate(operator, raw_values)
        if "." in expected:
            assert abs(float(result) - float(expected)) < 5e-9
        else:
            assert result == Decimal(expected)


def test_dashes_and_garbage_never_become_zero():
    for operator, raw_values in [("lookup", ["-"]), ("lookup", [""]), ("lookup", ["1,2x4"])]:
        with pytest.raises(VerificationError):
            evaluate(operator, raw_values)
    assert parse_raw("(234)") == -234
    assert round_half_up(evaluate("percentage_change", ["1,234", "1,100"])) == Decimal("12.18")


def test_answer_runs_the_fec_compiler_and_records_its_plan(single: Database):
    answer = FinancialAnswerEngine(KnowledgeEngine(single)).percentage_change(
        "ISS-T", "2021-12-31T00:00:00Z", metric="revenue",
        current_period="2020", prior_period="2019")
    assert answer["outcome"] == "answered"
    assert answer["value"] == "12.18"
    assert answer["operator_version"] == COMPILER_VERSION
    assert answer["fec"]["compiler_version"] == COMPILER_VERSION
    assert [node["op"] for node in answer["fec"]["plan"]["nodes"]] == ["sub", "div", "mul"]
    assert answer["fec"]["run_id"].startswith("RUN-")
    assert answer["fec"]["trace"], "FEC execution trace must be present"


def test_tampered_cell_value_is_refused_by_independent_verification(single: Database):
    engine = FinancialAnswerEngine(KnowledgeEngine(single))
    genuine = engine.cells("ISS-T", "2021-12-31T00:00:00Z")[0]
    tampered = Cell(**{**{field: getattr(genuine, field) for field in genuine.__slots__},
                       "raw": "1,000", "value": "1234"})
    engine.cells = lambda issuer_id, cutoff: [tampered]  # type: ignore[method-assign]
    answer = engine.lookup("ISS-T", "2021-12-31T00:00:00Z", metric="revenue", period="2020")
    assert answer["outcome"] == "abstained"
    assert answer["reason"] == "verification_disagreement"


def test_scale_mismatch_between_inputs_is_refused(single: Database):
    engine = FinancialAnswerEngine(KnowledgeEngine(single))
    cells = engine.cells("ISS-T", "2021-12-31T00:00:00Z")
    revenue = next(cell for cell in cells if cell.row_label == "Revenue" and cell.period == "2020")
    inflated = Cell(**{**{field: getattr(revenue, field) for field in revenue.__slots__},
                       "scale": 9})
    engine.cells = lambda issuer_id, cutoff: [revenue, inflated]  # type: ignore[method-assign]
    answer = engine.percentage_change("ISS-T", "2021-12-31T00:00:00Z", metric="revenue",
                                      current_period="2020", prior_period="2020")
    assert answer["outcome"] == "abstained"
    assert answer["reason"] in {"period_mismatch", "unit_mismatch", "metric_ambiguous"}


def test_concept_resolution_prefers_consolidated_revenue_over_segment(single: Database):
    resolution = ConceptResolver(KnowledgeEngine(single)).resolve(
        "ISS-T", "revenue", "2020", "2021-12-31T00:00:00Z")
    assert resolution.status == "resolved"
    assert resolution.cell is not None
    assert resolution.cell.value == "1234"
    assert resolution.vintage["accession"] == "0000000099-21-000001"
    payload = resolution.as_dict()
    assert payload["xbrl_status"].startswith("unavailable")


def test_conflicting_row_labels_are_ambiguous():
    db = _db(DOC_AMBIGUOUS, accession="0000000099-21-000002", period="2020-12-31",
             filed="2021-02-10", accepted="2021-02-10T12:00:00Z", issuer="ISS-AMB")
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        "ISS-AMB", "revenue", "2020", "2021-12-31T00:00:00Z")
    assert resolution.status == "ambiguous"
    assert resolution.reason == "conflicting_row_values"


def test_restated_comparative_is_a_vintage_conflict():
    db = _db(DOC_A, accession="0000000099-21-000003", period="2020-12-31",
             filed="2021-02-10", accepted="2021-02-10T12:00:00Z", issuer="ISS-V")
    KnowledgeEngine(db).ingest_document(
        issuer_id="ISS-V", accession="0000000099-22-000004", form_type="10-K", html=DOC_B,
        filed_date="2022-02-10", acceptance_time="2022-02-10T12:00:00Z",
        period_of_report="2021-12-31", rights="public_domain",
        primary_document_url="https://www.sec.gov/Archives/0000000099-22-000004.htm")
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        "ISS-V", "revenue", "2020", "2023-01-01T00:00:00Z")
    assert resolution.status == "vintage_conflict"
    assert resolution.vintage["document_id"]
    assert any(item["value"] == "1300" for item in resolution.candidates)


def test_future_cutoff_is_refused_before_resolution(single: Database):
    resolution = ConceptResolver(KnowledgeEngine(single)).resolve(
        "ISS-T", "revenue", "2020", "2020-06-30T00:00:00Z")
    assert resolution.status == "not_found"


def test_spacer_and_currency_columns_are_reconstructed():
    rows = [["Year Ended December 31,", "2022", "2021"],
            ["Net Operating Revenues", "$", "43,004", "", "$", "38,655"],
            ["Cost of goods sold", "$", "18,000", "", "$", "15,357"]]
    cells = extract_cells({"table_id": "TAB-G", "unit_id": "U-1", "section_path": "Item 8",
                           "caption": "(in millions)", "units": None, "rows": rows,
                           "footnotes": [], "sha256": "abc"},
                          document={"document_id": "DOC-G", "accession": "A-G",
                                    "availability_time": "2023-02-01T00:00:00Z",
                                    "availability_precision": "observed",
                                    "rights": "public_domain"})
    revenue = {cell.period: cell for cell in cells if cell.row_label == "Net Operating Revenues"}
    assert revenue["2022"].value == "43004" and revenue["2022"].scale == 6
    assert revenue["2021"].value == "38655"
    # Original source column indices are preserved, not renumbered.
    assert (revenue["2022"].column, revenue["2021"].column) == (2, 5)
