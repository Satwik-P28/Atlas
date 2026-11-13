# Phase 9.6 — Independent Financial Retrieval Evaluation

**Status: complete for evaluation; research-accuracy claim not certified.**

## What was evaluated

112 questions from FinanceBench's `OPEN_SOURCE` subset that target annual reports, run against a
corpus Atlas did not author and cannot tune: 64 real 10-K filings from 32 issuers, 112,484
passages, 11,851 tables, 303,025,449 source bytes (see `PHASE9_6_DATASET_AND_RIGHTS_MANIFEST.md`).

Questions were not rewritten. 38 of the 150 open rows are excluded with recorded reasons
(15 10-Q, 9 8-K, 14 earnings calls: `document_type_outside_ingested_scope`), because the corpus
holds one filing per fiscal year and guessing which quarterly report answers a question would
attribute results to the wrong document.

## Pre-registered thresholds

Declared in `scripts/phase9_6_evaluate.py` before the held-out run:

| Gate | Threshold | Result | Status |
| --- | --- | --- | --- |
| Citation integrity | 1.00 | 1.0000 | pass |
| Future-leak rate | 0.00 | 0.0000 | pass |
| Cross-issuer rate | 0.00 | 0.0000 | pass |
| Target-document recall@5 | ≥ 0.60 | 1.0000 (@10) | pass |
| Answer-presence recall@5 | ≥ 0.40 | 0.2411 (@10) | **fail** |
| Abstention recall (strict) | ≥ 0.80 | 0.7000 | **fail** |

## Measured results (baseline = Phase 9.5 BM25; challenger = precision-first lexical)

| Metric | bm25 | lexical_improved |
| --- | --- | --- |
| Questions scored | 112 | 112 |
| Correct document @1 | 0.7589 | 0.7589 |
| Target document recall @10 | 1.0000 | 1.0000 |
| MRR | 0.8424 | 0.8424 |
| Annotated evidence localized | 0.9732 | 0.9732 |
| Reference answer literal presence @10 | 0.2411 | 0.2411 |
| Citation integrity | 1.0000 | 1.0000 |
| Future-leak rate | 0.0000 | 0.0000 |
| Cross-issuer rate | 0.0000 | 0.0000 |
| Latency p50 / p95 (ms) | 642.66 / 791.09 | 643.86 / 769.72 |

The challenger changed the match expression only (phrase → all-terms → OR). With document
retrieval already at 1.0 there was no headroom for it to show a gain, and it did not: the two
methods return the same ranked documents on this corpus. That is reported as a negative result,
not as an improvement.

## Reading the gap

The distance between 0.9732 (evidence reachable) and 0.2411 (reference answer literally present)
is the central finding. FinanceBench answers are frequently *derived* — a margin, a turnover
ratio, a year-over-year change — and never appear verbatim in any filing. Atlas retrieved the
document containing the inputs in 97% of cases and the passage containing the printed answer in
24%. Retrieval quality is not the same as answer construction, and this phase does not claim the
latter.

No human adjudication of evidence relevance or claim entailment was performed. These results are
therefore an independent *retrieval* evaluation, not an independently validated
research-accuracy benchmark.

## Failure inventory

All 85 record-level failures are `answer_not_present_in_retrieved_passages`; there were no
citation, leakage or issuer failures. Per-question records, target ranks, returned accessions,
latency and failure class are in `artifacts/phase9_6_evaluation.json` (`schema:
atlas.phase9_6.evaluation.v1`), together with the question-set SHA-256 so the same 112 questions
can be verified later.

## What would change the verdict

1. Table-cell-level retrieval and unit/period verification, so a printed value can be located
   inside a table rather than hoped for in a narrative passage.
2. Independent human adjudication of a fixed sample, with inter-annotator agreement recorded.
3. A supervised abstention policy; see `PHASE9_6_CITATION_AND_ENTAILMENT.md`.
