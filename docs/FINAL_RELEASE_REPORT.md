# Priority 0 application-ready checkpoint

## Repository

| Ref | SHA |
|-----|-----|
| Starting main | `644448d4fbb3414c9c8045f5a86030ef34bfe2df` |
| Clean candidate base | `616f131ffa5f19dad4ceee4b8f02ba874a497b57` (`release/9.6.4-candidate`) |
| Development (same tree as candidate) | `5b185a8fe36dcbe0d2e9c053ffde3003ed65d2d6` |
| Spec v3.1.0 SHA-256 | `d1800cfea35d973e2ff2b3570f8bf564fd3a7aceabca2f623ec5de17931a1111` (verified) |

Priority 0 branch: `cursor/focus-priority0-827f` (see latest commit after push).

## Engineering

Repaired evaluator integrity; bound evaluation path; unknown-scale refusal; 3M millions detection; typed display precision; research certificates + CLI verifier; `make focus-demo`.

## Research

Controlled real-filing demonstration and certificate adversarial tests. No FinanceBench population score claimed.

## Numerical correctness

See `docs/FOCUS_FILING_CASE_OUTCOMES.md`.

## Testing

`tests/test_focus_certificate.py`, `tests/test_phase9_6_4_evaluator_integrity.py`, binding/geometry and financial answer suites green for Priority 0 changes.

## FOCUS readiness

Working demo, technical note, architecture, research results, resume evidence, engineering defense, application package, reproduction command.

## Release status tags

- `FOCUS_READY` — application-ready checkpoint on the Priority 0 branch with measured demo.
- `BLOCKED_BY_HISTORY` — do not force-push `main`; ancestry still includes `d8ae4f1`.
- `BLOCKED_BY_MISSING_DATA` — FinanceBench licensed rows absent → evaluator exit 2.
- Not claimed: `MAIN_PROMOTED_AND_VERIFIED`, `RESEARCH_VALIDATED` (population benchmark).
