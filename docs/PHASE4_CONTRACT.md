# Phase 4 contract (proposed, not implemented)

Phase 3 deliberately stops before strategies, backtests, simulations and institutional
pricing.

## Required before Phase 4

- An execution boundary type distinct from stateless financial arithmetic:
  `Strategy`, `Simulation`, `Workflow`, `Monitor`, `Thesis`.
- Declared state, time-step semantics, data partitions, transaction costs and fills.
- Reproducible experiment manifests including universe snapshots and code versions.
- Vectorised/SQL execution adapters behind the existing `OperatorSpec` capability
  interface, with explicit precision and backend identity in cache keys.
- Portfolio and risk types (`Weight`, `Return`, `Covariance`, `Exposure`) with the same
  dimensional discipline as `Money`/`Price`/`Shares`.
- Sandboxed third-party operator loading; untrusted Python execution remains disabled.

## Non-goals for Phase 4 foundation

Do not implement QuantLib, GPU training, Monte Carlo at scale or an economic digital
twin merely to increase feature count. Establish typed boundaries and reproducibility
first.

## Compatibility

`atlas.model.v1`, `atlas.fec.ir.v1`, `atlas.research_object.v1` and the evidence kernel
remain authoritative. New execution kinds require additive schemas/migrations and
independent validation.
