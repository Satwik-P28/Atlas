# ADR 0010 — Reverse dependency index for derived computations

- **Status**: accepted (Phase 1.1)
- **Date**: 2026-11-04

## Context

Every derived evidence record already carries its lineage: the rule id, the transformation
steps, and the evidence ids of its inputs. That answers *"what did this value come from?"*
— the X-Ray question.

A compiler needs the inverse: *"this filing just arrived; which derived values are now
stale?"* Scanning `transformation_lineage` JSON for every derived record cannot be indexed,
does not scale, and would put dependency logic inside the compiler rather than in the
evidence layer that owns provenance.

## Decision

Add two tables in migration 002 (schema v2) and an owning module
(`atlas/dependencies.py`):

```sql
CREATE TABLE computation (
    computation_id   TEXT PRIMARY KEY,
    rule_id          TEXT NOT NULL,
    output_evidence  TEXT NOT NULL UNIQUE REFERENCES evidence(evidence_id),
    knowledge_as_of  TEXT,
    mode             TEXT,
    engine           TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE computation_input (
    computation_id TEXT NOT NULL REFERENCES computation(computation_id),
    evidence_id    TEXT NOT NULL REFERENCES evidence(evidence_id),
    role           TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (computation_id, evidence_id, role)
);
CREATE INDEX idx_computation_input_evidence ON computation_input (evidence_id);
```

Rules:

1. **One computation per output.** `output_evidence` is unique because a derived record is
   produced by exactly one rule application. Recomputing creates a *new* evidence record
   that supersedes the old one; the old computation remains as history.
2. **Inputs are real.** Foreign keys plus an explicit existence check reject a computation
   that names a missing input. A derived record whose lineage names an input that is not
   stored fails its whole ingest transaction rather than persisting broken provenance.
3. **Recording is automatic.** `EvidenceKernel.ingest` records the computation when a
   derived record arrives with lineage inputs. `DependencyIndex.backfill()` indexes records
   written before schema v2, so the index can be introduced on an existing database.
4. **Staleness has one definition.** A computation is stale when an input it consumed has
   since been **superseded**, or the input disappeared. A re-assertion of the same value is
   not supersession (the kernel does not supersede unchanged values either), so it does not
   invalidate anything.
5. **The index never derives.** It records and answers dependency questions. Derivation is
   the compiler's job; keeping them separate means the compiler can be replaced without
   touching provenance.

## API

```python
index = DependencyIndex(db)

index.record(rule_id, output_evidence_id, inputs=[("EV-1", "revenue"), ("EV-2", "cost_of_revenue")])
index.record_for_derived(record)         # from the record's own lineage
index.backfill()                         # -> number indexed

index.for_output(output_evidence_id)     # Computation | None
index.dependents(evidence_id)            # direct consumers
index.transitive_dependents(evidence_id) # [(depth, Computation), ...]
index.stale(evidence_ids=None)           # computations with superseded/missing inputs
index.impact(evidence_id)                # ImpactReport: direct, transitive, stale, outputs
index.integrity()                        # dangling inputs, non-derived outputs, inputless rows
```

`ImpactReport.to_dict()` is the stable shape a Phase 2 terminal can render directly.

## Consequences

* The reverse question is an indexed join (`idx_computation_input_evidence`), not a scan.
* Derived ingestion is slightly stricter: an unknown input id aborts the ingest. That is
  the correct failure mode — a derived value with unresolvable provenance is worse than no
  value.
* Untested at scale: the design assumes computations are far fewer than facts. If a
  whole-market model run produces millions of derived rows, the per-computation insert
  pattern will need batching; the schema supports it, the write path is row-at-a-time.
* A cycle (derived value consuming its own descendant) is prevented for direct
  self-reference but not for longer cycles. Staleness traversal is finite-depth (default 8)
  and returns each computation once, so a cycle degrades to truncation rather than an
  infinite loop.
