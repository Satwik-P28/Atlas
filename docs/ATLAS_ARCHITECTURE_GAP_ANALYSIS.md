# Atlas architecture gap analysis

This document distinguishes code that exists from architecture that is only planned. It
was written from the repository at `481cd58` (schema 13, 108 Python modules, ~39,500
lines) without the master specification, which is absent. Nothing here is a
master-spec conformance claim.

## 1. Inventory (measured)

| Package | Files | Lines | Responsibility as implemented |
| --- | ---: | ---: | --- |
| `atlas.core` | 6 | 1,648 | ids, units, temporal semantics, concepts, errors |
| `atlas.storage` | 6 | 1,862 | SQLite, migrations (13), sources, data-quality log |
| `atlas.ingestion` | 8 | 2,610 | SEC client/parsers, market CSV, bounded transport |
| `atlas.entities` | 2 | 704 | issuer → security → listing → ticker resolution |
| `atlas.evidence` | 4 | 1,763 | evidence kernel, point-in-time selection, provenance |
| `atlas.market` | 5 | 1,373 | sessions, bars, revisions, corporate actions |
| `atlas.finance` | 4 | 1,038 | ratios, curves, bond/option pricing primitives |
| `atlas.fec` | 9 | 2,314 | model IR, compiler, operator registry, runtime |
| `atlas.quant` | 7 | 1,884 | features, lab, simulator, vectorised previews |
| `atlas.institutional` | 5 | 1,399 | portfolios, risk, walk-forward validation |
| `atlas.learning` | 11 | 2,225 | dataset eligibility, features, experiments, audit |
| `atlas.economic` | 7 | 2,425 | economic data fabric, models, scenarios |
| `atlas.research` | 12 | 7,880 | equity research, banks, prices, regulatory, FR Y-9C, packages |
| `atlas.applications` | 7 | 2,206 | application packages, install/execute/fork, domain packs |
| `atlas.terminal` | 9 | 5,235 | HTTP API, read models, workspaces, indicators, screener |
| top level | 6 | ~2,000 | CLI, demo, reconciliation, validation, dependency index |

Largest single modules: `research/equity.py` (2,473), `terminal/api.py` (1,947),
`terminal/read_models.py` (1,552), `research/prices.py` (1,233),
`research/institutions.py` (1,184), `storage/migrations.py` (1,177).

## 2. Dependency direction (as implemented)

```
core ──► storage ──► entities / evidence / market / finance
                  └─► ingestion (SEC, CSV) ──► evidence
core ──► fec ──► quant / learning
core ──► economic ──► applications
evidence + market + fec ──► research ──► applications ──► terminal
```

Two rules hold in the code: `core` imports nothing from Atlas, and only `ingestion`
talks to the network. `applications` and `terminal` are the only consumers of the
research layer, and `terminal` is the only HTTP surface.

## 3. Named systems versus actual code

The mission names eight principal systems. Four exist under those descriptions; three
exist under different names; one has no implementation at all.

| Named system | Actual code | State |
| --- | --- | --- |
| Temporal Evidence Kernel | `atlas/evidence` (+ `storage`, `ingestion`) | implemented, locally tested, independently audited arithmetic downstream |
| Financial-Economic Compiler | `atlas/fec` (IR, compiler, operator registry, runtime) | implemented for the canonical `atlas.model.v1` graph; not a general-purpose language |
| Model Forge | no dedicated package; model templates live in `applications/sdk.py`, `quant/lab.py` | **partial / experimental** — templates and lab runs exist, no forge pipeline |
| Quant Lab | `atlas/quant` + terminal Lab surface | implemented for features/simulation; not a strategy research OS |
| Learning Brain | `atlas/learning` | implemented as dataset eligibility + experiments + audit; no autonomous learning loop |
| Economic Intelligence | `atlas/economic` | implemented for the EIA/NOAA case study; not a general economic-intelligence platform |
| Research OS | `atlas/research` (no module or document uses the name) | **partial** — research workflows, packages and institutions exist; no OS-level scheduling, memory or multi-analyst layer |
| UROS | absent from source (one documentation mention) | **vision only** |

`docs/ATLAS_NEXT_PHASE_DEPENDENCIES.md` records the ordering implied by this table.

## 4. Duplication and inconsistent contracts

1. **Market-price semantics are implemented three times.** `research/prices.py` (import,
   observations, analysis), `terminal/read_models.py` (display summary) and
   `research/equity.py` (valuation multiples) each read the same rows. Phase 9.2.4 found
   two real defects caused by exactly this: `close` was a string on one path and a number
   on another, and the unavailable-analysis payload dropped keys on one path only.
   *Recommendation:* one typed market-evidence value object consumed by all three.
