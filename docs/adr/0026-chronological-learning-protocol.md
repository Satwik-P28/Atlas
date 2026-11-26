# ADR 0026 — Chronological learning protocol

Status: accepted, Phase 6.

## Context

Financial rows are ordered and cross-sectionally dependent. Random splits leak future
information, and repeated tuning on a final test set turns an out-of-sample claim into an
in-sample one. Phase 4/5 already used chronological partitions and an attempt ledger.

## Decision

For the first learning runtime:

* build one row per security/session with features through `t` and target `t+1`;
* record `date`, `available_at` and `target_date`;
* split 60% train / 20% validation / 20% test by date, not row;
* insert a two-session embargo;
* select the model on validation Brier;
* fit Platt calibration on validation only;
* evaluate the frozen selection/calibrator on test once;
* persist every candidate and set `test_used_for_selection: false`;
* classify a nonpositive test skill as `not_supported`;
* report cross-sectional dependence as a limitation on row-level intervals.

## Consequences

Positive:

* no future information in feature construction;
* calibration and selection do not touch test;
* negative results remain visible;
* the same protocol is used for every candidate.

Negative:

* one fixed split is sensitive to regime choice;
* the two-session embargo is not a full purged CV for overlapping labels;
* 685 rows are not 685 independent market observations;
* a single test period cannot establish persistent skill.

## Rejected alternatives

* random train/test split: rejected;
* select on test Brier and call it out-of-sample: rejected;
* calibrate on test: rejected;
* delete a losing model: rejected.

## Follow-up

Phase 7 should add walk-forward and purged cross-validation, with search-level multiple-testing
accounting, before making stronger claims.
