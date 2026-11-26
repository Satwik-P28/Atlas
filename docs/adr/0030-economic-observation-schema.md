# ADR 0030 — Economic observations extend the evidence discipline

Status: accepted.

## Context

Phase 7 needs nonfinancial observations (weather, electricity demand) without treating them as
financial facts or starting a second evidence platform. Existing bars and fundamentals cannot
carry station identity, revision sequence or retrieval-proxy availability.

## Decision

Add additive schema-9 tables for economic series and observations. An observation retains
series, source, period, observed_at, availability time/precision/basis, vintage, revision
sequence, supersedes pointer, numeric value, unit, quality, data class, content hash and
metadata. Source rights and timing remain in the source registry.

## Consequences

* The Temporal Evidence Kernel remains the authority for temporal semantics.
* As-of exclusion is explicit and testable.
* A revision adds a row; history is never overwritten.
* The schema does not claim historical publication vintage merely because a current archive
  can be downloaded.
* Additional source families need their own units/rights declarations, not schema forks.
