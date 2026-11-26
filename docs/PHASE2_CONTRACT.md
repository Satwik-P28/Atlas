# Phase 2 integration contract

Phase 1 owns the trustworthy data and evidence layer. Phase 2 (models, the
Financial-Economic Compiler, dependency tracking, research workflows, the terminal) must
consume it through these interfaces rather than reaching into tables.

Everything below exists today unless explicitly marked **proposed**.

---

## 1. Read interface

### 1.1 Point-in-time facts

```python
from atlas.evidence import EvidenceKernel, AsOfMode

kernel = EvidenceKernel(db)
result = kernel.as_of(
    entity_id="ISS-CIK0000320193",
    as_of="2024-06-01T00:00:00Z",
    mode=AsOfMode.PUBLIC_AVAILABLE,   # or ATLAS_INGESTED
    concepts=["revenue", "net_income"],
    statement=None,                    # or "income" | "balance" | "cashflow"
    include_unknown=False,
    limit=None,
    offset=0,
)
```

`result` (`SelectionResult`) carries:

| Field | Meaning |
|---|---|
| `facts[]` | selected versions with value, unit, period, `evidence_id`, source element, accession, availability, derivation kind/rule |
| `mode`, `policy` | time semantics and selection policy id (`atlas.select.point_in_time.v2`) |
| `completeness` | `complete_for_query` / `partial: …` / `incomplete: …` |
| `excluded_not_yet_available` | candidates that existed but were not available at `as_of` |
| `excluded_unknown_availability` | candidates with unevidenced timing (excluded) |
| `contradictions[]` | same instant, different values, with evidence ids |
| `truncated` | pagination signal |

`result.to_dict()` is the stable JSON form (used by `atlas --json facts`).

### 1.2 Provenance

```python
report = kernel.provenance(evidence_id)      # ProvenanceReport
report.to_dict()["narrative"]                # human-readable X-Ray steps
report.to_dict()["revision_chain"]           # all versions + supersession edges
report.to_dict()["derived_inputs"]           # input evidence ids for derived values
```

### 1.3 Identity

```python
master = SecurityMaster(db)
master.resolve_ticker("FB", as_of="2021-06-01")   # Resolution: candidates + confidence + reasoning
master.security_profile(security_id)               # listings, tickers, identifiers, relationships
master.issuer_profile(cik="320193")
```

`Resolution.confidence ∈ {confirmed, probable, ambiguous, none}`. Phase 2 must treat
`ambiguous` as a hard stop, not a hint.

### 1.4 Market data

```python
bars = BarStore(db).query(security_id, "XNAS", "2019-01-01", "2023-12-31")  # raw only
series = split_adjust(bars, actions, knowledge_as_of=..., reference_date=...)
tr = total_return(bars, actions, knowledge_as_of=...)
series.to_dict()          # bars + factors + actions_applied + actions_withheld + warnings
```

`total_return_index` is an index, not a price. Do not relabel it.

---

## 2. Write interface

Phase 2 may create evidence **only** through the kernel:

```python
from atlas.evidence import EvidenceRecord, DerivationKind, lineage_step

record = EvidenceRecord.build(
    entity_id=..., entity_kind="issuer", concept="gross_profit",
    source_id="model-run-<id>",                 # a registered source
    unit="USD",
    availability=availability_from_instant(run_time, "model.run_completed"),
    period=ReportingPeriod(end=..., start=...),
    value=Decimal("40"),
    derivation_kind=DerivationKind.DERIVED_CALCULATION,
    derivation_rule="atlas.derived.gross_profit.v1",
    lineage={
        "rule": "atlas.derived.gross_profit.v1",
        "steps": [lineage_step("subtract", detail="revenue - cost_of_revenue")],
        "inputs": [
            {"evidence_id": rev_id, "concept": "revenue", "value": "100", "unit": "USD"},
            {"evidence_id": cost_id, "concept": "cost_of_revenue", "value": "60", "unit": "USD"},
        ],
    },
    quality="verified", verification="unchecked",
)
kernel.ingest(record)
```

Rules:

1. Never `INSERT INTO evidence` directly — the kernel enforces identity, supersession and
   validation.
2. Never omit `derivation_rule` or input `evidence_id`s for a computed value.
3. Never mark a computed value `quality="verified"` unless it has been independently
   reproduced.
