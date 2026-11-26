# ADR 0023 — Small active-set optimizer instead of an uninstalled QP library

**Status:** accepted (Phase 5)

## Context

CVXPY/SciPy/OR-Tools are absent. The demonstrated universe has three assets. A general QP
dependency would be unverifiable in this environment and unnecessary for the scoped case.

## Decision

Enumerate each asset's state (zero, cap, free), solve equality-constrained KKT systems with
Gaussian elimination, and choose the feasible minimum-variance solution. Support long-only,
max weight, cash and target return. Reject turnover and sector caps rather than ignoring
them. Return explicit infeasibility and solver diagnostics.

## Consequences

The solver is transparent and independently testable for small portfolios. It does not
scale beyond eight assets and has no warm start or transaction-cost objective. A future QP
backend must preserve the same constraint and diagnostic contract.
