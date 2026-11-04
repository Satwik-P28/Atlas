# Financial-Economic Compiler architecture

## Stages

1. **Specification** — `atlas.model.v1`, authored as equations, a graph, or the SDK.
2. **Parse/validate** — JSON shape, identifiers, arity, output references. Equations are
   parsed with Python `ast` and an allowlist; no `eval` or `exec`.
3. **Financial semantics** — resolve `FinType`s, currencies, temporal kinds and operator
   contracts.
4. **Typed IR** — canonical nodes (`atlas.fec.ir.v1`) with stable ids, inputs, params and
   inferred type.
5. **Dependency analysis** — deterministic Kahn topological order, cycle and missing
   dependency diagnostics.
6. **Execution plan** — ordered entries with operator versions and types.
7. **Execution** — `ExecutionEngine`; Decimal arithmetic, node cache, limits.
8. **Evidence/audit** — canonical spec, fingerprint, input snapshot, trace, operator
   versions, evidence ids and declared assumptions.

## Why this is a compiler, not an evaluator

- User input is translated into a typed intermediate graph before any arithmetic.
- Type inference is a separate stage and can reject the program before execution.
- Dependency analysis determines ordering and cacheable subgraphs.
- Operators are versioned implementations selected through a registry.
- The same canonical specification is executed by equations, graph, SDK and the DCF.

## Extension boundaries

`OperatorSpec` is the stable compute interface. Future vectorised, DuckDB, PyTorch,
QuantLib or simulation backends can implement operators/capabilities without changing
the model document. Execution boundaries for strategies and simulations are reserved in
`docs/PHASE4_CONTRACT.md`. No future backend is installed in Phase 3.

## Security

Model payloads cannot execute Python, SQL, shell or dynamic imports. Custom Python
operators are not exposed through the API. The equation grammar supports arithmetic,
numeric literals, declared names and `abs/min/max/sum/mean/growth/npv` only.
