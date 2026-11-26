# Phase 7 readiness

Status: **implemented vertical slice; schema 9; real public data; partial institutional
readiness.** The genuine master specification is absent, historical vintage is unavailable,
and general OSINT/entity resolution is not implemented. The flagship workflow is functional.

## Acceptance gates

| # | Gate | Status | Evidence / limitation |
|---:|---|---|---|
| 1 | Existing regression suites pass | **Pass** | 372 backend, 4 frontend, production build |
| 2 | Master spec imported or absence documented | **Pass — blocker documented** | v1.2.0 absent; no substitute invented |
| 3 | Two economically meaningful public source families | **Pass** | EIA-930 and NOAA GHCN-Daily |
| 4 | Provenance, rights, units, temporal limitations correct | **Pass** | Manifest, source registry, retrieval-proxy basis |
| 5 | Graph contains source-backed or inferred relationships | **Pass** | 6 observed, 1 inferred, 5 hypothetical edges |
| 6 | Contradictory claims preserved and reviewable | **Pass** | 32.8 vs 35.6 °C; unresolved; both claims |
| 7 | Association distinguished from causal estimate | **Pass** | `not_identified`; design refusal tested |
| 8 | Scenario reuses FEC | **Pass** | `atlas.fec.compiler.v1`; equality assertion |
| 9 | Meaningful uncertainty and sensitivity | **Pass** | 2,000 draws, separate sources, three grids |
| 10 | Complete weather-to-electricity workflow | **Pass** | 365 real days → association → scenario → finance |
| 11 | Financial stage labeled observed vs hypothetical | **Pass** | Hypothetical company/facility/load/contract |
| 12 | Replay invents no forecast or vintage | **Pass** | 2023 cutoff returns insufficient evidence |
| 13 | Saved application restored within archival limits | **Pass** | URO application; exact 2026 replay |
| 14 | Source updates invalidate dependent results | **Pass** | Revision marks run stale; old row kept |
| 15 | ICB-04 and ICB-09 independently evaluated | **Partial** | ICB-04 pass for narrow slice; ICB-09 limited to deterministic public-data claims |
| 16 | End-to-end UI and regressions pass | **Pass** | Browser journey desktop/mobile; screenshots |
| 17 | Rights and privacy protections intact | **Pass** | Public-domain sources; no private data; no restricted bytes |
| 18 | Benchmarks use measured results | **Pass** | `phase7_benchmarks.json`, browser timings |

## Master specification blocker

`ATLAS_MASTER_SPEC.md` v1.2.0 is not in the repository, and no external path was provided to
this environment. The required import therefore could not be performed. This record explicitly
identifies that absence rather than fabricating a shortened file. The Phase 6 contract,
`PHASE7_CONTRACT.md`, this Phase 7 set and the ADRs are the in-repo authority until the genuine
document is supplied.

## Implemented

* Schema 9 economic series, observations, entities, edges, events, claims, conflicts and
  research analyses, scenarios, dependencies and alerts.
* Real public EIA/NOAA ingestion, derived fixture, manifest and rights.
* As-of panel with retrieval-proxy availability and explicit refusal of unsupported cutoffs.
* Evidence graph with provenance, rights and observed/inferred/hypothetical labels.
* Claim ontology and preserved station disagreement.
* Chronological weather-demand experiment with seasonal and degree-day models.
* Causal policy plus validated DiD and ITS implementations.
* Scenario engine with correlated coefficient draws, sensitivity and extrapolation.
* FEC financial mapping, margin and cost impacts.
* Universal Research Object application persistence.
* Deterministic Sentinel, correction revisions and dependency invalidation.
* Economic Lab UI, API, tests, benchmark and docs.

## Partial

* **ICB-09 OSINT:** conflict and claim handling are real, but there is no document crawler,
  entity resolution, duplicate-article clustering or GDELT feed. Do not call this a general
  OSINT platform yet.
* **Historical reproduction:** exact reconstruction from the 2026 archive works; as-issued
  history and pre-event forecasts do not.
* **Causal research:** two identified estimators exist, but the flagship is observational and
  no natural experiment was found.
* **Performance:** measured on a 365-day panel; no national multi-year or concurrent-user
  evidence.
* **Monitoring:** manual deterministic refresh, not a scheduler.

## Unsupported

Historical vintages, archived weather forecasts, licensed company operating data, facility
registries, supplier contracts, forward power curves, live news, event markets, real-estate
underwriting, scheduled monitoring, multi-user auth, live orders and automated deployment.

## Why the flagship is still honest

The study reports a **negative R²** and a **positive mean error** despite a positive RMSE skill
score. It labels the relationship `not_identified`, keeps a source conflict unresolved, calls
the firm hypothetical, refuses a 2023 historical replay, and reports no automatic model
promotion. The data, arithmetic and limitations are independently testable.

## Phase 8 prerequisites

1. Supply the genuine master specification and reconcile its event/OSINT/domain contracts.
2. Acquire a lawful historical vintage and archived forecasts; otherwise keep replay
   non-claiming.
3. Build a real document ingestion/entity-resolution pipeline with source de-duplication.
4. Validate a defensible natural experiment before using causal language.
5. Add observed company/facility/contract evidence before any firm-specific financial claim.
6. Implement a scheduler only with explicit monitoring policy and user control.
