# Resume evidence

Git checkpoint for these bullets: branch `cursor/focus-priority0-827f` (derive SHA after merge/push). Spec baseline SHA before edits: `616f131ffa5f19dad4ceee4b8f02ba874a497b57`.

## Bullet 1

**Built a point-in-time SEC research pipeline that binds consolidated statement cells through a typed financial compiler and an independent Fraction verifier, packaging answers as fingerprint-stable research certificates.**

| Evidence | Path |
|----------|------|
| Binding + FEC path | `src/atlas/research/financial_answers.py`, `src/atlas/research/financial_concepts.py` |
| Independent arithmetic | `src/atlas/research/financial_verification.py` |
| Certificate schema | `src/atlas/research/certificate.py` |
| CLI verifier | `atlas verify-certificate` in `src/atlas/cli.py` |
| Tests | `tests/test_focus_certificate.py`, `tests/test_phase9_6_4_binding_and_geometry.py` |
| Demo | `make focus-demo` → `artifacts/focus_demo/report.json` |
| Measured | 3M FY2022 net sales `34229.00` at scale 6; certificate status `valid` |

**Limitations:** No XBRL corroboration; HTML geometry still inferred.

## Bullet 2

**Repaired financial evaluation integrity: fixed missing hashlib citation checks, success-conditioned recall denominators, a tautological assertion-precision formula, zero-denominator “perfect” scores, and methodology versioning; added hand-computed confusion-matrix tests.**

| Evidence | Path |
|----------|------|
| Evaluator | `scripts/phase9_6_4_evaluate.py` |
| Tests | `tests/test_phase9_6_4_evaluator_integrity.py` |
| Measured | Missing FinanceBench rows → exit `2` + `unavailable_reference_data` (no fabricated score) |

**Limitations:** Full FinanceBench gates require licensed rows out-of-band.

## Bullet 3

**Diagnosed and fixed cross-issuer unit/scale inconsistency (3M FY2022 net sales previously `scale=0` vs Coca-Cola `scale=6`), including in-table “(Millions, …)” detection, unknown-scale refusal, and typed display precision by answer type.**

| Evidence | Path |
|----------|------|
| Scale detection | `src/atlas/research/table_cells.py`, `_statement_context` in `financial_answers.py` |
| Case re-run | `artifacts/phase9_6_4_case_studies.json` (10 answered / 3 abstained) |
| Measured | 3M scale `6`; economic amount `34229000000`; ratios displayed to 4 dp |

**Limitations:** Pathological colspan/rowspan layouts can still mis-align columns.

## Draft resume lines (only after the evidence above remains true)

1. Built a point-in-time SEC research system that binds filing cells into typed computations, independently recomputes them with Fraction arithmetic, and emits verifiable research certificates (`atlas verify-certificate`).
2. Hardened a financial evaluation harness so zero denominators are not-evaluable, citation hashes are recomputed from stored bytes, and confusion-matrix metrics are tested against hand-computed cases.
3. Fixed issuer-scale integrity for real 10-K tables (including 3M FY2022 net sales at USD millions) and demonstrated justified abstention under historical cutoffs.
