# Phase 9.6 — Final Report

## 1. Commits

| | |
| --- | --- |
| Before | `486e7d0fd4b01e7c402dff1d54b463c00aefa614` |
| Implementation + evidence | `d8ae4f1` (this report is the following commit on the same branch) |
| Branch | `freebuff/0139b8fdada4bab1ac65bcfa` |
| `main` | **not promoted** — see §12 |

## 2. Defects confirmed and repaired

1. **Historical availability was acceptance time.** EDGAR acceptance is not public availability;
   the engine now stores `availability_time = acceptance + 900 s` with an explicit basis and
   precision, and the evaluator re-checks availability on every returned passage.
2. **Issuer identity by string similarity was unsafe.** Fuzzy matching mapped Amazon→AAON,
   Verizon→Veritone, CVS→VSEE. Replaced with a 32-entry verified CIK table; no guessing.
3. **The any-absent-term abstention rule rejected 91 of 112 answerable independent questions**,
   mostly over instruction wording. Repaired by splitting retrieval from assertion (balanced vs
   strict) and excluding instruction vocabulary.
4. **Answer comparison failed on formatting.** `$1,577.00` never matched `1,577`; normalisation
   plus digit-boundary matching now handles it, and unit scaling is deliberately not inferred.
5. **Benchmark bookkeeping.** Every exclusion carries a reason, every metric carries its
   denominator, and no question can vanish silently.

## 3. Independent dataset and licensing

FinanceBench `OPEN_SOURCE`, 150 rows, CC-BY-NC-4.0, evaluation only, not redistributed.
112 questions scored; 38 excluded with recorded reasons. Corpus: 64 EDGAR 10-Ks, 32 issuers,
112,484 passages, 11,851 tables, 303 MB, 0 ingestion failures.

## 4. Baseline vs challenger

BM25 and the precision-first cascade are **identical** on every quality metric
(correct@1 0.7589, recall@10 1.0000, MRR 0.8424, evidence localized 0.9732). The baseline already
saturates document retrieval, so the challenger has no headroom; it is not promoted.

## 5. Citation integrity vs semantic support

Citation integrity: **1.0000** (112/112). Evidence relevance and claim entailment: **not
measured**, and no LLM was used as a judge. The 0.9732 evidence-localization vs 0.2411
answer-presence gap is the phase's central quantitative finding: Atlas finds the document, and
usually the evidence, but does not construct the answer.

## 6. Temporal leakage and abstention

Future-leak rate **0.0000**; cross-issuer rate **0.0000**. Strict abstention recall **0.7000** on
10 self-authored negatives — below the pre-registered 0.80 gate, and recorded as an open defect.

## 7. Resources

p50 ≈ 0.64 s, p95 ≈ 0.79 s per query at 112k passages, single-process SQLite FTS5, no GPU, no paid
API. Phase 9.5 measured 7.7 ms at six documents; the cost is corpus size.

## 8. Advanced browser certification

**Not executed.** Frontend unit tests (45), typecheck and production build pass (301.37 kB entry,
94.33 kB gzip), but the Advanced `filing` panel journey, issuer-switch check, save/reload,
Standard-vs-Advanced equivalence, 390 px control and screenshots were not run. No browser claim is
made.

## 9. Cross-issuer case

Boeing FY2019 (`0000012927-19-000010`) and Lockheed Martin FY2020 (`0000936468-21-000013`) at
cutoff 2021-06-30, both `verbatim_excerpt`, both re-hashed and verified on reopen, periods
explicitly not equated, missing concentration data recorded, `equivalence_asserted: false`.

## 10. Tests

* Knowledge suite: **24/24 pass** (21 existing + support-policy and normalisation regressions).
* Full backend suite: 4 failures in `tests/test_phase6_learning.py`, **reproduced at the base
  commit `486e7d0`** with this environment's freshly resolved dependencies — pre-existing
  dependency drift, not caused by Phase 9.6, and not fixed here.
* Frontend: 45/45 tests, `tsc -b --noEmit` clean, build clean.
* Master spec: 333,547 bytes, SHA-256 `d1800cfe…31a1111`, verified unchanged.
* Evaluation harness exit code: 1 (gates unmet), intentionally not masked.

## 11. Remaining limitations

Answer construction from tables; human adjudication of relevance/entailment; supervised
abstention; dense/hybrid retrievers not evaluated; adversarial temporal boundary tests, malicious
HTML, decompression limits and concurrency tests not written; Advanced panel not certified.

## 12. Promotion

**`main` was not promoted.** Two pre-registered gates failed (answer-presence 0.2411 < 0.40;
abstention recall 0.70 < 0.80), the Advanced browser certification was not executed, and the
pre-existing Phase 6 failures mean the full required suite is not green. Promotion is blocked by
the phase's own rules; no threshold was relaxed after seeing results.