4. Model outputs are **estimates or derived calculations**, never `source_observation`.
5. Register a source per run (`SourceRegistry.ensure_custom`) so provenance is complete
   and model-generated values are indistinguishable from vendor data only by inspection
   of `source.kind`.

---

## 3. Dependency tracking (implemented in schema v2)

"Which computations depend on this evidence?" is answered by a persistent reverse index
added in migration 002. It is a materialisation of lineage already stored on derived
evidence records, not a new concept, and it is owned by `atlas.dependencies.DependencyIndex`
(see ADR 0010).

The tables are:

```sql
CREATE TABLE computation (
    computation_id   TEXT PRIMARY KEY,
    rule_id          TEXT NOT NULL,         -- e.g. atlas.derived.free_cash_flow.v1
    output_evidence  TEXT NOT NULL REFERENCES evidence(evidence_id),
    as_of            TEXT,                  -- knowledge time used
    mode             TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE computation_input (
    computation_id   TEXT NOT NULL REFERENCES computation(computation_id),
    evidence_id      TEXT NOT NULL REFERENCES evidence(evidence_id),
    role             TEXT,                  -- 'revenue', 'cost_of_revenue', ...
    PRIMARY KEY (computation_id, evidence_id, role)
);
CREATE INDEX idx_computation_input_evidence ON computation_input (evidence_id);
```

```python
from atlas.dependencies import DependencyIndex

index = DependencyIndex(db)
index.record(rule_id="atlas.derived.gross_profit.v1",
             output_evidence_id=derived_id,
             inputs=[(revenue_id, "revenue"), (cost_id, "cost_of_revenue")])

index.dependents(revenue_id)             # computations that consumed it
index.transitive_dependents(revenue_id)  # depth-tagged closure
index.stale([revenue_id])                # inputs since superseded
index.impact(revenue_id)                 # stable dict for a terminal
index.integrity()                        # dangling inputs / non-derived outputs
```

Kernel ingestion records the computation automatically for a derived record whose lineage
names its inputs; `index.backfill()` indexes records written before schema v2. Staleness
means "an input was superseded, or is gone" — a re-assertion of the same value does not
invalidate anything. The compiler is expected to call `stale()` after ingesting new
evidence and recompute only the affected outputs.

---

## 4. Dataset construction for models

```python
# Phase 2 builds typed inputs from Phase 1 reads.
panel = build_panel(
    entities=[issuer_id],
    concepts=["revenue", "net_income"],
    period="FY",
    knowledge_time="2024-06-01T00:00:00Z",
    mode="public_available",
)
```

Required properties for any such builder (enforced by the kernel, not by the builder):

* every cell resolves to exactly one `evidence_id` or is explicitly `missing`;
* units are homogeneous per column, with `unit` and `currency` exposed;
* periods are explicit (`period_start`, `period_end`), never inferred from row order;
* the result records the `as_of` and `mode` it was built with.

---

## 5. Stable identifiers and versioning

| Contract | Value | Change policy |
|---|---|---|
| Schema version | `1` (`schema_migration` table) | append-only migrations; never edit a released migration |
| Selection policy | `atlas.select.point_in_time.v2` | new id for any semantic change; old results remain interpretable |
| Derivation rules | `atlas.derived.<concept>.v1` | new suffix for a changed formula |
| Normalisation rules | `atlas.normalize.magnitude_outflow.v1` | id change required |
| Internal ids | prefixed, deterministic | uuid5 namespace is part of the on-disk contract |
| Result JSON | `to_dict()` shapes documented above | additive changes only within v1 |

---

## 6. What Phase 2 must not do

* Bypass the kernel or write `evidence` rows directly.
* Present a value without its `evidence_id` (X-Ray must always be reachable).
* Present an as-of reconstruction without `completeness` and exclusion counts.
* Merge securities by ticker symbol.
* Adjust an already-adjusted series, or label a total-return index as a price.
* Treat `availability unknown` as available, or invent a timestamp.
* Convert between currencies implicitly.
* Hide an ambiguous identity resolution behind a "best match".

---

## 7. Known gaps Phase 2 should close first

1. Dimensional (segment) facts, needed by any serious fundamental model.
2. A reverse dependency index (§3) and invalidation on new evidence.
3. Model-run provenance: a registered source per run plus reproducible environment capture.
4. Streaming ingestion contracts (bars and economic observations arriving continuously).
5. Columnar export/analytics path for whole-market panels (see ADR 0003).
