# Forecast object contract

Schema: `atlas.forecast.v1`.

A forecast is a typed statement with an explicit horizon, outcome space, model identity,
data class and limitations. It is not a trading instruction.

## Implemented: binary probability

`forecast_document(...)` returns:

```json
{
  "schema": "atlas.forecast.v1",
  "forecast_id": "FCST-…",
  "model_id": "LMOD-…",
  "security_id": "SEC-…",
  "as_of": "2025-06-16",
  "horizon_sessions": 1,
  "kind": "binary_probability",
  "probability": 0.52,
  "outcome_space": {"values": [0, 1], "definition": "price direction over the declared horizon"},
  "prediction_interval": null,
  "data_class": "observed",
  "decision_rule": null,
  "limitations": [
    "A probability forecast is not a trading instruction.",
    "The outcome must be observed after as_of; it cannot be scored with information known at forecast time."
  ]
}
```

Rules enforced in code:

* the probability is finite and lies in `[0,1]`;
* the forecast id is a content-derived digest of model, security, date, horizon and value;
* `decision_rule` is null unless a separate strategy document supplies one;
* the outcome is not filled from information known at `as_of`;
* the data class is carried from the dataset, not inferred from the word “real”.

Persistence adds the eventual observed outcome in `learning_forecast.outcome` when it is
available. The original forecast value is not rewritten.

## Implemented: continuous return

`continuous_forecast_document(...)` returns:

* `kind: continuous_return`;
* `value` in simple-return units;
* `horizon_sessions`;
* a 90% prediction interval with lower/upper bounds;
* method text: `training residual approximation`.

The real-data companion ridge reports RMSE **0.017966**, MAE **0.011938**, mean error
**-0.0000988**, and 90% interval coverage **0.919708** over 685 test rows. The interval is
an approximation from training residual sigma, not a calibrated posterior distribution.
Coverage near the nominal level is not proof that the conditional distribution is correct.

## Not implemented: categorical probability

A categorical contract is specified for Phase 7 compatibility but is not exposed or tested
as an implemented endpoint. It must add:

* an explicit ordered or unordered outcome set;
* probabilities that are nonnegative and sum to one within a declared tolerance;
* a reference category or full vector;
* the same timestamp/outcome verification rules as the binary case.

Until then, no UI or API claims a regime classifier.

## Event compatibility contract

Phase 6 defines the following as typed field requirements, not a live event-market feature:

| Field | Requirement |
|---|---|
| `event_id` | Stable reference to the defined event |
| `outcome_space` | Mutually exclusive, exhaustive outcomes |
| `resolution_criteria` | Exact rule and data source |
| `observation_deadline` | When the outcome becomes observable |
| `settlement_deadline` | When a contract settles |
| `forecast_revision` | Superseding forecast id, never an in-place edit |
| `contract_reference` | Read-only market/contract identifier if any |
| `outcome_verification_source` | Independent source used after the deadline |

The three claims must remain distinct:

1. probability of an outcome;
2. probability that a contract price moves;
3. expected net result of an executable decision after costs and constraints.

Phase 6 implements none of the three as a trading/event engine. It only provides a compatible
forecast vocabulary and decision boundary.

## Decision separation

The strategy contract `learning_probability` requires:

* a frozen list of `{date, probability}` entries;
* a threshold in `[0,1]`;
* a declared fill convention (next open);
* a model id and forecast run id for provenance.

The signal maps probability above threshold to a long position. It does not choose position
size, borrow, short, or optimize a portfolio. Those are explicit decision-layer choices.

## Validation

Tests cover:

* probability outside `[0,1]` is rejected;
* duplicate forecast dates are rejected by strategy validation;
* the compiler probability operators reject misaligned inputs;
* forecast count equals test-row count in persistence;
* the threshold is part of the frozen strategy identity, so changing it creates a new
  strategy rather than silently editing the old one.

## Limitations

* Binary and continuous only.
* One-session horizon in the implemented learning runs.
* No live forecast scheduler.
* No event-contract settlement or market-price feed.
* No claim that a probability forecast has economic value.
