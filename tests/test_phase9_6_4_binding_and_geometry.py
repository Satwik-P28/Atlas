"""Phase 9.6.4: evidence binding, statement identity, and table geometry regressions."""

from __future__ import annotations

import dataclasses

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver, bind
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

ISSUER = "ISS-T-964"
ACCESSION = "0000000031-24-000001"


def _db(html: str, *, accession: str = ACCESSION, period: str = "2022-12-31",
        filed: str = "2023-02-10", accepted: str = "2023-02-10T12:00:00Z",
        issuer: str = ISSUER) -> Database:
    database = Database(":memory:")
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (issuer, "0000000031", f"Fixture {issuer}", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=issuer, accession=accession, form_type="10-K", html=html,
        filed_date=filed, acceptance_time=accepted, period_of_report=period,
        rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{accession}.htm")
    return database


CONSOLIDATED = """<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p>
<table>
<tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table></body></html>"""

SEGMENT = """<html><body>
<p>Item 8. Financial Statements</p>
<p>Note 4. Segment information</p>
<table>
<tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>11,604</td><td>12,000</td></tr>
<tr><td>Cost of sales</td><td>7,000</td><td>7,100</td></tr>
</table></body></html>"""


def test_segment_table_cannot_supply_consolidated_revenue():
    db = _db(CONSOLIDATED + SEGMENT)
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        ISSUER, "revenue", "2022", "2024-01-01T00:00:00Z")
    assert resolution.status == "resolved"
    assert resolution.cell.value == "34229"
    assert resolution.cell.statement_family == "income"
    assert resolution.cell.entity_scope == "consolidated"


def test_same_label_in_two_families_keeps_statement_identity():
    db = _db(CONSOLIDATED + SEGMENT)
    cells = FinancialAnswerEngine(KnowledgeEngine(db)).cells(ISSUER, "2024-01-01T00:00:00Z")
    families = {cell.statement_family for cell in cells if cell.row_label == "Net sales"}
    assert "income" in families
    assert "unknown" in families or "segment" in families


def test_row_with_two_values_in_three_period_table_leaves_period_unresolved():
    html = """<html><body><p>Item 8</p><p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p><table>
<tr><td></td><td>2022</td><td>2021</td><td>2020</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
</table></body></html>"""
    db = _db(html)
    cells = [c for c in FinancialAnswerEngine(KnowledgeEngine(db)).cells(
        ISSUER, "2024-01-01T00:00:00Z") if c.row_label == "Net sales"]
    assert not any(c.value == "34229" and c.period == "2022" for c in cells), \
        "a two-value row in a three-period table must not guess the newest period"


def test_currency_columns_present_on_some_rows_do_not_shift_periods():
    html = """<html><body><p>Item 8</p><p>CONSOLIDATED BALANCE SHEETS</p>
<p>(In millions)</p><table>
<tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Total assets</td><td>$</td><td>92,763</td><td></td><td>$</td><td>94,354</td></tr>
<tr><td>Total liabilities</td><td>65,000</td><td></td><td>69,000</td><td></td></tr>
</table></body></html>"""
    db = _db(html)
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    assets = {c.period: c.value for c in engine.cells(ISSUER, "2024-01-01T00:00:00Z")
              if c.row_label == "Total assets"}
    assert assets.get("2022") == "92763"
    assert assets.get("2021") == "94354"


def test_identical_value_across_vintages_is_one_fact_not_a_conflict():
    original = """<html><body><p>Item 8</p><p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p><table><tr><td></td><td>2021</td></tr>
<tr><td>Net sales</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,500</td></tr></table></body></html>"""
    comparative = """<html><body><p>Item 8</p><p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>(In millions)</p><table><tr><td></td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr></table></body></html>"""
    db = _db(original, period="2021-12-31", filed="2022-02-10")
    KnowledgeEngine(db).ingest_document(
        issuer_id=ISSUER, accession="0000000031-24-000002", form_type="10-K",
        html=comparative, filed_date="2023-02-10",
        acceptance_time="2023-02-10T12:00:00Z", period_of_report="2022-12-31",
        rights="public_domain",
        primary_document_url="https://www.sec.gov/Archives/0000000031-24-000002.htm")
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        ISSUER, "revenue", "2021", "2024-01-01T00:00:00Z")
    assert resolution.status == "resolved"
    assert resolution.cell.value == "35355"


def test_binding_survives_to_fec_and_revalidates():
    db = _db(CONSOLIDATED)
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        ISSUER, "revenue", "2022", "2024-01-01T00:00:00Z")
    binding = bind(resolution, ISSUER, "revenue")
    assert binding is not None
    answer = engine.lookup_bound(binding, "2024-01-01T00:00:00Z")
    assert answer["outcome"] == "answered"
    assert answer["value"] == "34229.00"
    assert answer["inputs"][0]["table_id"] == binding.table_id
    assert answer["inputs"][0]["cell_id"] == binding.cell_id


@pytest.mark.parametrize("change,problem", [
    ({"value": "99999", "raw": "99,999"}, "cell_not_in_source"),
    ({"source_table_sha256": "0" * 64}, "table_hash_mismatch"),
    ({"period": "2019"}, "period_mismatch"),
    ({"issuer_id": "ISS-OTHER"}, "issuer_mismatch"),
    ({"table_id": "TAB-0000000000000000"}, "table_missing"),
])
def test_tampered_binding_is_refused(change, problem):
    db = _db(CONSOLIDATED)
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        ISSUER, "revenue", "2022", "2024-01-01T00:00:00Z")
    binding = dataclasses.replace(bind(resolution, ISSUER, "revenue"), **change)
    answer = engine.lookup_bound(binding, "2024-01-01T00:00:00Z")
    assert answer["outcome"] == "abstained"
    assert answer["reason"] == "input_unverified"
    assert problem in answer["context"]["problems"]


def test_future_cutoff_binding_is_refused():
    db = _db(CONSOLIDATED)
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    resolution = ConceptResolver(KnowledgeEngine(db)).resolve(
        ISSUER, "revenue", "2022", "2024-01-01T00:00:00Z")
    binding = bind(resolution, ISSUER, "revenue")
    answer = engine.lookup_bound(binding, "2022-01-01T00:00:00Z")
    assert answer["outcome"] == "abstained"
    assert "future_evidence" in answer["context"]["problems"]
