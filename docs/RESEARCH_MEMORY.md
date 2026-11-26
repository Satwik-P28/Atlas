# Research memory

Status: **implemented as a persistent, queryable experiment ledger.** It works without an
LLM. An optional model may summarize it later, but the records and arithmetic remain
authoritative.

## Storage

Schema 8 adds four append-oriented tables:

| Table | Purpose |
|---|---|
| `learning_run` | Run identity, dataset, target, data class, spec, canonical result, fingerprint, status, duration |
| `learning_attempt` | Every candidate model, stage, rank, selected flag and metrics |
| `learning_model` | Immutable artifact, feature schema, family, target, dataset, fingerprint, metadata |
| `learning_forecast` | One row per security/date probability with horizon and eventual outcome |

`learning_run` and `learning_attempt` are written in one transaction. Model and experiment
research objects are created next, then forecasts and model metadata. A run that already
exists is returned rather than overwritten; the deterministic run id makes a repeated
identical experiment idempotent.

## What is remembered

* the hypothesis and selected model;
* the dataset, source, rights and content hash;
* the feature schema and target definition;
* the chronological split and embargo;
* every candidate attempt and its validation metrics;
* the untouched test metrics and calibration;
* the audit findings;
* forecasts with their as-of dates and later outcomes;
* the model/experiment research-object ids;
* the software versions and artifact fingerprint;
* failed candidates, when a model raises, are retained in the attempt ledger.

A negative run is not deleted. The real demo memory currently reports:

```json
{"runs": 1, "not_supported": 1, "inconclusive": 0, "supported": 0}
```

## Queries

`POST /api/learning/memory` with optional `target`, `model`, `conclusion` and `limit`
returns matching run summaries and counts. `GET /api/learning/runs` lists recent runs;
`GET /api/learning/runs/{id}` reopens the full result; `GET /api/learning/models` lists
saved artifacts.

The UI history row reopens a run, including its test metrics, calibration and audit. The
Learning Lab also lists saved applications. Reopening is a read: it does not retrain or
change the artifact.

Questions the current ledger can answer:

* Which model was selected for this target?
* Did any candidate fail?
* What was the validation score versus the test score?
* Was the test interval used for selection?
* Which findings warned about data rights or historical vintage?
* Which experiment produced this model object?
* What changed since the previous run? (compare summary metrics; there is no semantic diff
  view yet)

Questions it cannot answer without new data:

* Are improvements concentrated in one market regime? (no regime labels; only split dates)
* Are conclusions invalidated by a vendor correction? (no correction/vintage store)
* Does the model work on a broader universe? (five names)
* Is the new model better after multiple-testing adjustment? (no cross-run correction)

## Research-object interoperability

The model and experiment are registered as existing `atlas.research_object.v1` objects.
They can be opened, compared and used by the research-application workflow. A retrain
creates a new version; the old row is not mutated. The model object includes the feature
schema, artifact, split, validation metrics, data class and limitations.

## No-LLM guarantee

The memory endpoints perform SQL reads and deterministic JSON summarization. No network,
language model, embedding or external service is required. An AI assistant could phrase a
summary, but it would not be allowed to change a metric or invent a failed run.

## Limitations

* No semantic version diff/merge UI.
* No cross-run multiple-testing correction.
* No scheduled retraining or monitoring job.
* No lineage graph beyond the stored object ids and run references.
* No automatic invalidation when a local vendor cache is refreshed.
* The database is single-user and local; there is no authentication or multi-tenant access.
