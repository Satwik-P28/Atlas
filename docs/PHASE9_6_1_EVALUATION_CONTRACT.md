# Phase 9.6.1 — Evaluation Contract

Version **9.6.1**. The 9.6.0 numbers remain in `artifacts/phase9_6_evaluation.json` under
`methodology_version: 9.6.0`; they were not recomputed or overwritten.

## Metric definitions

All rates use the same denominator: every question that matched an ingested document
(`questions_scored`, 112). Questions excluded before scoring are listed with reasons (38: 15 10-Q,
9 8-K, 14 earnings calls). Nothing is dropped silently, and a question whose target was never
retrieved counts as 0 rather than vanishing.

| Metric | Definition |
| --- | --- |
| `document_recall@k` | share of questions whose target accession appears in the first k passages |
| `correct_document_rate@1` | share whose first passage belongs to the target document |
| `mrr` | mean of 1/rank over **all** scored questions (unretrieved = 0) |
| `answer_presence@k` | share whose reference answer string/number occurs literally in the first k passages |
| `evidence_proxy@k` | share whose annotated evidence text overlaps a passage; **proxy only** |
| `evidence_span_recall@k` | `not_evaluable` — PDF page anchors cannot be aligned to SEC HTML spans |
| `citation_integrity` | share whose top citation re-hashes, spans and issuer-match |
| `future_leak_rate` | share returning a document whose availability exceeds the cutoff |
| `cross_issuer_rate` | share returning another issuer's document |
| `false_abstention_rate` | share of answerable questions the strict policy refuses |
| abstention `precision`/`recall` | computed from per-question abstain flags over positives/negatives |

Gate lookup goes through `required_metric`, which raises unless the requested key encodes its own
`k`. A test (`test_gate_cannot_read_a_metric_at_the_wrong_k`) pins this. The 9.6.0 runner's
`@5`-gate-on-`@10`-value defect cannot recur.

## Fingerprint

`evaluation_fingerprint` hashes, for every question: id, question text, answer text, document type,
period, target accession, cutoff and labels, plus the scoring configuration (version, k, policy,
support policy, thresholds, counts). Only the digest is published. Tests prove that changing an
answer, a question or the configuration changes it while the id stays the same.

Stored with each run: dataset revision, corpus manifest, retrieval version, scoring version,
configuration, question count, exclusions, environment (Python, platform, GPU=false, no seeds
needed — retrieval is deterministic).

## Results (v9.6.1, both methods identical)

| Metric | bm25 | lexical_improved |
| --- | --- | --- |
| document_recall@1 / @5 / @10 | 0.7589 / 0.9732 / 1.0000 | same |
| correct_document_rate@1 | 0.7589 | same |
| mrr | 0.8424 | same |
| answer_presence@1 / @5 / @10 | 0.0804 / 0.1964 / 0.2411 | same |
| evidence_proxy@1 / @5 / @10 | 0.5357 / 0.8839 / 0.9732 | same |
| citation_integrity | 1.0000 | 1.0000 |
| future_leak / cross_issuer | 0.0000 / 0.0000 | same |
| latency p50 / p95 (ms) | 615.37 / 723.82 | 619.32 / 728.69 |

Fingerprint: `28f305e02faf8fee…`. The challenger remains identical to the baseline: document
retrieval is saturated, so there is no headroom and no promotion.

## Gates (preregistered for 9.6.1)

| Gate | Threshold | Result |
| --- | --- | --- |
| citation integrity | 1.00 | pass |
| issuer integrity | 1.00 | pass |
| future leak | 0.00 | pass |
| cross-issuer | 0.00 | pass |
| document_recall@5 | ≥ 0.60 | pass (0.9732) |
| answer_presence@5 | ≥ 0.40 | **fail (0.1964)** |
| abstention precision/recall/false-abstention | ≥0.80 / ≥0.70 / ≤0.10 | **fail (1.0 / 0.625 / 0.0)** |

## Independence

The 112 questions were already exposed to Phase 9.6 engineering decisions. They are not an
untouched holdout, and no untouched answerable holdout exists in this phase. No human adjudication
of relevance or entailment was performed. These results are a reproducible *retrieval* evaluation,
not an independently validated accuracy claim.
