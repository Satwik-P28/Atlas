# Economic Sentinel v1

Status: deterministic manual refresh and dependency invalidation are implemented. There is no
scheduler, background worker or automatic retraining.

## What is monitored

* committed fixture SHA-256 versus each series’ ingestion hash;
* latest observed period and retrieval instant;
* observation, model, dataset and experiment dependencies;
* analyses marked stale;
* station evidence conflicts;
* correction alerts and their review status.

`GET /api/economic/sentinel` opens the current SQLite database, recomputes freshness matching,
persists alerts idempotently and returns the dependency and alert view. It does not modify
source values, model results or saved applications.

## Refresh behavior

* `source_freshness.changed_series` lists series whose ingested hash differs from the committed
  fixture.
* A changed source creates one `source_archive_changed` warning per series and does not rerun
  any model.
* `dependencies` groups exact dependency rows by observation, model, dataset or experiment.
* `stale_runs` returns runs invalidated by a revision.
* `automatic_retrain` and `automatic_deployment` are always false.
* Repeated source-hash alerts use a deterministic alert ID, so a refresh does not duplicate
  the same alert.

The shipped database has 1,098 dependency rows, 1,095 of them observation keys (three series ×
365 days) and three research-object dependencies. A normal refresh reports zero stale runs and
zero alerts.

## Revision behavior

A correction inserts a new observation with `revision_seq + 1` and `supersedes` the old row.
The old row remains. The dependency table is marked stale and an `observation_revised` alert is
recorded for each dependent run. The run status remains the historical `succeeded` result but
`stale: true` and `stale_reason` become visible. A saved application keeps its original result;
the user must inspect and rerun.

The UI correction drill demonstrates this without automatic adjudication. The 2023-06-30
Redbird claim is revised to 35.7 °C and dependent analysis `ERUN-ac92ae9ffef03de2` becomes
stale.

## Repeated-alert suppression

* Source-hash alerts use a deterministic ID over series and expected hash.
* Revision alerts use the run, observation and revision timestamp.
* The UI displays stored alerts, not an append-only notification stream.
* There is no external paging or email integration.

## Audit trail

The database retains analysis stale state, `economic_dependency.invalidated_at`, reason,
source revision rows, scenarios, applications and alerts. Nothing is overwritten. The user can
inspect the old observation through the research object export and the API.

## Explicit non-capability

Phase 7 does **not** promise background monitoring. A server restart or a changed source file
does not automatically execute a refresh. A user or scheduled external job must call the
endpoint. There is no cron, queue, webhook or alert delivery. Do not describe this as live
monitoring.

## Thresholds

Current thresholds are explicit and deterministic:

* hash mismatch → warning;
* any dependent run stale → visible stale state;
* station disagreements are unresolved evidence warnings;
* no automatic model acceptance threshold, because no retraining occurs.

User-configurable thresholds and alert subscriptions are future work.

## Limits

* No source polling or scheduled retrieval.
* No model performance drift detection for the economic study.
* No risk-thesis language monitoring; saved applications are not substantively evaluated.
* No multi-user review ownership or acknowledgement workflow.
* No push notifications.
