# Research integrity evaluation

Contract: `atlas.research_integrity.v1`, produced by `integrity_report()` in
`src/atlas/research/memo.py`, organised on Master Specification Section 52.

## Four independent dimensions

| Dimension | Passes when | Fails when |
| --- | --- | --- |
| Evidence | every factual claim resolves to stored evidence or a reproducible transformation, within the cutoff, with known rights | a claim cannot resolve its evidence, is unverifiable, or is restricted |
| Computational | every model claim reproduces and the independent component audit passed | the audit failed or a model claim did not verify |
| Statistical | an empirical test was run and met its stated criterion | an empirical test was run and failed |
| Decision | a supported valuation exists and its sensitivity grid is reported | the valuation verdict is not economically supported |

Outcomes are `pass`, `fail`, `insufficient_evidence`, `not_applicable`, `not_run`. The four
dimensions are reported separately, with the failing claim ids and check details; there is no
aggregate trust percentage.

## Rules that prevent flattering results

* **A deterministic valuation is not statistical evidence.** The statistical dimension is
  `not_applicable` for a memo with no forecast evaluation, regression or hypothesis test. It
  is never marked passed because the DCF executed.
* **Execution is not validation.** A model claim requires the independent component audit,
  which recomputes every component outside the compiled operator graph.
* **No price is not a pass.** With no authorised market observation the market comparison
  section reports unavailability, and the decision dimension reports what it can support
  without inventing a comparison.
* **Failures stay visible.** A failing claim is retained, listed in the unresolved
  contradictions section, and counted in `failures` and `outcome_counts`.

## Observed outcomes at this checkpoint

| Issuer | Method | Claims | Integrity |
| --- | --- | --- | --- |
| JPM | `residual_income_equity` (v3) | 36 | evidence pass, computational pass, statistical not applicable, decision fail (verdict not economically supported) |
| AAPL | `unlevered_fcff_dcf` | 48 | evidence pass, computational pass, statistical not applicable, decision pass |

The JPM decision dimension fails, and that is the correct result: the residual-income v3
contract stops at "arithmetically verified" and records that no economic review or external
benchmark exists. Reporting it as a pass would be exactly the kind of claim this dimension is
meant to prevent.

## What a reviewer can inspect

Every dimension carries `checks` with the concrete numbers (evidence record count, cutoff,
arithmetic verdict, component count, compiler version, assumption count, sensitivity
availability, final finding codes). A reviewer who disagrees with an outcome can re-run the
claim verifier and see the same diagnostics.
