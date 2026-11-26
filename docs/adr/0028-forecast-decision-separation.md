# ADR 0028 — Forecast and decision separation

Status: accepted, Phase 6.

## Context

A calibrated probability is not a position. Converting it into a trade requires a threshold,
sizing, costs, fills and constraints. Allowing the UI or model to silently produce an order
would conflate forecast accuracy with economic value and bypass the existing ledger.

## Decision

* Forecasts are `atlas.forecast.v1` documents with `decision_rule: null`.
* The only Phase 6 conversion is an explicit strategy with signal
  `learning_probability`.
* The strategy stores a frozen date→probability mapping, threshold, long-only constraint,
  costs and next-open fill convention.
* The threshold is part of the strategy **and** application identity. Changing it creates a
  new immutable strategy/application.
* The existing event-driven Quant Lab and portfolio reconciliation remain authoritative.
* A forecast experiment and a strategy experiment are separate claims.

## Consequences

Positive:

* no hidden order generation;
* the portfolio result can be audited against the independent ledger;
* repeated experiments cannot silently overwrite a different decision rule;
* the 0.50 result can be honestly described as equivalent to buy-and-hold.

Negative:

* the current rule is deliberately simple (one instrument, long-only, fixed threshold);
* no position sizing or portfolio optimization;
* the test window is applied to one security at a time in the demonstration.

## Evidence

At threshold 0.50 the frozen rule returns 14.3797%, exactly buy-and-hold, with zero excess.
At 0.55 it holds cash. This is reported as no decision-layer value, not alpha.

## Follow-up

Phase 7 may add a decision-aware experiment with predefined sizing and cost sensitivity, but
must retain the forecast/strategy distinction.
