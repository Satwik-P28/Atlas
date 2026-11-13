# Phase 9.6.1 — Defect Audit

Starting point: `efb79c9` on `freebuff/0139b8fdada4bab1ac65bcfa`, whose parent chain leads to
`486e7d0` on `main`. Each defect below was reproduced before being repaired.

| # | Defect | Severity | Evidence | Status |
| --- | --- | --- | --- | --- |
| 1 | Committed evaluation artifact contained licensed FinanceBench `question` and `answer` text, contradicting its own rights manifest | Critical (data handling) | 244 licensed fields in `artifacts/phase9_6_evaluation.json` | Repaired in working tree; **history exposure open** |
| 2 | `@5` gates were satisfied by `@10` metrics | High (acceptance integrity) | `scripts/phase9_6_evaluate.py:102-105` | Repaired: exact-K evaluator v9.6.1 |
| 3 | `question_set_sha256` hashed sorted ids only | High (reproducibility) | fingerprint `4b3c8500…` unchanged by answer edits | Repaired: content fingerprint |
| 4 | Availability labelled `exact` for `acceptance + 900 s` | High (historical claim) | `availability_precision="exact"` on 64 documents | Repaired: `unknown` + `availability_model` + migration 015 |
| 5 | Cutoff compared as raw strings, so `…:00Z` > `…:00.000Z` | High (temporal boundary) | boundary second excluded in test | Repaired: normalise cutoff via `iso()` |
| 6 | Phase 6 suite reported as "dependency drift" | High (release integrity) | four failures were a missing `learning` extra | Repaired: `requirements-learning.lock` installed; suite green |
| 7 | Evidence "localization" used incidental numeric overlaps | Medium (metric meaning) | proxy accepted any number in concatenated passages | Repaired: renamed `evidence_proxy@k`; span recall `not_evaluable` |
| 8 | No bound on query size | Medium (resource exhaustion) | 128+ term query accepted | Repaired: `MAX_QUERY_CHARS`/`MAX_QUERY_TERMS` |
| 9 | Saved desk lost instrument binding | Medium (UX/state) | restored panel shows "No instrument selected" | **Open** — persistence code added, not verified |
| 10 | Single-panel desk cannot be saved | Low (layout invariant) | "A split needs 2 to 6 children" | Open, recorded |
| 11 | Abstention recall below threshold | Research gap | strict policy 0.625 dev, 8/8 holdout negatives | Open by design; not tuned to pass |
| 12 | Answer construction unmeasured | Research gap | 0.2411 literal presence @10 | Open; arithmetic adapter not built |

## What Phase 9.6.0 still proves

Its scores are preserved unchanged in the sanitized artifact (`methodology_version: 9.6.0`):
document recall@10 1.0000, citation integrity 1.0000, leak 0, answer presence@10 0.2411, and the
failed `answer_presence` gate. Sanitisation removed text, never numbers.

## Severity policy

Critical: licensed content or a false release claim. High: a metric, timestamp or test suite that
says something untrue. Medium: integrity or reproducibility of an individual workflow. The release
remains blocked on #1's history exposure and on the failed research gates.
