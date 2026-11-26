# Atlas next-phase dependencies

This is a dependency map, not a roadmap commitment. Each item states what must exist
before dependent work can start and whether it is verifiable today. Phase 10 features are
**not** started.

## 0. Gates that precede everything

| Gate | Blocks | State |
| --- | --- | --- |
| Genuine `ATLAS_MASTER_SPEC.md` (155,419 bytes, `e54c5973…4ba5c9`) | clause-level traceability, ICB-01…20, the 34-section review | **blocked** (file absent) |
| Actions read access for the pushed SHA | hosted-CI acceptance | **blocked** (no credential) |
| Authorization for historical-data remediation | any history rewrite | **not requested** |

No later item may be described as specification-conformant until the first gate clears.

## 1. Foundations already satisfied (depend on nothing new)

| Capability | Evidence |
| --- | --- |
| Immutable raw documents with hashes | schema `raw_document`; 26,440 evidence rows in the reference DB |
| Point-in-time selection with stated policy | `atlas.select.point_in_time.v2`; differential Python/SQL test |
| Deterministic identifiers | uuid5 anchors; determinism tests |
| Market observation identity and revision pinning | `observation_id`, replay tests, browser B2–B6 |
| Declarative package format with rights enforcement | package contract tests, clean-install reproduction |
| Bounded, complete SEC transport | 9.2.5 fixes + adversarial tests |

## 2. Immediate dependencies (next work that does not need the specification)

### 2.1 Typed market-evidence interface

* **Needs:** nothing new; schema 13 and `research/prices.py` observations.
* **Why first:** three consumers currently share untyped dicts, which produced two real
  defects in 9.2.4 and one class of drift risk. Every price-dependent feature inherits it.
* **Acceptance:** one value object, all three consumers migrated, response shapes
  unchanged (pinned by the existing API tests), browser journeys still green.

### 2.2 Split presentation shaping from route wiring

* **Needs:** 2.1 for the price fields; response-shape tests as the safety net.
* **Why:** `terminal/api.py` (1,947 lines) is the largest untested-by-unit surface;
  refactoring later, after more endpoints exist, costs more.
* **Acceptance:** no route behaviour change; OpenAPI diff empty.

### 2.3 Model/operator deprecation policy

* **Needs:** the list of shipped `atlas.model.v1` operators and their versions (exists in
  `fec/operators.py`).
* **Why:** replay claims are only honest while old operators remain executable.
* **Acceptance:** a written retention rule plus a test that every persisted run's operator
  versions remain resolvable.

### 2.4 Research-object schema registry

* **Needs:** inventory of object schemas currently written (`research`, `quant`,
  `economic`, `applications`).
* **Why:** packages embed objects; an unregistered schema change silently breaks reopen.
* **Acceptance:** central registry with versions, read paths validated against it.

### 2.1 Delivered in Phase 9.2.6

The typed market-evidence contract, the migration of its consumers, the single rights
decision contract, the explicit non-loopback acknowledgement and the operator-version
compatibility policy are implemented. What remains from the original list is the split of
presentation shaping out of `terminal/api.py`: the contract made it safe to do, but it was
not required to close the duplication and is not included in this checkpoint.

## 3. Dependencies that require the specification

| Area | Depends on | Cannot start because |
| --- | --- | --- |
| Clause-level conformance matrix | genuine spec | mapping invented requirements is worthless |
| ICB-01…ICB-20 benchmark mapping | genuine spec | only ICB-04 and ICB-09 are named anywhere in the repo |
| UROS | genuine spec | no source, no design document, one passing mention |
| Model Forge pipeline | genuine spec + 2.3 | current templates are not a forge |
| Research OS scheduling/memory | genuine spec + 2.4 | no job contract exists |
| General-domain packs | capability binding contract (§7.3 of the gap analysis) | capabilities are unbound strings |
| Multi-user / hosted terminal | authentication design | explicitly out of scope today; requires a threat model first |

## 4. Recommended order

1. Obtain and verify the master specification (gate 0).
2. Land 2.1 (typed market evidence) — smallest change with the widest correctness effect.
3. Land 2.2 and 2.3 while writing the clause matrix; both are independent of it.
4. Produce the clause matrix and ICB mapping from the verified spec.
5. Only then choose the next feature phase, using the matrix's `blocked` and `partial`
   rows as the backlog.

## 5. Explicit non-dependencies

- The terminal UI does not depend on the specification to keep working; its acceptance is
  the browser journeys.
- Bank valuation arithmetic does not depend on any pending item; it is audited 29/29 and
  must not be changed to fit a future narrative.
- Clean installation does not depend on hosted CI; the local rehearsal is the evidence,
  and the CI gate stays separately blocked.

## Phase 9.2.7 dependency update

The canonical series contract (`MarketSeriesSelection`, `series_changes`) is now the only
way a consumer reads more than one observation. Any new market consumer — a chart, a
screener column, a risk factor — depends on it rather than on `BarStore.query`, which stays
a storage primitive for range/coverage work.

Before Phase 10, the measured dependency is bulk projection of the overview: the contract is
correct at 1,000 securities but slow, and the same policy can be applied to many securities
in one query with a differential test against the per-security result.
