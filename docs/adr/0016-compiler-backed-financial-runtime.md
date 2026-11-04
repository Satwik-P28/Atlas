# ADR 0016: Compiler-backed financial runtime

**Status:** accepted for Phase 3.

## Decision

Represent financial models as a versioned, typed DAG (`atlas.model.v1`), compile them
through a staged pipeline into `atlas.fec.ir.v1`, and execute only registered operators.
Use the same graph for equations, visual models, the Python SDK and the DCF.

Materialize point-in-time issuer metrics under a key containing issuer, exact as-of,
mode, model version and evidence generation. Never let a current snapshot satisfy a
historical query.

## Consequences

- Invalid currencies, periods, stock/flow mixing and cycles fail before execution.
- Node caching can be dependency-aware and correct because the cache key includes
  canonical input values and operator versions.
- Independent mathematical validation is possible against pure reference functions.
- The graph editor remains a view; no financial calculation lives in React.
- Future backends can implement the operator interface without changing model documents.

## Rejected alternatives

- A single expression evaluator: no type analysis, weak diagnostics, no plan.
- Separate UI/Python/valuation engines: numerical drift and irreproducible results.
- Caching by model id only: stale historical answers.
- Running user Python: unacceptable without an isolation sandbox.
