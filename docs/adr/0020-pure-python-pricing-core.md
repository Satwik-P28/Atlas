# ADR 0020 — Pure-Python pricing core with independent tests

**Status:** accepted (Phase 5)

## Context

QuantLib, ORE, NumPy, SciPy, CVXPY and pandas are not installed. Adding a heavy dependency
without a reproducible install would make the finance claims unverifiable. The scoped
calculations are small: one curve, one bond schedule, one option, three assets.

## Decision

Implement curve bootstrap, bond analytics, BSM and small active-set optimization in pure
Python. Test them against analytical identities, manual cash-flow calculations, known BSM
reference values and finite differences. Do not claim a QuantLib/ORE integration.

## Consequences

The code is readable, dependency-free and reproducible. It is slower and deliberately
limited (≤ 8 optimizer assets). A future adapter may replace it only behind the same
operators/contracts and must be independently validated.
