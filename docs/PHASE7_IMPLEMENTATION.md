# Phase 7 implementation — economic intelligence vertical slice

Status: **implemented and numerically validated on schema 9.** The flagship study uses real
public NOAA GHCN-Daily station observations and EIA-930 ERCOT demand. The weather-demand
result is an association with an unstable forecast, not an identified causal effect. Company
exposure and financial consequences are explicitly hypothetical.

## Master specification

`ATLAS_MASTER_SPEC.md` version 1.2.0 was **not present in the checkout** and no external path
was supplied to the coding environment. It was not reconstructed or replaced. This requirement
remains a documented blocker. The existing Phase 1–6 contracts, `PHASE7_CONTRACT.md` and this
Phase 7 record are the in-repo authority until the genuine file is supplied.

## Delivered

| Capability | State | Evidence |
|---|---|---|
| Public economic observations | Implemented | 1,095 observations from EIA-930 and NOAA GHCN-Daily |
| Provenance and rights | Implemented | Source URLs, SHA-256, public-domain rights and retrieval limitations |
| As-of panel reconstruction | Implemented | Explicit `public_available` / `atlas_ingested` modes |
| Historical vintage | **Unsupported** | Current archives have no evidenced publication vintage |
| Evidence graph | Implemented | 12 entities, 12 edges, source rights/provenance on every edge |
| Claim and conflict ontology | Implemented | Four claims, one preserved station conflict |
| Weather-demand model | Implemented | Chronological 70/15/15, seasonal baseline, two degree-day forms |
| Association vs causation | Implemented | `causal_status: not_identified`; no causal coefficient language |
| Scenario simulator | Implemented | Temperature shock, 2,000 draws, sensitivity, extrapolation checks |
| Financial consequences | Implemented | Scenario compiled through the FEC, not duplicated arithmetic |
| Research application | Implemented | Save, reopen, fork/compare through the Universal Research Object store |
| Sentinel | Implemented | Manual refresh, dependency invalidation, alert history |
| Historical replay | Implemented | Recomputes exact retrieval snapshot; refuses 2023 cutoffs |
| Economic Lab | Implemented | `/lab/economic`, desktop and 390 px layouts |
| Optional event markets | **Not implemented** | Deliberately outside the flagship slice |
| Real-estate pack | **Not implemented** | Shared geography contracts only |

## Schema 9

Migration 009 is additive and creates:

* `economic_series` — provider series identity, geography, units, frequency, rights, vintage
  and publication policy;
* `economic_observation` — value, period, observation/retrieval/availability time, vintage,
  revision chain, quality and content hash;
* `economic_entity` — typed economic nodes with geography, evidence class and validity;
* `economic_edge` — source-backed, inferred or hypothetical relationships with confidence;
* `economic_event` — structured event records;
* `economic_claim` — typed epistemic and causal status;
* `economic_conflict` — conflicting assertions without a forced winner;
* `economic_analysis` — full canonical result JSON, fingerprint and stale state;
* `economic_scenario` — scenario input/result JSON and FEC fingerprint;
* `economic_dependency` — exact observation/model/scenario dependencies;
* `economic_alert` — source revisions, staleness and monitoring alerts.

`/api/health` reports `schema_version: 9`, `supported_schema: 9`, `integrity_check: ok`.

## Architecture

```
public EIA-930 + NOAA GHCN archives
          ↓
scripts/build_phase7_fixtures.py (committed compact fixture + manifest)
          ↓
economic.data      source registry, observations, as-of panel, graph, claims
          ↓
economic.model     chronological weather-demand association and audit
          ↓
economic.causal    DiD / ITS / observational refusal policy
          ↓
economic.scenario  shock, coefficient draws, sensitivity, FEC financial mapping
          ↓
economic.service   persistence, applications, replay, Sentinel, revision
          ↓
FastAPI + Economic Lab + existing research-object store
```

The Temporal Evidence Kernel, source registry, Universal Research Object System,
Financial-Economic Compiler, Quant Lab and Learning Brain are reused. No second compiler,
research platform or identity system was introduced.

## Real flagship run

`ERUN-ac92ae9ffef03de2`, fingerprint
`ac92ae9ffef03de2df5daf2449d9a2b87fa99a0e7994548de39f776048502fce`.

| Item | Value |
|---|---|
| Panel | 2023-01-01 → 2023-12-31, 365 complete days |
| Demand | ERCOT daily mean, mean 51,007 MW, range 37,517.5–71,371.875 MW |
| Weather | Dallas/Fort Worth `USW00013960`; Redbird `USW00003971` comparison |
| Split | 255 train / 55 validation / 55 test |
| Selected form | `degree_day_curvature` |
| Validation RMSE | 2,612.24 MW |
| Test RMSE | 2,956.58 MW |
| Seasonal test RMSE | 4,588.78 MW |
| RMSE skill | 35.57% |
| Test R² | **-0.8935** |
| Test mean error | **+2,378.06 MW** |
| Conclusion | `association_supported_forecast_unstable` |
| Causal status | `not_identified` |
| Audit | 0 errors, 5 warnings, 1 info |
| Test selection | Never used |

The selected model beats the seasonal RMSE baseline but fails against a constant test mean.
That contradiction is retained: it is evidence of a conditional association in one year and
one region, not a deployable load forecast.

## Financial scenario

Central +2 °C shock on the 2023-08-15 reference day, 50,000 MWh annual consumption, 50%
demand pass-through, 60% unhedged, $65/MWh, $40m revenue, 21% tax:

| Output | Value |
|---|---:|
| Regional demand response | +3.8694% |
| Facility energy delta | 967.34 MWh |
| Cost increase | $37,726.30 |
| After-tax cost | $29,803.77 |
| Operating margin change | -9.43 bp |
| Demand 90% parameter interval | +3.3997% to +4.3638% |
| Cost 90% interval | $33,147.18 to $42,546.62 |

The financial allocation is executed by `atlas.model.v1` through the FEC. Scenario code
independently reproduces the scalar result and asserts the FEC output agrees.

## Verification

* Backend: **372 passed** (363 prior + 9 Phase 7).
* Frontend: **4 passed**; production build succeeds.
* Phase 7 browser journey and screenshots: see `PHASE7_VALIDATION.md`.
* Benchmark: `artifacts/phase7_benchmarks.json`.

## Defects found and fixed

* Graph serialization referenced `GRAPH_SCHEMA` and `ECONOMIC_SCHEMA` without importing them;
  both were caught by the first graph/catalog calls.
* Graph edges omitted source rights and provenance required by the contract; the query now
  joins the source registry and exposes `source_name`, `rights`, `provenance` and
  `source_evidence`.
* Two hypothesis edges used `hypothesized` while the graph contract uses `hypothetical`;
  counts and labels now agree.
* Forecast skill and R² disagreed. The original conclusion was too strong; a
  `test_regime_instability` finding and `association_supported_forecast_unstable` status were
  added rather than hiding the negative R².
* Benchmarked object export called a non-existent method; it now uses `export_manifest`.
* The research-memory summary omitted saved applications; `counts.applications` now reports
  them.

## Deliberate boundaries

* No historical forecast archive was available; replay does not invent day-ahead weather.
* The current NOAA/EIA archives are retrieval proxies, not as-issued historical vintages.
* A point station is not an area-weighted ERCOT temperature.
* No company, facility, load, contract or supplier relationship is observed.
* No OSINT document crawler, entity-resolution service, LLM extraction or GDELT ingestion.
* No real-time scheduler, automatic retraining or deployment.
* No event-market execution, real-estate underwriting platform or live data feed.
