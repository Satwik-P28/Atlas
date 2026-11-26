# Weather → electricity → financial impact

The Phase 7 acceptance study. All weather and demand values are real public observations;
the company and its financial exposure are hypothetical.

## Question

Is Dallas-area temperature associated with ERCOT daily mean electricity demand in 2023, and
what financial consequence would a declared temperature shock have for an explicitly
hypothetical Texas manufacturer?

This is a predictive association and a conditional scenario. It is not a causal identification
and not a company forecast.

## Evidence

| Input | Identity | Rights |
|---|---|---|
| ERCOT demand | EIA-930 `ERCO` hourly demand, 2023 | U.S. public domain |
| Primary weather | NOAA GHCN-Daily `USW00013960` DFW | U.S. public domain |
| Comparison weather | NOAA GHCN-Daily `USW00003971` Redbird | U.S. public domain |
| Panel | `fixtures/phase7/weather_demand_2023.csv` | derived, public-domain sources |

365 complete days, 8,760 hourly demand records, 1,095 observations. Demand mean 51,007.16 MW,
daily mean range 37,517.5–71,371.875 MW. Primary station mean temperature 21.07 °C, observed
range -2.95 to 36.95 °C. Maximum station TMAX disagreement 2.8 °C on 2023-06-30.

The current bulk archives have no verified historical publication vintage. Availability is the
2026 retrieval instant. A 2023 as-of query therefore returns insufficient evidence.

## Stage A–C: model

Features: cooling/heating degree days at 18 °C, quadratic cooling term for the selected form,
six day-of-week indicators and three annual harmonic pairs.

Chronological split:

| Partition | Dates | Rows |
|---|---|---:|
| Train | 2023-01-01 → 2023-09-12 | 255 |
| Validation | 2023-09-13 → 2023-11-06 | 55 |
| Test | 2023-11-07 → 2023-12-31 | 55 |

Candidates are the seasonal baseline, linear degree-day model, and quadratic degree-day model.
Selection uses validation RMSE only. The test is not used for selection.

Selected: `degree_day_curvature`, validation RMSE 2,612.24 MW.

| Test metric | Selected | Seasonal baseline |
|---|---:|---:|
| RMSE | 2,956.58 MW | 4,588.78 MW |
| MAE | 2,513.43 MW | 4,081.58 MW |
| Mean error | +2,378.06 MW | +4,080.72 MW |
| R² | **-0.8935** | -3.5611 |

RMSE skill versus seasonal is **35.57%**, but the negative R² means the model does not beat a
constant test mean and exhibits a large positive late-year bias. The conclusion is
`association_supported_forecast_unstable`. This is an honest mixed result: the weather
relationship is visible, the forecast is not stable enough to deploy.

Conditional association at the reference: **1,222.83 MW per °C CDD**, 95% sampling interval
1,073.42–1,372.24 MW. Identification: none. Causal status: `not_identified`.

## Stage D–F: shock and financial consequence

Reference day 2023-08-15: 29.7 °C observed, 65,420.875 MW demand, 63,128.49 MW model
prediction. A +2 °C shock produces **+3.8694%** conditional demand.

Hypothetical firm: 50,000 MWh/year, 50% demand pass-through, 60% unhedged, $65/MWh, $40m
revenue, 21% tax.

| Financial result | Value |
|---|---:|
| Facility energy delta | 967.34 MWh |
| Cost increase | $37,726.30 |
| After-tax cost | $29,803.77 |
| EBIT change | -$37,726.30 |
| Margin change | -9.43 bp |

The FEC compiler run is `RUN-60ef2b7483bb29293492fc09`, compiler fingerprint
`5689a3efdc93bce96f907daa03c8823dd384b517111c5fabec97db3152427e81`.

## Stage G: historical replay

The saved 2026 retrieval snapshot reproduces 365 rows and the exact run fingerprint. A
2023-12-31 cutoff returns `insufficient_evidence`, because the current archive cannot prove
what was published at that date. No historical weather forecast is invented. The study also
does not pretend the 2023 weather was forecast in advance.

## Stage H: application

The saved application (a generated `URO-APP-…` object) persists the question, source IDs,
dataset/model/experiment objects,
association, uncertainty, scenario, limitations and replay views. The application can be
reopened; changing the scenario assumptions recomputes the financial consequences without
rewriting the saved thesis.

## What would change the conclusion

* A verified historical vintage and archived weather forecasts.
* Area-weighted gridded weather or multiple stations, not one point.
* Additional years and regions, with extreme-event coverage.
* A credible identification design for causal demand elasticity.
* Observed company load/contract data and a forward power curve.
* Interval calibration and a stable out-of-sample forecasting protocol.

None of these is claimed here.

## Reproduction

```bash
.venv/bin/python scripts/fetch_phase7_data.py
.venv/bin/python scripts/build_phase7_fixtures.py
.venv/bin/python scripts/build_phase7_db.py --db var/atlas-phase7.db
.venv/bin/atlas --db var/atlas-phase7.db serve --host 127.0.0.1 --port 8000
```

The raw archives remain ignored; the compact fixture and manifest are committed.
