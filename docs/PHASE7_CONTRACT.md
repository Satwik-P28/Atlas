# Phase 7 contract

Phase 7 may extend the learning system only through versioned, tested interfaces. It must
not relabel an observed demo panel as point-in-time data or turn a probability experiment
into an alpha claim.

## Stable interfaces to preserve

* `atlas.learning.dataset.v2` — dataset id, source rights, data class, coverage, quality,
  adjustment convention, historical vintage and content hash.
* `atlas.learning.feature.v2` — feature key, formula, window, missing policy, feature cutoff
  and target outcome date.
* `atlas.learning.model_artifact.v1` — JSON-only artifact, scaler, coefficients/weights,
  seed, software versions and optional calibration.
* `atlas.learning.model.v2` and `atlas.learning.run.v2` — immutable model/run identity,
  attempt ledger, split metadata, fingerprint and conclusion.
* `atlas.forecast.v1` — binary/continuous forecast, horizon, outcome space, data class and
  null decision rule absent a strategy.
* `atlas.learning.audit.v1` — named findings with evidence/limitations and
  `overall_score: null`.
* `atlas.learning.monitor.v1` — drift/realized calibration observations, sample sizes, no
  automatic retrain.
* `atlas.learning.discovery.v1` — bounded grid, test-not-used flag, retained attempts.
* `atlas.quant.reference.v1` — close decision, next-open fill, long-only ledger and
  reconciliation.
* `atlas.research_object.v1` — model, experiment and application versions.
* All Phase 1–5 contracts, especially source identity, availability and portfolio accounting.

## Required before stronger claims

1. **Point-in-time market archive.** Store provider publication/retrieval times, corrections
   and a defensible historical vintage. A current bulk download is not enough.
2. **Broader authorized universe.** More names, historical membership, delisting returns and
   explicit survivorship limitations. Do not merge synthetic and real names silently.
3. **Fundamental/macro timing.** Key accounting and economic observations by `available_at`
   and revision vintage; fit normalization and imputation on train only.
4. **Calibration and uncertainty at scale.** More than one populated probability bin,
   horizon grouping, purged CV for overlapping labels, and search-level multiple-testing
   control.
5. **Decision-aware evaluation.** Predefine threshold/position rules, costs, turnover and
   capacity; keep forecast accuracy and strategy economics separate.
6. **Search ledger as a research object.** Deduplicate decision-equivalent candidates and
   require a fresh confirmatory experiment before promotion.
7. **Monitoring policy.** Explicit thresholds, sample sizes, correction handling and user
   authorization for retraining/deployment.
8. **Event/probability compatibility.** Typed event, outcome space, resolution and
   settlement deadlines, forecast revisions, contract references and independent outcome
   verification. Read-only market research first; no live orders, custody or wagering.
9. **Security.** No arbitrary code execution from model specs, no untrusted document gaining
   file/credential/tool access, no restricted vendor bytes in exports.
10. **Performance at scale.** Measure larger panels and feature counts before adding a GPU or
    custom kernels; preserve the CPU baseline.

## Explicit non-goals

Live trading, order routing, high-frequency order-book reconstruction, autonomous deployment,
unrestricted web research, market foundation models, and claims of causal identification.

## Definition of done

A Phase 7 claim needs an independent assertion, a persisted artifact, a measured result where
performance is claimed, an explicit data class, and a stated limitation. Interfaces, mock
models and attractive charts are not capabilities. Failed experiments remain in memory.
