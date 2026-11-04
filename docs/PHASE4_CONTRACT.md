# Phase 4 contract — implemented status

Phase 4 is implemented on schema 6. The former “proposed” list is retained here only as a
compatibility record; see [PHASE4_IMPLEMENTATION.md](PHASE4_IMPLEMENTATION.md) for verified
capabilities and [PHASE5_CONTRACT.md](PHASE5_CONTRACT.md) for the next boundary.

## Implemented interfaces

* `atlas.strategy.v1` — versioned, single-instrument, long-only strategy object.
* `atlas.feature.v1` — typed price/volume features with historical cutoff.
* `atlas.quant.reference.v1` — chronological next-open simulator with an independent ledger.
* `atlas.quant.vectorized.v1` — explicitly non-fill close-to-close preview.
* `atlas.quant.run.v1` — persisted run, reconciliation, metrics and fingerprint.
* `atlas.time_capsule.v1` — strategy/config/source/archive/replay context.
* `atlas.quant.experiment.v1` — experiment document stored as a research object.
* `atlas.research.archive.v1` — content-addressed source archive with rights metadata.

## Preserved

`atlas.model.v1`, `atlas.fec.ir.v1`, `atlas.research_object.v1`, evidence selection,
historical cutoff semantics and all Phase 1–3 APIs remain authoritative. Migration 006 is
additive.

## Not yet implemented

Multi-instrument universes, shorting, intraday/auction fills, external engine adapters,
out-of-sample/walk-forward validation, statement-derived features and a bitemporal vendor
price store. These are not represented as working features.
