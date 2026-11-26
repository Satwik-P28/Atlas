# ADR 0001 — Python core with SQLite persistence

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

Atlas needs a strongly typed financial domain core, exact decimal arithmetic, careful
time semantics, SQL and dataframe interoperability, and eventually a research runtime.
The Phase 1 environment has Python 3.12 and Node available; **no Rust toolchain**
(`cargo`/`rustc` absent), and the deliverable requires a working, tested vertical slice
rather than an unverifiable design.

The specification explicitly asks to evaluate a Rust core and warns against introducing
Rust/Python interoperability for architectural appearance.

## Decision

Implement Phase 1 in Python 3.11+ with **zero runtime dependencies**:

* `sqlite3` (stdlib) for persistence;
* `decimal.Decimal` for money and quantities;
* `zoneinfo` for venue time zones;
* `urllib` for SEC HTTP (no `requests`);
* `dataclasses` + enums for domain contracts;
* `pytest` + `hypothesis` as development-only dependencies.

The domain core is written with the discipline a Rust core would require: immutability,
typed errors with stable codes, explicit invariants, and no implicit float conversions.

## Consequences

**Positive**

* Every requirement in Phase 1 is executable and testable in this environment today.
* No dependency supply-chain surface for the data path; the whole engine is auditable.
* Direct interoperability with the Python scientific stack (pandas/PyArrow/DuckDB) that
  Phase 2+ research will need — no FFI boundary to design or maintain.
* `Decimal` + canonical string storage gives exact arithmetic, which mattered more than
  compile-time types for correctness here.

**Negative**

* No compile-time type checking. Mitigated by dataclasses with slots, enums instead of
  string literals at boundaries, and a test suite that exercises the public API.
* Python throughput sets a ceiling for large-scale computation. Measured in
  `docs/BENCHMARKS.md`; the current bottleneck is ingestion I/O and SQL, not the language.
* A future Rust computational core would mean reimplementing domain types or adding an
  FFI boundary. Deferred deliberately.

## Alternatives considered

| Option | Why not now |
|---|---|
| Rust core + PyO3 bindings | No toolchain in the environment; an unverifiable core would violate "a feature counts only if it executes". Best long-term option for the compiler/simulation engine — revisit when the toolchain and a hot path justify it. |
| TypeScript/Node | Weaker decimal and typed-array numerics for this domain; SQLite story is weaker than Python's. |
| Rust for storage + Python for ingestion (split runtime) | Premature interoperability for Phase 1; doubles the surface area before the contracts are proven. |

## Follow-up

When Phase 2 profiling identifies a genuinely compute-bound hot path (not I/O), evaluate a
Rust crate for that path only, with the typed contract in `PHASE2_CONTRACT.md` as the
boundary. Do not port the evidence model for performance reasons alone: the model's value
is semantic, and it is cheap.
