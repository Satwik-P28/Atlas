"""Phase 10I: source-scope, concept semantics and fail-closed arithmetic.

These tests are adversarial by design. Each one encodes a way the resolver used to produce a
confident wrong answer (or a silent definitional substitution), so the behaviour cannot regress
without a fixture failing.
"""

from __future__ import annotations

from atlas.research.financial_concepts import (
    CONCEPTS,
    _label_score,
    component_sum_supports_total,
    label_equals_alias,
)
from atlas.research.geometry_resolution import GeometryDocument, GeometryResolver
from atlas.research.statement_scope import classify, group_scope
from atlas.research.table_cells import Cell
from atlas.research.financial_answers import FinancialAnswerEngine

MILLIONS = "<p>(In millions)</p>"


def _document(*sections: str, accession: str = "0000000001-23-000001") -> GeometryDocument:
    html = "<html><body>" + "".join(sections) + "</body></html>"
    return GeometryDocument.from_html(html, accession=accession)


def _table(*rows: str) -> str:
    return "<table>" + "".join(rows) + "</table>"


HEADER = "<tr><td></td><td>2022</td><td>2021</td></tr>"


# ---------------------------------------------------------------- statement identity
def test_note_that_names_a_statement_is_not_the_statement() -> None:
    found = classify("Amounts Offset in the Consolidated Balance Sheets")
    assert found.family == "note"


def test_plural_financial_position_is_a_balance_sheet() -> None:
    found = classify("Consolidated Statements of Financial Position")
    assert (found.family, found.scope) == ("balance_sheet", "consolidated")


def test_section_heading_is_not_a_statement_title() -> None:
    assert classify("Item 8. Financial Statements and Supplementary Data").family == "unknown"


def test_segment_disclosure_has_segment_identity() -> None:
    found = classify("Note 15 — Segment and Geographic Area Information")
    assert (found.family, found.scope) == ("segment", "segment")


def test_banner_pair_is_not_a_column_group() -> None:
    assert group_scope("STATEMENT 1") == "unknown"
    assert group_scope("Caterpillar Inc.") == "unknown"
    assert group_scope("Consolidated") == "consolidated"
    assert group_scope("Consolidating Adjustments") == "adjustment"


# ---------------------------------------------------------------- concept semantics
def test_substring_revenue_labels_are_rejected() -> None:
    for label in ("Sales and marketing",
                  "Sales and marketing (1)",
                  "Net (purchases), sales and maturities of marketable securities",
                  "Finance lease revenue",
                  "Operating lease revenue",
                  "Differences in timing of revenue recognition"):
        assert _label_score(label, "sales") == 0.0, label
        assert _label_score(label, "revenue") == 0.0, label


def test_total_current_assets_cannot_satisfy_total_assets() -> None:
    assert _label_score("Total current assets", "total assets") == 0.0
    assert _label_score("Total assets", "total assets") >= 2.0
    assert _label_score("Total Assets", "total assets") >= 2.0


def test_plural_and_footnote_markers_do_not_change_the_concept() -> None:
    assert _label_score("Total revenues", "total revenue") >= 2.0
    assert _label_score("Revenues", "revenue") >= 2.0
    assert label_equals_alias("Total assets(a)", "total assets")
    assert label_equals_alias("Total assets (a)", "total assets")


def test_net_income_and_attributable_income_are_distinct_concepts() -> None:
    assert _label_score("Net income (loss)", "net income") >= 2.0
    assert _label_score("Net income (loss) attributable to Parent", "net income") == 0.0
    assert _label_score("Net income attributable to Parent",
                        "net income attributable to") >= 2.0


def test_total_is_preferred_only_when_components_add_up() -> None:
    assert component_sum_supports_total(["242901", "271082"], ["513983"]) is True
    assert component_sum_supports_total(["1234"], ["1250"]) is False


# ---------------------------------------------------------------- geometry and scope
def test_same_row_in_a_note_cannot_beat_the_consolidated_statement() -> None:
    note = ("<p>Amounts Offset in the Consolidated Balance Sheets</p>" + MILLIONS
            + _table(HEADER, "<tr><td>Total assets</td><td>2,932</td><td>2,500</td></tr>"))
    statement = ("<p>The Boeing Company and Subsidiaries</p>"
                 "<p>Consolidated Statements of Financial Position</p>"
                 "<p>(Dollars in millions)</p>"
                 + _table(HEADER,
                          "<tr><td>Total assets</td><td>182,103</td><td>168,406</td></tr>",
                          "<tr><td>Total liabilities</td><td>100,000</td><td>90,000</td></tr>",
                          "<tr><td>Total equity</td><td>82,103</td><td>78,406</td></tr>"))
    resolution = GeometryResolver([_document(note, statement)]).resolve("total_assets", "2022")
    assert resolution.status == "resolved"
    assert resolution.cell is not None and resolution.cell.value == "182103"


def test_consolidating_schedule_uses_only_the_consolidated_column_group() -> None:
    table = _table(
        '<tr><td></td><td colspan="2">Consolidated</td>'
        '<td colspan="2">Consolidating Adjustments</td></tr>',
        "<tr><td></td><td>2022</td><td>2021</td><td>2022</td><td>2021</td></tr>",
        "<tr><td>Total assets</td><td>81,943</td><td>82,793</td><td>(2,267)</td><td>(2,200)</td></tr>")
    html = ("<p>Supplemental Consolidating Data</p>" + MILLIONS + table)
    resolution = GeometryResolver([_document(html)]).resolve("total_assets", "2022")
    assert resolution.status == "resolved"
    assert resolution.cell is not None and resolution.cell.value == "81943"


