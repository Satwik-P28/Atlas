# ADR 0032 — Weather-demand regression is an association

Status: accepted.

## Context

The weather-demand model is statistically strong on validation and beats the seasonal RMSE
baseline on the frozen test, but weather is not randomly assigned and the study has one region,
one year and a point station. A regression with calendar controls does not identify a causal
effect. The test also has negative R² and positive bias.

## Decision

Classify the result as `association` / `not_identified`. Name the coefficient a conditional
association, not an elasticity or causal effect. Report the 95% interval as sampling
uncertainty. Add a forecast-instability finding rather than promoting the model because RMSE
improved. Implement DiD and interrupted time series separately, with explicit design
assumptions and refusal of unknown designs.

## Consequences

* Causal language is only available through a declared, assumption-bearing design.
* The simulator calls its +2 °C result a conditional counterfactual, not a causal response.
* The UI displays the causal boundary beside the test result.
* A future natural experiment can replace the design without rewriting the observation layers.
