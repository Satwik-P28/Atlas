# ADR 0018: Quant run persistence, strategy registry and source archives

**Status:** accepted for Phase 4.

## Context

Strategies and experiments must use the existing Universal Research Object registry rather
than a parallel store. Runs need immutable results that can be reopened and replayed.
Reproducibility claims need durable source bytes, but vendor redistribution rights differ.

## Decision

- Strategy and experiment documents remain `atlas.research_object.v1` kinds; `quant_run`
  stores the execution result, config, reconciliation, metrics and experiment link.
- Migration 006 adds `quant_run`, `feature_snapshot`, `source_archive` and
  `source_archive_link`; no existing table is rewritten.
- Strategy identity is `name` + semver, and the registry rejects a changed spec reusing an
  existing identity.
- Source archives are SHA-256 content-addressed with provider, retrieval/publication times,
  rights, retention, parser/schema version and provenance links. Bytes are stored only when
  retention is permitted.
- The Time Capsule reports `archived`, `external_provider_only` or `no_evidence`; it never
  upgrades provider-dependent data to fully reproducible.

## Consequences

- Experiments are immutable, forkable research objects and participate in existing export
  and dependency machinery.
- Replay is a fingerprint equality check, not a re-fetch of the vendor.
- Real IBM data remains provider-dependent because vendor bytes are not bundled. This is
  visible in the Lab and capsule.
- A future bitemporal vendor store can populate the same archive tables without changing
  strategy or run contracts.

## Rejected alternatives

- Separate strategy database: breaks the research object registry and provenance.
- Store only successful runs: selection bias and no audit trail.
- Hash-only archive rows without bytes: cannot verify source content.
- Bundle Alpha Vantage payloads into the public repository: redistribution rights are not
  established.
