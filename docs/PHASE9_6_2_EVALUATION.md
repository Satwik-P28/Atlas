# Phase 9.6.2 — Evaluation methodology

Runner: `scripts/phase9_6_2_evaluate.py`. Artifact: `artifacts/phase9_6_2_evaluation.json`
(sanitized). Historical artifacts `phase9_6_evaluation.json` and `phase9_6_1_evaluation.json` are
untouched and remain failed.

## Separation of metrics

| Metric | Meaning | Result |
| --- | --- | --- |
| document_recall@1 / @5 | correct document retrieved (carried from 9.6.1) | 0.7589 / 0.9732 |
| cell_localization_rate | verified cell in target document carries the reference value at its scale | 0.1429 |
| period_alignment_rate | localized cells carry an explicit period | 1.0 |
| citation_integrity | every localized cell resolves to a hashed unit | 1.0 |
| calculation_correctness | hand-computed fixtures replay exactly | 1.0 (6/6) |
| abstention_precision / recall | balanced mixed set | 1.0 / 1.0 |
| false_abstention_rate / false_assertion_rate | | 0.0 / 0.0 |
| future_leak_rate | | 0.0 |

Sample: first 40 of 112 eligible questions. 33 reference answers are prose or yes/no and are
counted as unsupported, leaving 7 numeric questions; 1 localized. That denominator is small and is
the main reason the localization gate fails.

## Pre-registered gates

`cell_localization >= 0.20` (FAILED at 0.1429), `citation_integrity == 1.0`, `calculation
correctness == 1.0`, abstention precision `>= 0.80` and recall `>= 0.70` with zero false
assertions, `future_leak_rate == 0`.

## What this is not

This is not a retroactive pass of `answer_presence@5` (0.1964, still failed). It measures whether
verified cells and compiled answers are right, not whether a reference string appears in retrieved
text. Correctness among answered questions and correct-over-all-eligible are reported separately
where both exist; here "answered" is 6 fixture cases and 1 localized FinanceBench cell, which is
far too small to claim benchmark success.
