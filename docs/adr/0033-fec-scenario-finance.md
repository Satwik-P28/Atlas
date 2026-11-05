# ADR 0033 — Scenario finance goes through the FEC

Status: accepted.

## Context

A weather scenario produces a demand fraction, then needs cost, after-tax cost and margin
impacts. Implementing those formulas inside scenario code would create a second financial
engine and diverge from Atlas valuation and compiler behavior.

## Decision

Compile a small `atlas.model.v1` graph with three new operators:
`energy_cost_impact`, `after_tax_cost_impact` and `margin_impact`. Execute it through the
existing compiler/runtime. Scenario code computes the independent scalar arithmetic only as a
reconciliation assertion and stores the compiler run ID and fingerprint.

## Consequences

* Units, types and trace remain inspectable.
* Scenario results can be reproduced through the same compiler as other Atlas models.
* The simulator cannot silently redefine margin or tax arithmetic.
* The scenario is still narrow: no DCF, credit model, forward curve or hedge settlement.
