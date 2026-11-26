# Quant Lab architecture

Quant Lab is a capability of the existing Atlas runtime, not a second application.

```
evidence kernel / market bars
          │
          ▼
point-in-time FeatureEngine ──► feature_snapshot (optional)
          │
          ▼
versioned Strategy object (research_object kind=strategy)
          │                         │
          │                         └── atlas.model.v1 custom signal (Model Forge)
          ▼
chronological simulator ──► Portfolio ledger ──► reconciliation
          │
          ├── equity / drawdown / metrics / credibility report
          ├── quant_run (immutable result + fingerprint)
          └── experiment research object
                         │
                         ▼
                    Time Capsule / replay
```

## Boundaries

* **Features** read raw `bar` rows up to the requested session cutoff. They do not query
  the browser, current time or future revisions.
* **Strategies** are declarations. They cannot contain Python, SQL, JavaScript or a
  lambda; the existing research-object validator rejects those keys.
* **Model signals** use the same compiler and Decimal runtime as the financial models.
* **The simulator** owns the clock, pending target, cash, positions and corporate actions.
  A signal calculated at close is filled at the next available open.
* **Persistence** writes a run and an experiment; it never writes evidence.
* **The API** validates request types and returns structured Atlas errors.

## Main modules

| Module | Responsibility |
|---|---|
| `src/atlas/quant/features.py` | typed rolling features, cutoff, generation, snapshots |
| `src/atlas/quant/contracts.py` | strategy/experiment schemas and validation |
| `src/atlas/quant/portfolio.py` | independent cash/holdings/realized/unrealized ledger |
| `src/atlas/quant/simulator.py` | clock, signal decisions, next-open fills, metrics |
| `src/atlas/quant/vectorized.py` | close-to-close research preview (not fills) |
| `src/atlas/quant/lab.py` | strategy registry, runs, experiments, capsule, replay |
| `src/atlas/research/archive.py` | content-addressed source archives |
| `web/src/pages/Lab.tsx` | minimalist research workspace |

## Event ordering

For each stored session:

1. Apply splits effective at that session open; then dividends, so same-date share-count
   changes are ordered economically rather than by random action id.
2. Execute the pending target at the open. A target generated at the previous close
   cannot fill at that close.
3. Mark the portfolio at the close.
4. On a decision session, evaluate the signal using only closes/features available at
   that close and set the next pending target.

The benchmark uses the same bars and costs and sets its first target on the first
session, producing a buy at the second session's open.

## Extension points

Multi-instrument universes, an external engine adapter (LEAN/Nautilus), factor models,
walk-forward partitions, archived vendor vintages, and an order/auction model are
deliberately not faked. They would be additive adapters around this boundary.
