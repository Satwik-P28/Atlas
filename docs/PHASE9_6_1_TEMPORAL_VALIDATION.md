# Phase 9.6.1 — Temporal Validation

## Corrected contract

Phase 9.6 stored `availability_time = acceptance + 900 s` and labelled it `exact`. EDGAR
acceptance is not the public-release instant, so that label asserted precision Atlas does not have.

| Field | Meaning now |
| --- | --- |
| `acceptance_time` | observed EDGAR acceptance timestamp (unchanged) |
| `public_availability_time` | observed public instant — **null**, none is independently available |
| `availability_time` | modelled bound = acceptance + `SEC_PUBLICATION_LAG_SECONDS` |
| `availability_basis` / `availability_model` | `sec_acceptance_plus_publication_lag_v1` |
| `availability_precision` | `unknown` (lagged) or `date` (no acceptance timestamp) |
| `ingested_at` | when Atlas stored the bytes |
| policy | `public_available` (default) or `atlas_ingested` |

Migration 015 relabels the existing 64 documents and adds `availability_model` and
`public_availability_time`. Timestamps are untouched, so 9.6.0 results reproduce exactly.

## As-of policy

* **Daily** (`as_of_precision="daily"`, the claim default): a modelled bound is acceptable; the
  claim is verified and carries an `availability_modeled_bound` diagnostic. Date-only sources are
  still refused, because a filing date is not an availability instant at all.
* **Intraday** (`as_of_precision="intraday"`): requires an observed exact instant; modelled bounds
  resolve to `unverifiable_historical_availability`.

## Boundary defect found and fixed

Cutoffs were compared as raw strings. `2024-03-01T12:15:00Z` (stored) sorts *after*
`2024-03-01T12:15:00.000Z` (caller), so a cutoff written with milliseconds excluded the very
second a filing became available. `search()` and `build_document_claim()` now normalise cutoffs
through `iso()` before comparison.

## Tests (`tests/test_phase9_6_1_temporal.py`, 7 passing)

1. Lag is modelled, not exact — precision `unknown`, model recorded, public instant null.
2. The boundary second is inclusive; one second earlier excludes and reports the exclusion.
3. Daily verifies a modelled bound; intraday refuses it.
4. Date-only metadata never verifies as an in-time claim.
5. Re-ingestion with identical bytes is idempotent; different bytes for the same accession raise.
6. Corpus growth before the cutoff does not mutate an earlier query's results.
7. `public_available` and `atlas_ingested` legitimately disagree, and neither corrupts the other.

## Not claimed

Zero measured leakage in the evaluation does **not** prove exact public availability: the
timestamps are modelled. It proves that nothing after the modelled bound was returned. Intraday
reconstruction remains refused rather than approximated.
