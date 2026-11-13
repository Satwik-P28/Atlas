# Phase 9.6.2 — Bounded financial-answer compiler

Version: `9.6.2`; operator version `fec-table-9.6.2`. Module:
`src/atlas/research/financial_answers.py`.

## Supported questions

| Operator | Formula | Refuses when |
| --- | --- | --- |
| `lookup` | `cell` | metric missing, ambiguous, non-unique values |
| `percentage_change` | `(current - prior) / prior * 100` | inputs missing, same period, unit/scale mismatch, zero denominator |
| `ratio` | `numerator / denominator` | missing input, unit/scale mismatch, zero denominator |
| `margin` | `numerator / revenue * 100` | as ratio |
| `total` | `sum(components)` | any component missing |

Metric resolution is exact-label first, then token-set equality. Subset matching is rejected so
`revenue` never resolves to `Cost of revenue`.

## Output contract

An answered result contains: outcome, answer type, value (Decimal, half-up 2dp), unit and
currency, period, formula, operator/engine versions, every input cell with coordinate, raw text,
period, scale, source hash and knowledge-unit hash, an independent recomputation flag, the
rounding policy, limitations, and a reproducibility fingerprint over the plan and inputs.

`reported_value` means the number is quoted from one cell. Every computed type carries the
limitation that it is not a quoted filing number.

## Abstention

Refusals use closed reason codes (`metric_not_found`, `metric_ambiguous`, `missing_input`,
`unit_mismatch`, `period_mismatch`, `zero_denominator`, `no_verified_cells`, `future_evidence`,
...). Cells whose document was not available at the requested cutoff are filtered before
matching, so a numerically correct answer from future evidence cannot be produced.

## Not implemented

Multi-hop concept mapping (e.g. "operating margin" to two specific rows), CAGR across gaps,
segment-level aggregation with overlapping components, and fiscal-calendar reconciliation.
These are refused rather than approximated.
