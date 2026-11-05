# Event and claim ontology

Schemas: `atlas.economic.claim.v1`, event records in schema 9, graph
`atlas.economic.graph.v1`.

The ontology exists to stop the UI and model pipeline from silently turning a hypothesis or a
statistical association into an observed fact or causal effect.

## Epistemic states

| State | Meaning | Promotion rule |
|---|---|---|
| `observed` | Directly supported observation or documented relationship | Requires source evidence and preserved time |
| `inferred` | Conclusion produced by a stated inference rule | Must retain rule and inputs |
| `hypothesized` | Proposed mechanism without causal identification | Can never be rendered as observed |
| `estimated_causal_effect` | Estimate with an explicit identification design, assumptions, uncertainty and falsification tests | Requires a declared design such as DiD/ITS |
| `counterfactual` | Model result under a hypothetical intervention | Must state scenario and assumptions |
| `unresolved` | Conflicting or insufficient evidence | Both records retained; no winner chosen |

Separate causal statuses are `not_applicable`, `association`, `identified` and
`not_identified`. A claim can be observed with `not_applicable` causality; a weather-demand
claim can be `observed` at the data level while the estimated relationships are an
`association` with `not_identified` causality.

## Event object

An event has stable identity, type, geographic scope, affected entities, observation interval,
publication interval, source records, measurements, definition, status, uncertainty,
historical availability and linked research objects.

Implemented event types include a temperature-threshold event and an analysis event. Events
are not financial contracts and do not imply tradeability. The API exposes event counts in the
catalog and stores event records in `economic_event`.

## Claim object

Implemented claims store:

* stable `claim_id` and subject key;
* predicate and numeric or text value;
* unit and observation reference;
* source and claim time;
* epistemic status and causal status;
* review status;
* metadata JSON.

The fixture contains observed daily maximum-temperature claims for the two stations and a
hypothesized weather-demand relationship. Claims from the assumption source are barred from
being counted as observations.

## Conflict object

A conflict records the subject, claim IDs, detection time, status, reason, resolution (null
until a reviewer resolves it), dependent-research stale flag, values, units, sources and
observation IDs.

The flagship conflict is:

* subject `dallas_area.daily_max_temperature.2023-06-30`;
* values **32.8 °C** at Redbird and **35.6 °C** at DFW;
* both `observed`, both from `noaa-ghcn`, both preserved;
* status `unresolved`, resolution `null`;
* dependent research flagged stale.

This is treated as station representativeness and instrument/location disagreement, not a
single truth adjudication.

## Prohibited promotions

* A language-model explanation is not evidence.
* A regression with controls is not automatically causal.
* A prediction-market price is not a calibrated probability.
* A news mention count is not event severity.
* A supplier or utility relationship cannot be invented for graph completeness.
* A stale result is not silently rewritten; the user must inspect and rerun.

## Limits

The ontology implements typed storage and API views, not a full event calculus. There is no
event deduplication service, no automated article extraction, no temporal event algebra and
no reviewer UI beyond status preservation. Resolution is data-level; the UI currently exposes
the conflict and a correction drill, not an adjudication workflow.
