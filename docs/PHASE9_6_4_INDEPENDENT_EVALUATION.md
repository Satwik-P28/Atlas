# Phase 9.6.4 — Independent Evaluation

## Test suite

- Backend: **766 passed** (`pytest -p no:warnings`), up from 749 before this phase.
- New tests: 12 in `tests/test_phase9_6_4_binding_and_geometry.py`, 5 in
  `tests/test_phase9_6_4_evaluator_integrity.py`.
- Frontend: **50 passed**, `tsc -b --noEmit` clean, production build 301.37 kB (94.32 kB gzip).

## FinanceBench

Not re-run. The licensed rows file lived in `/tmp` and was lost with the sandbox; it is not stored
in the repository by design. The 9.6.4 evaluator reports `unavailable_reference_data`, exits 2 and
writes that artifact. No metric from 9.6.3 is presented as a 9.6.4 result.

Historical 9.6.3 numbers, preserved unchanged: concept resolution 2/6, cell localization 1/2,
correctness among answered 1/2, citation integrity 1.0, abstention precision 0.9167 on 36
constructed negatives, 3 false assertions.

## Arithmetic

All computed answers pass the independent Fraction-based verifier inside the FEC run; a
disagreement produces `verification_disagreement` rather than an answer.
