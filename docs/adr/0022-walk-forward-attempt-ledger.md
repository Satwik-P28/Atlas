# ADR 0022 — Persist every walk-forward candidate and freeze the test interval

**Status:** accepted (Phase 5)

## Context

A single attractive test result can hide the number of configurations tried. Selecting a
parameter on the test interval makes an “out-of-sample” claim false. Discarding losing
candidates makes the search unauditable.

## Decision

Use train → embargo → validation → embargo → test. Select one parameter per family on
train, select the family on validation, freeze it, then evaluate test once. Persist every
candidate at every stage in `validation_attempt`, including losers, with a `selected` flag.
Report the trial count, a block-bootstrap diagnostic and a Bonferroni-adjusted warning.
Expose `test_used_for_selection: false` in the result.

## Consequences

The research record is auditable and negative results remain visible. It does not eliminate
data snooping, regime change or model-class selection. The bootstrap is a diagnostic, not
proof of independence. The synthetic fixture cannot support a real-market claim.
