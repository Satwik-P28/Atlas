# Causal research

Status: implemented policies and two explicit estimators, plus an observational
weather-demand study that is deliberately **not** causal.

## Separation

| Question | Result class | Identification |
|---|---|---|
| Does temperature predict same-day ERCOT demand? | predictive association | none |
| Does temperature cause demand? | not estimated | no randomized or credible natural experiment |
| What would +2 °C do under the fitted conditional model? | counterfactual scenario | model assumption, not causal effect |
| DiD / interrupted time series on a suitable design? | estimated causal effect | caller declares design assumptions |

`economic.causal.classify_design` returns the epistemic status and the assumptions that must
hold. `observational_regression` is permanently classified as `association` /
`not_identified`. An unknown design, including `regression_with_controls`, is rejected.

## Implemented estimators

### Two-by-two difference-in-differences

`two_by_two_difference_in_differences(rows, outcome, treated, post)` requires all four cells.
It estimates:

```
(Y_treated,post - Y_treated,pre) - (Y_control,post - Y_control,pre)
```

It reports cell means and sizes, a Welch-style sampling standard error, a 95% interval and four
assumptions: parallel trends, no anticipation, stable composition and no concurrent
treatment-specific shock. It does not search for a control group.

### Interrupted time series

`interrupted_time_series(rows, outcome, time, post, treatment_time)` fits:

```
Y = β0 + β1·time + β2·post + β3·max(time - treatment_time, 0) + ε
```

It requires at least eight observations and a full-rank design. It reports level change,
slope change, standard errors, 95% intervals and four assumptions. It cannot detect a
concurrent shock automatically.

## Independent validation

Synthetic data with known structure verifies estimator behavior:

* 2×2 DGP with true effect **1.5**: estimated 1.5 within `1e-12`; identified status.
* ITS DGP with level jump **6.0** and slope change **0.3**: recovered within `1e-9`.
* Observational design returns `association`, not causal.
* `regression_with_controls` is rejected as an unknown identification design.

These tests are independent of the weather data.

## Weather-demand study

The selected model regresses daily mean ERCOT demand on degree days, day-of-week and annual
seasonal terms. It is fit on 255 days, selected on 55 validation days and evaluated once on 55
chronological test days.

The reported quantity is **1,222.83 MW per °C of cooling degree days at the reference** with a
95% sampling interval of 1,073.42–1,372.24 MW. It is explicitly named:

`conditional association; not an identified causal effect`.

Why no causal label:

* weather is not randomly assigned;
* the point station is not the full balancing-area temperature;
* omitted prices, outages, industrial activity and adaptation are plausible;
* the design has no treatment timing or comparison group;
* same-day feedback and measurement error are unresolved;
* the model has one year, one region and one primary station.

The interval is sampling uncertainty for the association, not a causal confidence interval.
The test R² of **-0.8935** also rules out a claim of stable predictive skill.

## Falsification and refusal

The Phase 7 test suite exercises temporal ordering, chronological leakage, missing rows,
nonstationarity/invalid controls by design rejection, and estimator behavior on known DGPs.
More formal placebo outcomes and sensitivity analysis remain future work. The system returns
`not_identified` rather than manufacturing a causal estimate.

## Limitations

* No synthetic-control estimator yet.
* No automated parallel-trends or concurrent-shock test.
* No clustered/time-series HAC standard errors in the scenario.
* No instrumental variables, regression discontinuity or event-study design.
* DiD/ITS availability does not imply a suitable natural experiment exists.
