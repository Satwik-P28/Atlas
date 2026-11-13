# Phase 9.6.2 — Verified table-cell contract

Version: `9.6.2`. Module: `src/atlas/research/table_cells.py`. Tests:
`tests/test_phase9_6_2_financial_answers.py`.

## What a cell is

A `Cell` is derived from one stored `knowledge_table` row. It carries the document id and
accession, table id, unit id, section path, row/column coordinates, row and column headings,
period, currency, unit, scale, sign convention, raw text, parsed value, footnotes, the source
table hash, extraction method/confidence, availability time/precision and rights. `cell_id` is a
hash of `table_id:row:column:raw`, so two cells with different provenance cannot collide.

## Verified versus unresolved

A cell is `verified` only when all of these hold:

1. exactly one unit interpretation exists across caption and units (`in millions`, `(in thousands)`),
2. the column header resolves to exactly one period, or the column is period-free,
3. the raw text parses to one number with an unambiguous sign,
4. the row label is unique, or its period column disambiguates it.

Anything else is `unresolved` with a reason: `dash_not_zero`, `empty_cell`, `unparseable`,
`merged_period_header`, `duplicate_row_label`, `missing_row_label`, `conflicting_units`,
`conflicting_currencies`.

## Deliberate refusals

* A dash is never zero. Filings use dashes for nil, not-applicable and not-disclosed.
* A missing cell is never zero.
* Adjacent columns are never merged into one period; two periods in one header leave the cell
  unresolved.
* A trailing footnote marker (`(a)`, `(1)`, `*`, `†`) is stripped for parsing but recorded in
  `footnotes`; the value is still traceable to the raw text.
* When the stored extractor drops an empty row-label header cell, the header is realigned only
  if it is short by a leading label; other shape mismatches stay unresolved.

## Source coverage (diagnostic)

Across the first seven target filings of the evaluation sample: 4,255 cells, 2,264 verified
(53.2%). Unresolved reasons: unparseable 1,114, duplicate label 416, dash 372, merged period 89.
The unparseable share is dominated by prose and partially split values, not by footnotes.

## Parser repair

`KnowledgeEngine` dropped `<caption>` inside a table because the in-table branch returned before
the caption handler, losing the unit scale. `src/atlas/research/knowledge.py` now records it, and
`tables()` exposes the table `sha256` used by cells for provenance.
