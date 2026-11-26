# ADR 0009 — Selection policy v2 and dual selection engines

- **Status**: accepted (Phase 1.1)
- **Date**: 2026-11-04

## Context

Phase 1 had one selector and one policy id (`atlas.select.point_in_time.v1`). An
adversarial audit found three things worth changing, and the brief asked for a SQL
implementation to be benchmarked against the Python one — adopting it only on evidence.

### Audit findings

1. **Double-counting in `atlas_ingested` mode.** A record whose *public availability* is
   unevidenced was fetched as a "known" candidate (its `observed_at` was within range) and
   again as an "unknown availability" candidate. It could be emitted twice, and it was
   counted as excluded even though it had been selected. Under ingestion-time semantics
   the observation time *is* the evidenced instant, so such a record must be treated as
   knowable and not reported as a gap.
2. **Contradiction adjudication ignored the revision chain.** When several records
   asserted different values with identical availability, the selector picked the
   best-quality record. If a correction had arrived with the same acceptance timestamp as
   the original, quality could select the *older* value and silently discard the
   correction. The chain is the only evidence of ordering in that situation.
3. **Quality direction was implicit.** Ties on availability were sorted by quality rank in
   an order that happened to be harmless but was not stated or tested.

## Decision

**Policy id becomes `atlas.select.point_in_time.v2`.** The ranking is now written down and
implemented identically twice:

1. lowest basis tier in the group (source observation outranks derived, estimate last);
2. latest availability at or before the instant (or `observed_at` in `atlas_ingested` mode);
3. ties: best quality, then latest ingestion order, then evidence id (deterministic);
4. if the values at the winning instant disagree: report a contradiction and adjudicate by
   **revision-chain tip**, then quality, then latest ingestion. The conflict, both values
   and the chosen record are always reported;
5. if the value did not change: return the **earliest** evidence of that value, so
   provenance points at the document that first established it (ties: best quality, then
   earliest ingestion).

Two implementations exist: `EvidenceKernel` (Python grouping) and
`evidence/selection_sql.py` (SQL window functions). They are **not** assumed to agree:
`tests/test_selection_engines.py` runs a differential comparison over four randomised
histories (values, units, tiers, qualities, precision, ingestion order), a set of
adversarial scenarios (date boundary, simultaneous corrections, backfills, unknown
availability, tier precedence) and the real Apple payload across three instants, two modes
and four statement filters.

## Benchmark result — SQL not adopted

Measured on the Apple dataset (5,737 facts), 2 vCPU, SQLite 3.45, medians of 5:

| Query | Python | SQL (correlated) | SQL (window rewrite) |
|---|---|---|---|
| All concepts, one instant | **154.6 ms** | 205.9 ms | 235.8 ms |
| Four concepts, latest | **22.4 ms** | 31.3 ms | 35.3 ms |

The SQL engine is correct (differential tests pass) but **slower**, so the default stays
`engine="python"`. The SQL path remains available (`--engine sql`,
`as_of(..., engine="sql")`) for the columnar/whole-market future, where transferring every
candidate row is the dominant cost and a set-based plan should win. That claim is untested
and is not made; it must be re-measured before adoption.

Why SQL lost here: the dataset is small enough that the Python path's cost is dominated by
row hydration rather than grouping, while SQLite pays for window partitioning plus a second
hydration pass over the winning ids. The window rewrite replaced correlated subqueries with
one pass but widened the intermediate relation, and did not help.

## Consequences

* Results record policy `v2`; a v1 result remains interpretable because it names v1.
* `atlas_ingested` results no longer report unknown-availability records as excluded, and
  gain a note explaining that public availability may precede Atlas ingestion.
* Contradictions now name the selected record (`contradictions[].selected`), so an
  adjudication is auditable rather than implied.
* Maintaining two implementations is a real cost. It is justified only by the differential
  test; if that test is ever weakened, one engine should be deleted.
