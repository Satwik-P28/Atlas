# Controlled automated discovery

Status: **implemented as a bounded candidate enumerator, not an autonomous research agent.**

## What it does

`src/atlas/learning/discovery.py`:

1. receives an explicit budget and optional model/feature-set lists;
2. enumerates a finite grid of model × feature-set × threshold candidates;
3. builds point-in-time features on a discovery split;
4. fits each candidate with a fixed seed;
5. scores validation Brier;
6. retains failures and successes;
7. ranks completed candidates;
8. returns at most three recommendations;
9. stops at the budget.

It does **not** use the final test interval, deploy a model, modify an existing model, or
claim open-ended scientific discovery.

## Search space

Default candidates:

* models: `ridge`, `logistic`, `mlp`;
* feature sets: `[mom_20, vol_20]`, the five default features, and a six-feature set with
  `mom_60`;
* thresholds: 0.50 and 0.55.

The threshold does not affect validation Brier, so it produces duplicate metric rows. This is
visible in the output rather than hidden. A future search should either vary a decision-aware
criterion or deduplicate equivalent candidates before spending budget.

## Real demo discovery

A budget-of-four run over two feature sets and one model produced:

| Candidate | Validation Brier | Rank |
|---|---:|---:|
| ridge, `mom_5`, `mom_20`, `vol_20`, threshold 0.50 | 0.248253 | 3 |
| same, threshold 0.55 | 0.248253 | 4 |
| ridge, `mom_20`, `sma_gap_20`, `cs_mom_20_rank`, 0.50 | 0.247949 | 1 |
| same, threshold 0.55 | 0.247949 | 2 |

`test_used: false`; stop reason: budget exhausted. The best discovery score is **not** the
final experiment result and is not called a validated model. It is a candidate for a fresh
confirmatory experiment.

## Budget and safety

* budget is bounded to `[1,24]`;
* there is no network access in the loop;
* there is no code execution from a candidate specification;
* feature keys are validated against the declared catalogue;
* model keys are validated against the model library;
* failures are recorded with their error, not skipped silently;
* no model is saved or deployed by discovery.

## What this is not

* Not a genetic program or symbolic regression.
* Not an LLM generating hypotheses.
* Not Bayesian optimization.
* Not a multiple-testing correction for the search.
* Not proof that the best candidate generalizes.
* Not a trading strategy search.

The value is a reproducible experiment ledger that can later support a more advanced
hypothesis-generation layer without surrendering control of budget, test isolation or
deployment.

## Next safe extensions

1. Deduplicate candidates whose decision threshold does not affect the selection metric.
2. Add explicit search-family budgets and a search-level multiple-testing record.
3. Add train/validation-only cross-validation for overlapping labels.
4. Require a fresh confirmatory experiment before a recommendation can become a model.
5. Preserve a search ledger as its own research object, not only a transient response.
