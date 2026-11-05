# ADR 0029 — Named audit findings and bounded discovery

Status: accepted, Phase 6.

## Context

A single “model credibility” score hides which assumption failed and encourages false
precision. An unrestricted discovery agent could tune indefinitely, contaminate the final
test set, or deploy an unvalidated model.

## Decision

Auditor:

* emit named findings with severity, evidence and limitation;
* set `overall_score: null`;
* separate data, statistical, forecast, economic, trading and reproducibility checks;
* never declare profitability from predictive accuracy.

Discovery:

* enumerate a finite declared grid;
* cap the budget at 24;
* use an early discovery split and never expose the final test;
* retain failures;
* return recommendations only;
* require a fresh confirmatory experiment before a model is promoted;
* never deploy or retrain automatically.

Monitoring follows the same rule: report drift and realized calibration with sample sizes,
but do not invalidate or retrain on a threshold crossing alone.

## Consequences

Positive:

* findings are actionable and reviewable;
* negative evidence survives;
* the test interval is protected from search;
* the system cannot call ordinary hyperparameter tuning “autonomous discovery”.

Negative:

* no single number for ranking studies;
* search is narrow and threshold candidates can duplicate metrics;
* no cross-run multiple-testing correction yet;
* a recommendation still requires human/confirmatory follow-up.

## Evidence

The real run reports 0 errors, 4 warnings and 2 infos. Discovery evaluated four candidates
with `test_used: false`; the thresholds duplicated Brier because threshold is not part of
that metric. That duplication is documented as a limitation rather than hidden.
