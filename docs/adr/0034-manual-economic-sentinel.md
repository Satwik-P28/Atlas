# ADR 0034 — Sentinel is deterministic and user-triggered

Status: accepted.

## Context

The phase requires source revision detection and dependent-result invalidation, but the
repository has no scheduler, queue or notification runtime. Promising background monitoring
without those components would be false.

## Decision

Implement Sentinel as an idempotent manual refresh endpoint over the local SQLite database.
It compares fixture hashes, exposes dependencies, marks affected runs stale on revision,
stores alerts with deterministic IDs and always reports
`automatic_retrain: false` and `automatic_deployment: false`. Saved applications are never
rewritten.

## Consequences

* A user can inspect exactly what changed and rerun deliberately.
* Repeated refresh does not duplicate hash alerts.
* “Live monitoring” is explicitly unsupported until a scheduler and delivery policy exist.
* A future scheduler can call the same service without changing the research contract.
