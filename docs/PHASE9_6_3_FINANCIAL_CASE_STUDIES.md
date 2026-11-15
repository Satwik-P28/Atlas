# Phase 9.6.3 — Financial case studies

Runner: `scripts/phase9_6_3_case_studies.py`; artifact
`artifacts/phase9_6_3_case_studies.json`.

## Design

Three issuers with different reporting: Coca-Cola (operating), JPMorgan Chase (bank), 3M
(segment reporting). Twelve tasks: lookups, percentage change, margin, ratio, cross-document
lookup, plus an intentionally inappropriate bank gross-profit lookup. Cutoffs: 2023-06-30 for
Coca-Cola, 2024-01-01 for JPMorgan and 3M.

## Result: 0 answered, 12 abstained

| Family | Task | Outcome | Reason |
| --- | --- | --- | --- |
| operating | revenue FY2022 lookup | abstained | 2022 column has no period |
| operating | net income FY2022 | abstained | metric ambiguous |
| operating | revenue change 2022 vs 2021 | abstained | 2022 period missing |
| operating | operating margin FY2022 | abstained | missing input |
| operating | assets / revenue FY2022 | abstained | missing input |
| bank | total assets FY2022 | abstained | consolidated vs parent tables both complete |
| bank | net income FY2022 | abstained | metric ambiguous |
| bank | net margin FY2022 | abstained | metric ambiguous |
| bank | gross profit FY2022 | abstained | not disclosed (correct refusal) |
| segment | revenue FY2022 | abstained | consolidated vs segment ambiguity |
| segment | revenue change | abstained | missing input |
| segment | revenue FY2018 | abstained | vintage ambiguity |

This is a **failed demonstration**, not a certified capability. The arithmetic engine is verified on
fixtures and on cells the resolver returns; the resolver currently cannot establish statement
identity well enough on these filings to answer real questions. The bank gross-profit refusal is
the intended behaviour; the rest are coverage failures caused by missing period headers and
duplicate row labels across consolidated, parent and segment tables.

## What a passing packet would contain

`research_task`, typed plan, selected cells with coordinates/section/hash, concept and period
mapping, formula, independent recomputation, citations, limitations, fingerprint. The packet schema
is implemented; no real case reached `answered` in this run.
