# Economic reality simulator v1

Schema: `atlas.economic.scenario.v1`.

The simulator is a narrow structural scenario executor over the fitted weather-demand
association. It does not contain a second financial compiler or a general equilibrium model.

## Scenario object

The stored result contains:

* analysis run and reference date;
* observed reference temperature, demand and model prediction;
* temperature shock;
* observed input fields and structural assumptions;
* demand response and parameter interval;
* uncertainty decomposition;
* financial assumptions and FEC result;
* temperature, price and hedge sensitivity grids;
* extrapolation flag where a shock leaves the historical range;
* limitations and reproducibility fingerprint;
* optional persistence and creation time.

The input contract is validated: shock in [-10, 10] °C; non-negative consumption and
pass-through; unhedged fraction in [0, 1]; non-negative price; positive revenue; tax in [0, 1];
draws in [200, 20,000]. Invalid combinations raise a typed validation error.

## Demand stage

The reference day is 2023-08-15, observed mean temperature 29.7 °C, observed demand
65,420.875 MW, model prediction 63,128.49 MW. A +2 °C shock substitutes the shocked degree-day
features into the selected model while retaining the reference day’s calendar terms.

```
CDD = max(T - 18, 0)
HDD = max(18 - T, 0)
demand = β0 + β_cdd·CDD + β_hdd·HDD + β_cdd²·CDD²
         + day-of-week + seasonal harmonics + ε
```

The central demand response is **+3.8694%**. This is a model-conditional counterfactual, not
an observed event.

## Financial stage

Company exposure is hypothetical: 50,000 MWh annual consumption, 50% regional-demand
pass-through, 60% unhedged, $65/MWh flat power price, $40m revenue, 21% tax.

The FEC model is `atlas.model.v1`, compiled by `atlas.fec.compiler.v1`:

```
facility_change = demand_change × load_sensitivity
cost_delta      = energy_cost_impact(annual_mwh, facility_change,
                                     unhedged_fraction, price)
ebit_delta      = -cost_delta
after_tax_cost  = after_tax_cost_impact(cost_delta, tax_rate)
margin_delta    = margin_impact(ebit_delta, revenue)
```

Central results:

* facility delta 967.34 MWh;
* cost increase **$37,726.30**;
* after-tax cost **$29,803.77**;
* operating margin **-9.43 bp**.

The simulator independently computes the scalar arithmetic and asserts equality with the FEC
output. The scenario does not perform its own valuation. There is no company DCF, credit
model, forward curve or hedge settlement in this slice.

## Uncertainty and sensitivity

2,000 multivariate-normal coefficient draws use the OLS covariance. Residual variance is used
only for a separate predictive check. Sensitivity grids recompute central results across
temperature (`-2, 0, +2, +4` °C), power price (`$45, $65, $85/MWh`) and unhedged exposure
(`20%, 60%, 90%`). See `UNCERTAINTY_PROPAGATION.md`.

## Execution and reproducibility

* deterministic seed for parameter draws: `20261105`;
* a fingerprint over canonical inputs and model identity;
* same inputs and source snapshot produce the same result;
* FEC run ID and compiler fingerprint are retained;
* scenarios are persisted per analysis and can be attached to an application;
* no automatic retraining or deployment.

## Physical consistency

The scenario enforces MW → MWh through annual consumption × fractional change, then MWh ×
$/MWh = $; tax applies to cost; margin delta divides by revenue. Units are not silently
interchanged. Geographic scope remains ERCO; the facility is hypothetical and located in the
same context. No frequency aggregation is performed because the panel is daily.

## Not implemented

Branching DAGs beyond the linear FEC model, correlated firm-level shocks, probabilistic
weather forecasts, forward power curves, contract settlement, pass-through optimization,
credit/default, equity valuation and real-estate underwriting. Do not read this scenario as a
company forecast.
