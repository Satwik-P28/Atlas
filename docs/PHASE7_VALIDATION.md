# Phase 7 validation

Status: backend and frontend suites pass. Browser acceptance is recorded separately below.
All numerical checks read the committed fixture and the API; none hard-codes a chart shape as
proof of correctness.

## Backend

```text
.venv/bin/python -m pytest -o addopts='' -q -p no:warnings
372 passed
```

The Phase 7 file contributes nine independent tests:

1. Schema 9, 1,095 observations, 365 aligned days, rights, retrieval-proxy availability, and a
   refused 2023 as-of query.
2. Graph counts, hypothetical company status, and source/provenance/rights on every edge.
3. Two contradictory station claims preserved with both values and no resolution.
4. Chronological 255/55/55 split, frozen test, RMSE skill, negative R², and explicit
   forecast-instability / association labels.
5. FEC reconciliation, independent scalar scenario calculation, separated uncertainty,
   intervals, sensitivities and invalid-input rejection.
6. Revision history retention, stale dependency invalidation and alert creation.
7. Application roundtrip, exact replay fingerprint, and refusal of an unsupported 2023 cutoff.
8. Synthetic DiD and ITS recovery on known data-generating processes, plus refusal of
   `regression_with_controls` as a causal design.
9. API workflow: health, catalog, graph, conflicts, analysis, scenario, application, Sentinel
   and benchmark routes.

## Independent numerical assertions

* Test RMSE equals the API value within 0.5 MW in the browser; backend tests recompute
  predictions from coefficients and feature names.
* Scenario central cost is independently calculated as
  `50,000 × fraction × 0.5 × 0.6 × $65` and compared with the FEC output.
* After-tax cost = cost × (1 − 0.21).
* Margin delta = −cost / $40m.
* DiD true effect 1.5 recovered within `1e-12`.
* ITS level 6.0 and slope 0.3 recovered within `1e-9`.
* Replay fingerprint equality is exact.
* Source conflict values 32.8 and 35.6 °C are both retained.

## Frontend

```text
cd web && npm test -- --run
4 passed
cd web && npm run build
tsc -b && vite build — success
```

The production bundle is approximately 660 kB / 196 kB gzip. The chart library accounts for
most of the bundle; no new UI dependency was added.

## Browser journey

`web/e2e/phase7.mjs` runs against a **copy** of the database so the correction drill cannot
mutate the shipped artifact. It covers:

* catalog API counts and persisted run identity;
* source names, rights badge and no-historical-vintage warning;
* rendered test R² and RMSE versus API values;
* causal-boundary text;
* 12 evidence graph rows and hypothetical company;
* both contradictory station values and no-winner policy;
* 2,000-draw scenario and a +4 °C recomputation changing cost;
* save application and reopen;
* 2023 replay returning `insufficient_evidence`;
* Sentinel refresh with automatic actions false;
* 390 px layout, document-overflow and graph-table-overflow checks;
* correction drill marking `ERUN-ac92ae9ffef03de2` stale.

Screenshots:

* `artifacts/36-economic-lab.png`
* `artifacts/37-economic-mobile.png`

Navigation timing is in `artifacts/phase7_browser.json`.

## Regression

Phase 1–6 tests remain passing after schema 9. Schema assertions that intentionally pinned
version 8 were updated to 9; no production behavior was weakened. The frontend build and
four existing Vitest checks pass.

## Not validated

* No licensed historical vintage or as-issued weather forecast was available.
* No external OSINT document parser exists to test.
* No live event-market adapter is implemented.
* No scheduler exists, so background monitoring is not tested or claimed.
* The browser test uses the local Chromium sysroot and may need the repository browser
  bootstrap after a runner restart.

## Commands

```bash
.venv/bin/python -m pytest -o addopts='' -q -p no:warnings
cd web && npm test -- --run && npm run build

# with the local Chromium sysroot
export LD_LIBRARY_PATH="$PWD/../.pwlibs/sysroot/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
export FONTCONFIG_PATH="$PWD/../.pwlibs/sysroot/etc/fonts"
export FONTCONFIG_FILE="$PWD/../.pwlibs/sysroot/etc/fonts/fonts.conf"
ATLAS_BASE=http://127.0.0.1:8001 node web/e2e/phase7.mjs
```
