# Five-minute technical walkthrough

Audience: an engineer or analyst evaluating whether the evidence model is real.

## 1. The problem Atlas refuses to hide (0:00–1:00)

Financial figures are ambiguous in four ways: which statement (consolidated versus segment), which
filing (original versus amendment), which unit (thousands versus millions), and which instant (filed,
accepted, publicly available). Show `docs/CONCEPTS.md` and the concept table: closed vocabulary,
scope rules, and segment-sensitive concepts that are consolidated-only.

## 2. Resolution and binding (1:00–2:00)

In Answer certificates, resolve *gross profit* for 2023. Then open the certificate JSON: `inputs[0]`
carries `cell_id`, `unit_id`, `table_id`, `document_id`, `accession`, `row_label`, `column_label`,
`raw`, `value`, `scale`, `currency`, `statement_family`, `entity_scope`. Explain that the value is
read from the parsed document, not from an XBRL convenience API.

## 3. Arithmetic and verification (2:00–3:00)

Point at `formula: lookup(cell)` for a lookup, then run a derived concept. The compiler turns the
expression into exact fractions; the verifier recomputes independently. Note the deliberate wording
`verified_but_not_proven_correct`: consistency is checked, interpretation is the analyst's.

Watch for the citation-quality flag: on filings whose statements put currency symbols in their own
columns, Atlas reports `ambiguous_column_label` rather than asserting a column name it cannot
vouch for. That flag came out of the real-filing acceptance run.

## 4. Point in time (3:00–3:30)

Move the information cutoff. Values unavailable at that cutoff disappear rather than being
back-filled. Availability precision is reported as `unknown`, `date` or exact, and a modelled bound
is labelled as a bound.

## 5. Artifacts and surfaces (3:30–4:30)

Build a memo in the Valuation workspace, save it, export PDF and JSON, then run *Check for new
evidence*. Show the same question through the CLI and through the MCP server with the official SDK:
`python -m pytest tests/test_mcp_sdk_interop.py`.

## 6. Limits and reproduction (4:30–5:00)

`scripts/accept_phase10_4.py` (30 steps, synthetic, offline) and
`scripts/accept_real_filing_phase10_5.py` (45 steps, live Apple 10-K). Close with the limitation
list and what has not been tested: independent human evaluation, other MCP clients, and anything
about a browser beyond the 21-step journey (which passes on Chromium, Firefox and WebKit in CI).
