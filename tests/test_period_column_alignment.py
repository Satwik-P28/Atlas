"""Regression tests for column-to-period mapping in flattened financial tables.

The documented defect: a real 10-K printed a 2026 amount under a header cell that read
"2025", because the filer puts `$` in its own column and prints a `Change` column between
periods. The flattened header row therefore sits to the left of the data columns it describes.

These tests build the misleading layouts directly, so the fix cannot be tuned to one issuer:
every expected number here is written by hand from the fixture rows.
"""

from __future__ import annotations

import pytest

from atlas.research.table_cells import extract_cells

_DOCUMENT = {"document_id": "DOC-ALIGN", "accession": "0000000026-26-000001",
             "sha256": "0" * 64}


def _table(rows, caption: str = "(In millions)"):
    return {"table_id": "TAB-ALIGN", "unit_id": "UNIT-ALIGN", "section_path": "",
            "rows": rows, "caption": caption, "units": "USD", "footnotes": [],
            "sha256": "1" * 64}


def _by_raw(cells):
    return {cell.raw: cell for cell in cells}


def test_change_columns_and_currency_separator_do_not_shift_the_cited_year():
    """Apple-style layout: header 2026|Change|2025|Change|2024 over values shifted right."""
    table = _table([
        ["", "2026", "", "Change", "", "2025", "", "Change", "", "2024"],
        ["Total net sales", "$", "478,834", "", "", "15", "%", "",
         "$", "416,161", "", "", "6", "%", "", "$", "391,035"],
    ])
    cells = _by_raw(extract_cells(table, document=_DOCUMENT))

    assert (cells["478,834"].period, cells["478,834"].column_label) == ("2026", "2026")
    assert (cells["416,161"].period, cells["416,161"].column_label) == ("2025", "2025")
    assert (cells["391,035"].period, cells["391,035"].column_label) == ("2024", "2024")
    # A comparison column is a real number with no period of its own.
    assert cells["15"].period is None
    assert cells["15"].column_label == "Change"


def test_currency_column_shift_with_a_short_header_still_names_the_right_year():
    """The header prints one cell per period; the values sit one column further right."""
    table = _table([
        ["", "2026", "2025"],
        ["Revenue", "$", "1,000", "", "", "$", "900"],
    ])
    cells = _by_raw(extract_cells(table, document=_DOCUMENT))

    assert (cells["1,000"].period, cells["1,000"].column_label) == ("2026", "2026")
    assert (cells["900"].period, cells["900"].column_label) == ("2025", "2025")
    assert cells["1,000"].geometry == "slot_sequence"


def test_multi_level_header_uses_the_row_that_names_the_periods():
    table = _table([
        ["Years Ended"],
        ["September 26, 2026", "", "September 27, 2025", "", "September 28, 2024"],
        ["Net sales:", "", "", "", ""],
        ["Products", "$", "355,533", "", "", "$", "307,003", "", "", "$", "294,866"],
    ], caption=None)
    cells = _by_raw(extract_cells(table, document=_DOCUMENT))

    assert cells["355,533"].period == "2026"
    assert cells["355,533"].column_label == "September 26, 2026"
    assert cells["307,003"].period == "2025"
    assert cells["294,866"].period == "2024"


def test_header_that_cannot_cover_the_values_is_refused_not_guessed():
    """Two header labels over three values: the header cell above a value cannot be shown
    to govern it, so the value is unresolved with a typed reason instead of taking that year."""
    table = _table([
        ["", "2026", "", "2025"],
        ["Revenue", "1,000", "500", "300"],
    ])
    cells = extract_cells(table, document=_DOCUMENT)
    by_raw = _by_raw(cells)

    assert by_raw["1,000"].status == "unresolved"
    assert by_raw["1,000"].reason == "period_column_ambiguous"
    assert by_raw["1,000"].value is None
    # No cell in this table may claim a period it cannot support.
    assert not any(cell.period in {"2026", "2025"} and cell.status == "verified"
                   for cell in cells)


def test_placeholders_and_symbols_are_not_assigned_a_year():
    table = _table([
        ["", "2026", "", "2025"],
        ["Revenue", "$", "1,000", "", "$", "900"],
        ["Nil line", "$", "-", "", "$", "-"],
    ])
    cells = _by_raw(extract_cells(table, document=_DOCUMENT))

    assert cells["-"].status == "unresolved"
    assert cells["-"].reason == "dash_not_zero"


def test_printed_label_is_reconstructable_from_the_archived_header():
    """The label reported for a cell must be a string the document actually prints."""
    printed = {"September 26, 2026", "September 27, 2025"}
    table = _table([
        ["Years Ended", "", "", ""],
        ["September 26, 2026", "", "September 27, 2025"],
        ["Revenue", "1,000", "", "", "900"],
    ], caption="(In millions)")
    cells = extract_cells(table, document=_DOCUMENT)
    verified = [cell for cell in cells if cell.status == "verified"]
    assert len(verified) == 2
    for cell in verified:
        assert cell.column_label in printed
        assert cell.period in cell.column_label


def test_citation_gate_refuses_a_label_that_contradicts_the_period():
    pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")
    from fastapi import HTTPException

    from atlas.terminal.answers_api import citation_period_gate

    assert citation_period_gate("2026", "2026") == (True, "exact")
    assert citation_period_gate("September 26, 2026", "2026") == (True, "exact")
    with pytest.raises(HTTPException) as raised:
        citation_period_gate("2025", "2026")
    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "citation_period_conflict"
    assert raised.value.detail["context"] == {"column_label": "2025", "period": "2026"}
