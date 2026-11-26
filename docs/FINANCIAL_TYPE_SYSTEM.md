# Financial type system

Types are `FinType(kind, currency, element, temporal, convention, horizon)`.

Supported: `Money[CUR]`, `Price[CUR]`, `Shares`, `Rate[convention]`, `Ratio`,
`Scalar`, `Series[T]`, `Probability`, `Distribution`, `Forecast`, `Stock[CUR]`,
`Flow[CUR]`.

## Implemented rules

- `Price[USD] × Shares → Money[USD]`.
- `Money[USD] + Money[EUR]` is rejected with `currency_mismatch`; an explicit dated FX
  node is required.
- `Money / Shares → Price`.
- `Money / Money → Ratio`; `Series[T] × scalar/rate/ratio → Series[T]`.
- Adding different kinds, e.g. `Shares + Money`, is rejected.
- Adding explicitly different temporal axes (`flow` vs `stock`) is rejected.
- Forecast series created by `forecast_series` carry `temporal: forecast`.
- Rate conventions must agree when rates are added.

## Operators (`atlas.fec.operators.v1`)

`add`, `sub`, `mul`, `div`, `neg`, `abs`, `pow`, `min`, `max`, `growth`, `diff`,
`delta`, `forecast_series`, `npv`, `terminal_value`, `discount`, `sum`, `mean`.

`terminal_value` supports Gordon growth and an explicitly labelled exit multiple.
`npv`/`discount` support end-year and mid-year conventions. All numeric work uses
`Decimal` precision 28 and rejects non-finite results.

## Not yet modelled

Full accounting articulation (assets = liabilities + equity with enforced closing
balances), FX rate sources, inflation/index conventions, tax-loss carryforwards,
stochastic distributions and instrument pricing belong to later phases. Their absence is
reported rather than filled with invented values.
