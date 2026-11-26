# Phase 5 contract

Phase 5 may build on the implemented Quant Lab boundary but must not reinterpret Phase 4
semantics.

## Stable interfaces to preserve

* `atlas.strategy.v1`, strategy registry identity (`name` + semver) and rejection of
  silent parameter reuse.
* `atlas.quant.reference.v1`: close decision, next-open fill, raw prices, explicit costs,
  single long-only instrument, independent reconciliation.
* `atlas.feature.v1` feature names, Decimal outputs, cutoff behavior and snapshot hashes.
* `atlas.quant.run.v1` result, fingerprint and Time Capsule fields.
* `atlas.research_object.v1` strategy/experiment documents and migration 006 tables.
* `atlas.model.v1` and the shared FEC operator registry.

## Required before expanding scope

1. **Multi-instrument universes** with explicit membership/as-of rules, delisting returns
   and no survivorship bias.
2. **External engine adapter** (LEAN or NautilusTrader) behind the same result contract,
   validated against the independent ledger before exposure.
3. **Out-of-sample framework**: chronological train/validation/test, walk-forward,
   parameter sensitivity, multiple-testing accounting, and purged/embargoed CV when labels
   overlap.
4. **Bitemporal vendor store** and complete source archives so `fully_reproducible` is
   earned rather than asserted.
5. **Corporate-action coverage checks** that fail or clearly degrade when actions are
   incomplete; no silent raw-price/dividend mixing.
6. **Portfolio construction and risk**: weights, covariance, exposure, shorting/borrow if
   supported, with dimensioned types.
7. **Statement-derived features** keyed by `available_at`, never fiscal-period end.
8. **Reproducible experiment search** storing every attempted configuration and seed.
9. **Explicit execution model** for any non-next-open fill, including auction/queue
   assumptions and partial fills.
10. **Browser/API regression** for all prior phases plus new capabilities.

## Explicit non-goals

Live routing, high-frequency/order-book reconstruction, options chains, proprietary data,
GPU training, autonomous research and production execution management remain out of scope
until their data and validation prerequisites exist.

## Definition of done

A Phase 5 claim requires an independent assertion, a persisted artifact and an honest
limitation. Interfaces, stubs, mock engines and attractive charts are not capabilities.
