# Uncertainty propagation

Status: implemented for the weather-demand scenario. Uncertainty sources remain separate;
`combined` is deliberately `null`.

## Sources

| Source | Implementation | Output |
|---|---|---|
| Observation | TMAX/TMIN precision; 0.05 °C perturbation | demand fraction range |
| Parameter | 2,000 draws from coefficient covariance | 90% demand and cost interval |
| Model form | linear vs quadratic degree-day alternative | alternative fraction |
| Relationship | observational design | `not_identified`; no causal interval |
| Forecast | residual variance | separate predictive check |

## Parameter draws

The selected OLS model supplies a coefficient vector and covariance matrix. The covariance is
symmetrized, eigen-decomposed and clipped at zero to remain positive semidefinite. Draws are
multivariate normal:

```
β* ~ N(β, Cov(β))
demand_base* = X_base · β*
demand_shock* = X_shock · β*
fraction* = (demand_shock* - demand_base*) / demand_base*
```

Using the full covariance preserves coefficient correlations. Economic shocks are not assumed
independent by default for this stage.

At 2,000 draws the +2 °C demand response has a 90% interval of **+3.3997% to +4.3638%** and the
cost interval is **$33,147.18 to $42,546.62**.

## Observation uncertainty

The source resolution is 0.1 °C. A ±0.05 °C perturbation produces a demand fraction range of
+3.7727% to +3.96598%. This is reported separately and is not folded into the parameter
interval.

## Model-form uncertainty

The alternative linear degree-day form gives +3.8960% versus +3.8694% for the selected
quadratic form. This small difference in one year does not establish model robustness and is
not merged into a single interval.

## Relationship uncertainty

Weather is not randomly assigned, so no causal interval is calculated. The result says
`relationship.status: not_identified` and explicitly refuses a causal interpretation.

## Why no single confidence percentage

Observation, parameter, model-form and identification uncertainty answer different questions
and have different semantics. Combining them would create a precise-looking number without a
defensible joint distribution. `uncertainty.combined` is `null` by design.

## Sensitivities

| Assumption | Values | Cost result |
|---|---|---|
| Temperature shock | -2 / 0 / +2 / +4 °C | -$37,818.86 / $0 / $37,726.30 / $75,360.03 |
| Power price | $45 / $65 / $85 per MWh | $26,118.21 / $37,726.30 / $49,334.39 |
| Unhedged fraction | 20% / 60% / 90% | $50,301.73 / $25,150.86 / $6,287.72 |

The hedge grid is labelled by unhedged fraction in the API but the UI header says “Unhedged
exposure”; the values are fractions of exposure, not hedge ratios.

## Extrapolation

The scenario flags when the shocked temperature lies outside the observed training range. The
+4 °C case remains inside the maximum observed temperature for this panel; larger valid-range
shocks are still structural extrapolations and must be labeled as such.

## Limits

* Parameter covariance is conditional on the selected functional form.
* Residual autocorrelation and heteroskedasticity are not fully modeled.
* No Bayesian posterior, bootstrap or HAC interval.
* No joint distribution across weather, price and firm exposure.
* Financial assumptions are fixed, not uncertain, except through the demand coefficient.
* The cost interval is a mechanical propagation of coefficient uncertainty, not a forecast.