2. **Rights decisions are re-derived in more than one place.** `applications/rights.py`
   owns the policy, but `research/equity.py` independently checks source rows before
   packaging. The rules agree today; they are two implementations of one policy.
3. **Presentation logic lives in two modules.** `terminal/api.py` and
   `terminal/read_models.py` both shape issuer, metric and provenance payloads. The API
   is 1,947 lines; splitting read-only shaping from route wiring is the highest-value
   structural change and carries no contract risk if response shapes are pinned by tests.
4. **`research/equity.py` performs five jobs**: point-in-time selection, DCF, bank
   residual income, packaging/report rendering and peer comparison. It is the module most
   likely to be rewritten by the next phase, and the hardest to test in isolation.
5. **Two point-in-time selection implementations** — Python grouping (`evidence/kernel.py`)
   and SQL window functions (`evidence/selection_sql.py`) — are deliberate, documented in
   ADR 0009 and proven equivalent by a differential test. Not duplication to remove.
6. **Two execution paths for models**: the canonical FEC runtime and the economic
   scenario service. Both are allowlisted; they do not share an execution contract.

### 4.1 Resolved in Phase 9.2.6

`src/atlas/market/evidence.py` now owns observation selection. The three independent price
queries (`prices._selected_row`, two `BarStore.latest_close` call sites and the inline equity
coverage query) were replaced by `select_price` / `latest_observation`, and the terminal
routes were left untouched because no route changed shape. The remaining untyped boundary is
not market evidence but the FEC value tuple; the operator registry is typed
(`FinType`-checked) and now has a compatibility policy, so that boundary is narrower than it
appeared.

## 5. Foundational capabilities versus downstream features

**Foundational (everything else depends on them):** identifiers and units
(`core`), temporal semantics and point-in-time selection (`core`, `evidence`),
raw-document storage (`storage`, `ingestion`), price revisions (`market`), and the
operator registry (`fec`).

**Downstream (safe to change without touching evidence):** equity research, bank
valuation, regulatory reconciliation, packages, terminal read models, workspaces,
screeners, learning experiments, economic scenarios.

The boundary is real: no downstream module writes SQL against `evidence` directly, and
`evidence` has no knowledge of valuation or presentation.

## 6. Reusable components for future domains

- `core.ids`, `core.units`, `core.temporal` — domain-neutral, already reused by every
  package.
- `evidence` kernel and provenance — reusable for any source with availability semantics.
- `storage.migrations` patterns — append-only, transactional, version-gated.
- `applications.contracts` — content-addressed, declarative package format; the rights
  engine and ZIP validation are not finance-specific.
- `terminal.workspaces` — declarative layout schema, explicitly designed as the output of
  a future workspace compiler.
- `fec` operator registry — new operators register with versions; no recompilation of
  historical results as long as old versions are retained.

## 7. Missing contracts that would force a later rewrite

1. **A typed market-evidence interface.** Today three callers share dicts; the 9.2.4
   defects came from that. This is the single highest-risk missing contract.
2. **A model/operator deprecation policy.** `atlas.model.v1` and operator versions are
   checked, but nothing states how long a version must remain executable. Historical
   replay depends on it.
3. **A capability-to-module binding for domain packs.** `CAPABILITIES` is a string set;
   there is no contract saying which module may satisfy a capability, so a pack's
   declarations are not yet enforceable beyond metadata.
4. **An evidence-handle type for model inputs.** `docs/PHASE2_CONTRACT.md` describes it;
   the runtime passes ids and dicts. A compiled model cannot today be type-checked
   against evidence kinds without a runtime lookup.
5. **A research-object schema registry.** Objects carry `schema` strings and are
   validated per writer; there is no central version/compatibility table.
6. **A job/replay execution contract.** Replay is synchronous and request-scoped. Any
   scheduled or long-running research would need one, and inventing it later would touch
   every service.

## 8. What this analysis does not claim

It is not a master-specification conformance assessment. It does not propose creating
modules to complete a diagram: the four "partial/vision only" systems stay described as
such until the genuine specification states what they must do.

### Phase 9.2.7 update — remaining gaps

- **Introducing gap: Markets Overview scaling.** The overview now builds one canonical
  series per security. Measured at 1,000 securities: ~7.6 s cold, 24 SQL statements per row.
  The per-point identity cost was removed; the remaining cost is per-security series
  construction. A bulk projection of the same contract is the next step, not a rewrite.
- **Introducing gap: route module size.** The market group is extracted; ~90 routes still
  live in `terminal/api.py`. Each further group should move only with its own contract test.
- **Persisting gap: master specification.** Still absent from the workspace.
- **Persisting gap: unauthenticated API.** The exposure guard makes a non-loopback bind
  explicit; it does not add authentication.
