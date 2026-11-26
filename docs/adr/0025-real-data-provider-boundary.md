# ADR 0025 — Real-data provider boundary

Status: accepted, Phase 6.

## Context

Phase 5 had one real IBM price series and a synthetic multi-asset panel. Phase 6 needs
multiple genuine histories without inventing a licence or redistributing a vendor dataset.
Several free/demo providers were audited. EODHD's documented demo entitlement resolved five
symbols (AAPL, MSFT, TSLA, VTI, AMZN) over a useful date range.

## Decision

Use the five EODHD demo histories as a **local, observed** research panel:

* cache provider JSON under ignored `var/phase6-eodhd/`;
* build `var/atlas-phase6.db` locally;
* register the source as `restricted`;
* commit code and aggregate evidence, never vendor bytes;
* label the panel `observed`, not `point_in_time_verified`;
* use the post-split 2023-01-03 → 2025-12-31 window and raw closes;
* keep synthetic fixtures separate and labelled.

## Consequences

Positive:

* real cross-sectional market histories, real sessions and prices;
* reproducible local build from the adapter/cache;
* honest rights boundary and no token in source.

Negative:

* a clean checkout without the cache cannot reproduce the real run;
* the five names are survivorship-selected and not a market universe;
* no displayed-vintage archive or correction history;
* dividends are excluded, so results are price-direction only.

## Rejected alternatives

* Scraping a provider against its terms: rejected.
* Treating a demo sample as a licensed feed: rejected.
* Mixing synthetic names into a “real” portfolio: rejected.
* Inventing a replacement master specification or data rights: rejected.

## Follow-up

A licensed point-in-time archive with corrections, delistings and redistribution permission
is a Phase 7 prerequisite.
