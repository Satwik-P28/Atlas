# ADR 0007 — Phase 1 scope boundaries and the Phase 2 contract

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

Atlas is intended to become a Financial Intelligence Operating System with a compiler,
simulation, research workflows and a terminal. Phase 1 is only the data and evidence
layer. The risk in a project of this ambition is twofold: build the whole platform badly,
or build a narrow core that later phases cannot use.

## Decision

### What Phase 1 owns

* Evidence records, availability semantics, revisions, provenance.
* Entity identity (issuer, security, listing, ticker, identifier).
* SEC ingestion and normalisation.
* Market bars, calendars, corporate actions, adjustment mathematics.
* Dataset validation, migrations, operational logging.

### What Phase 1 deliberately does not build

| Excluded | Reason |
|---|---|
| Financial-Economic Compiler | Requires stable evidence handles first; specified, not built. |
| Dependency graph service | Lineage data is captured now (`transformation_lineage`); the graph engine is Phase 2. |
| Model registry / simulation | Out of scope; depends on typed datasets. |
| Backtesting engine | Look-ahead prevention is provided at the data layer; the engine is Phase 2. |
| Terminal UI | A CLI demonstrates every capability; UI is deliberately absent. |
| AI/LLM features | Optional by design; nothing in Phase 1 depends on one. |
| Live market-data vendor | Licensing constraints; CSV/Parquet import plus a provider-agnostic store instead. |

### Boundaries that make Phase 2 possible

1. **Stable JSON shapes.** Every CLI result (`--json`) and every kernel result has a
   documented dict form (`SelectionResult.to_dict`, `ProvenanceReport.to_dict`,
   `AdjustedSeries.to_dict`). Phase 2 can consume them without importing internals.
2. **Evidence handles.** A selected fact carries `evidence_id`; a derived fact carries
   `lineage.inputs[].evidence_id`. That is the join key for "which computations depend on
   this evidence".
3. **Versioned policy ids.** `atlas.select.point_in_time.v2`,
   `atlas.derived.gross_profit.v1`, `atlas.normalize.magnitude_outflow.v1`. A result is
   interpretable years later because the policy that produced it is named.
4. **Explicit knowledge time.** `as_of` + `mode` travel with every query, so Phase 2 does
   not need to reimplement look-ahead prevention.
5. **Typed units end-to-end.** A compiler can reject `USD + shares` at its own boundary
   using the stored `unit_kind`/`currency`.
6. **No hidden state.** The database plus fixtures reproduce every result; no service, no
   cache, no LLM.

### Rules Phase 2 must follow

* Never write evidence rows directly; go through `EvidenceKernel.ingest`, which enforces
  identity, supersession and validation.
* Never derive a value without recording `derivation_kind`, `derivation_rule` and the
  input `evidence_id`s.
* Never present a reconstruction without its completeness/exclusion metadata.
* Never merge securities by ticker; use the master and honour ambiguity.
* Never adjust an adjusted series; ask for raw and derive.

The full interface specification is in [../PHASE2_CONTRACT.md](../PHASE2_CONTRACT.md).

## Consequences

* Phase 1 is verifiable in isolation: 186 offline tests, an executable demo, measured
  benchmarks.
* Some requirements are satisfied "as a contract" rather than as code (compiler,
  dependency graph). This is stated explicitly in the report rather than implied.
* The one requirement that is *not* met in code is a live external market-data adapter;
  the reasoning and the ready hook points are documented as technical debt.
