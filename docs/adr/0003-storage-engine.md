# ADR 0003 — Storage engine: SQLite for Phase 1, columnar later

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

Phase 1 is local-first, must run with no paid service, must survive interruption, needs
range queries over time, and must keep append-only history. Candidate designs:

* SQLite (single file, ACID, SQL, ubiquitous);
* Parquet files (columnar, cheap scans, no transactions);
* DuckDB (columnar SQL, embedded, strong analytics);
* Postgres (server, operational cost, not local-first).

Datasets in Phase 1 are modest: Apple's full XBRL history is ~5.7k facts; daily bars for
a decade of one instrument are ~2.5k rows. Analytics-scale workloads (whole-market
panels, factor research) are future phases.

## Decision

**SQLite** is the Phase 1 system of record, with explicit pragmas:

```sql
journal_mode = WAL        -- readers never block an ingestion writer
synchronous  = FULL       -- a committed ingestion survives an OS crash
foreign_keys = ON         -- referential invariants actually hold
busy_timeout = 30000      -- concurrent processes back off instead of failing
```

Schema migrations are versioned SQL, applied inside a transaction and recorded in
`schema_migration`; the runner refuses to open a database newer than the binary.

Raw source documents are stored as BLOBs with SHA-256 so provenance is self-contained.

## Consequences

**Positive**

* Real ACID transactions: ingestion is all-or-nothing, and an interrupted run rolls back
  (verified by an acceptance test that kills ingestion mid-transaction and restarts).
* No service to operate; the database is a single file that can be copied or archived.
* SQL gives the range queries, grouping and joins that evidence selection and validation
  need, with indexes designed per access path.
* Exact decimal strings fit naturally; no float column tempts anyone.

**Negative**

* Analytical scans are slower than DuckDB/Parquet. Point-in-time selection over all
  concepts takes ~179 ms for Apple (see benchmarks) because selection is computed in
  Python over candidate rows — acceptable for research queries, not for whole-market
  panels.
* Large market history (minute bars, multi-decade panels) will outgrow one SQLite file
  and require partitioning by instrument/year.

## Deferred design (not implemented)

Bars and evidence are append-only and timestamped, so they can be exported to
Parquet partitioned by `(source, interval, year)` and queried with DuckDB for analytics,
while SQLite remains the transactional record. The `Database` wrapper isolates SQL, and
`PHASE2_CONTRACT.md` specifies a read interface rather than exposing the connection, so
this change does not leak into consumers. Parquet **import** already exists as an
optional path (`[columnar]` extra) so users can bring columnar files now.

## Alternatives considered

| Option | Verdict |
|---|---|
| Parquet only | No transactions, no cheap point updates for identity tables, painful revision chains. |
| DuckDB as primary | Excellent analytics, but weaker concurrency/transaction story for writer + reader, and no benefit at Phase 1 sizes. Planned as an optional analytics engine. |
| Postgres | Violates local-first and "no mandatory cloud services"; operational overhead for zero Phase 1 benefit. |
| Custom storage format | Reinvention with no upside; explicitly discouraged by the brief. |
