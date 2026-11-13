# Phase 9.6.4 — Evaluator Integrity

## Exit semantics

`scripts/phase9_6_4_evaluate.py` separates three outcomes:

| Condition | Exit | Artifact |
|---|---|---|
| All mandatory gates pass | 0 | full evaluation payload |
| Any mandatory gate fails | 1 | payload + `MANDATORY GATE FAILURE: <gates>` |
| Reference questions missing / unreadable | 2 | `evaluation_status: unavailable_reference_data` |

`gate_exit_code()` returns 0 only when the gate map is non-empty and every gate is true, so an
empty or zero-eligible population can never pass. The 9.6.3 runner's unconditional `return 0` is
not present in the 9.6.4 runner.

## Gates

`eligible_population`, `concept_resolution`, `cell_localization`, `answer_correctness`,
`citation_integrity`, `abstention_precision`, `false_assertions`. Thresholds are carried from
9.6.3 and declared before the run; they were not tuned against the 9.6.4 holdout (none exists).

## Citation integrity

The 9.6.3 check only asserted that a unit exposed a `sha256` field. The 9.6.4 check re-reads the
stored unit body and recomputes `sha256(body)`; a missing or mismatching digest counts as a
citation failure. Binding-level verification additionally re-reads the stored table row/column and
compares it to the bound raw text (`cell_not_in_source`).

## Negative audit

The 9.6.3 negative set asked for FY2017 revenue with a 2100 cutoff, which is answerable whenever
the corpus holds that filing. In the 9.6.4 runner this construction is recorded as
`historical_year_available` and counted as a **positive**, not as an abstention. Genuine negatives
are `undisclosed_metric` (ebitda) and `cutoff_before_availability` (1990 cutoff for a 2022 figure).
Each negative is logged with its class and status in `negative_log`.

## Current result

The licensed FinanceBench rows file was not present in this environment, so the 9.6.4 run reports
`unavailable_reference_data` and exits 2. No new FinanceBench metric is claimed. The historical
9.6.3 artifact is unchanged.

## Metrics with denominators

Definitions are reported with integer numerators/denominators: assertion precision, unanswerable
recall, abstention precision, answerable-question recall, false assertion rate, false abstention
rate, correctness among answered, correctness among all eligible, concept resolution, cell
localization and citation integrity. A single correct answer is never reported as general recall;
`false_assertions` and `false_abstentions` are emitted as counts alongside rates.