def test_scope_incompatible_statement_is_refused_with_a_reason() -> None:
    parent = ("<p>Parent Company Only Balance Sheet</p>" + MILLIONS
              + _table(HEADER, "<tr><td>Total assets</td><td>88,331</td><td>80,000</td></tr>"))
    resolution = GeometryResolver([_document(parent)]).resolve("total_assets", "2022")
    assert resolution.status in {"scope_mismatch", "statement_scope_unresolved"}
    assert resolution.cell is None


def test_note_only_evidence_is_accepted_only_when_every_note_agrees() -> None:
    agreed = ("<p>Segment and Geographic Area Information</p>" + MILLIONS
              + _table(HEADER,
                       "<tr><td>Total assets</td><td>74,438</td><td>73,000</td></tr>",
                                                  "<tr><td>Total liabilities</td><td>40,000</td><td>39,000</td></tr>",
                           "<tr><td>Total equity</td><td>34,438</td><td>34,000</td></tr>"))
    resolution = GeometryResolver([_document(agreed)]).resolve("total_assets", "2022")
    assert resolution.status == "resolved"
    assert resolution.cell is not None and resolution.cell.value == "74438"

    conflicting = ("<p>Fair value of assets measured on a recurring basis</p>" + MILLIONS
                   + _table(HEADER,
                            "<tr><td>Total assets</td><td>243</td><td>200</td></tr>",
                            "<tr><td>Total liabilities</td><td>100</td><td>90</td></tr>"))
    second = ("<p>Reconciliation of total assets</p>" + MILLIONS
              + _table(HEADER,
                       "<tr><td>Total assets</td><td>325</td><td>300</td></tr>",
                       "<tr><td>Total liabilities</td><td>120</td><td>110</td></tr>"))
    resolution = GeometryResolver([_document(conflicting, second)]).resolve("total_assets", "2022")
    assert resolution.status == "ambiguous"
    assert resolution.reason == "conflicting_note_values"


def test_consolidated_and_attributable_net_income_is_a_definitional_ambiguity() -> None:
    html = ("<p>Consolidated Statements of Operations</p>" + MILLIONS
            + _table(HEADER,
                     "<tr><td>Total revenues</td><td>82,722</td><td>67,418</td></tr>",
                     "<tr><td>Net income (loss)</td><td>3,505</td><td>1,995</td></tr>",
                     "<tr><td>Net income (loss) attributable to Parent</td>"
                     "<td>3,145</td><td>1,800</td></tr>"))
    resolution = GeometryResolver([_document(html)]).resolve("net_income", "2022")
    assert resolution.status == "ambiguous"
    assert resolution.reason == "definitional_ambiguity"


def test_parenthesised_loss_is_a_negative_value_not_a_missing_cell() -> None:
    html = ("<p>Consolidated Statements of Operations</p>" + MILLIONS
            + _table(HEADER,
                     "<tr><td>Total revenues</td><td>66,608</td><td>62,286</td></tr>",
                     "<tr><td>Net income (loss)</td><td>(5,053)</td><td>(4,202)</td></tr>"))
    resolution = GeometryResolver([_document(html)]).resolve("net_income", "2022")
    assert resolution.status == "resolved"
    assert resolution.cell is not None and resolution.cell.value == "-5053"


# ---------------------------------------------------------------- fail-closed arithmetic
def _cell(**overrides) -> Cell:
    base = dict(document_id="DOC-1", accession="A-1", table_id="T-1", unit_id="U-1",
                section_path="", table_caption=None, row=1, column=2, row_label="Revenue",
                column_label="2022", period="2022", currency="USD", unit="USD", scale=6,
                sign_convention="plain", raw="100", value="100", statement_family="income",
                entity_scope="consolidated", source_sha256="s")
    base.update(overrides)
    return Cell(**base)


def test_arithmetic_refuses_mixed_accessions() -> None:
    engine = FinancialAnswerEngine.__new__(FinancialAnswerEngine)
    problem = engine._require([_cell()], [_cell(accession="A-2", period="2021")], "2022", "2021")
    assert problem is not None and problem["reason"] == "incompatible_operands"
    assert problem["context"]["detail"] == "mixed_source_accession"


def test_arithmetic_refuses_a_segment_operand() -> None:
    engine = FinancialAnswerEngine.__new__(FinancialAnswerEngine)
    problem = engine._require([_cell(entity_scope="segment")],
                              [_cell(period="2021")], "2022", "2021")
    assert problem is not None and problem["reason"] == "scope_mismatch"


def test_arithmetic_refuses_a_missing_period() -> None:
    engine = FinancialAnswerEngine.__new__(FinancialAnswerEngine)
    problem = engine._require([_cell(period=None)], [_cell(period="2021")], "2022", "2021")
    assert problem is not None and problem["reason"] == "period_mismatch"


def test_answer_contract_names_the_evidence_and_the_verification_stages() -> None:
    cell = _cell(value="1234", raw="1,234")
    engine = FinancialAnswerEngine.__new__(FinancialAnswerEngine)
    engine.engine = None
    engine.db = None
    engine.validate_binding = lambda binding, cutoff: []  # type: ignore[method-assign]
    engine.cell_from_binding = lambda binding: cell  # type: ignore[method-assign]
    packet = engine.lookup_bound(_cell(), "2023-01-01T00:00:00Z")
    assert packet["outcome"] == "answered"
    evidence = packet["evidence"]
    for key in ("requested_concept", "displayed_value", "period", "accession", "statement",
                "rows", "scale", "currency", "document_sha256", "verification_stages"):
        assert key in evidence or key in packet
    assert packet["verification_stages"]["final_validity"] == "verified_but_not_proven_correct"
    assert evidence["rows"][0]["printed_value"] == "1,234"
    assert CONCEPTS["total_assets"].statement == "balance"
