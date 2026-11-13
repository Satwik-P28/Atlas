# Phase 9.6.2 — Arithmetic validation

All reference values are computed by hand from the fixture table, not copied from engine output.

Fixture: FY2020/FY2019, caption "in millions": Revenue 1,234 / 1,100; Cost of revenue (234) / (200);
Gross profit 1,000 / 900; Net income 100 / -50; Total assets 2,500 / 2,000; Shares outstanding
dash / 10.

| Case | Expected | Basis |
| --- | --- | --- |
| lookup revenue 2020 | 1234.00 | printed cell |
| lookup net income 2019 | -50.00 | minus sign preserved |
| revenue change 2020 vs 2019 | 12.18 | (1234-1100)/1100*100 |
| gross margin 2020 | 81.04 | 1000/1234*100 |
| assets / revenue 2020 | 2.03 | 2500/1234 |
| total revenue+gross profit 2019 | 2000.00 | 1100+900 |

Result: 6/6 answered and matching (`calculation_correctness = 1.0`).

## Independent recomputation

Every answer re-parses the raw strings with `parse_number` and recomputes the formula without
reusing `Cell.value`. A mismatch yields `unverified_calculation` rather than an answer.

## Refusal tests

Dash cells, missing metrics, wrong prior period, zero denominators, conflicting units, merged
headers, duplicate labels and future cutoffs all abstain or stay unresolved. Footnote markers are
stripped but recorded. A dash is never treated as zero.

## Scope of the claim

The engine is validated on this fixture and the 14 unit tests, not on FinanceBench arithmetic.
FinanceBench arithmetic questions are counted as unsupported in the evaluation.
