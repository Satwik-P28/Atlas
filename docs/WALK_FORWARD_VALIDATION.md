# Walk-forward and out-of-sample validation

## Contract

`atlas.institutional.walk_forward.v1` evaluates portfolio-weight strategies on aligned
synthetic returns. It never uses the test interval to choose a family or a parameter.
Each fold has three ordered partitions: train, embargo-separated validation, and an
untouched test interval.

```
train [t0, t1) | embargo 5 sessions | validation [v0, v1) | test [x0, x1)
```

The default test interval is the final 63 sessions of each fold. Folds advance by `step`.
`mode="rolling"` keeps the training window fixed; `mode="expanding"` starts training at the
first observation and grows it. Invalid or overlapping ranges raise a validation error.

## Selection protocol

Families: momentum, inverse volatility and a compiled Model Forge `close/SMA - 1` signal.
Lookbacks: 20, 60 and 120 sessions by default.

1. For each family, select the best lookback **on train** by Sharpe.
2. Evaluate the three family winners **on validation** and select one family.
3. Freeze that family and lookback.
4. Run the chosen strategy **once on the untouched test interval**.
5. Log every candidate at every stage, including losers.

Two folds therefore produce 18 selection attempts plus 6 test evaluations = 24 rows.
The API persists all of them in `validation_attempt`.

## Metrics

Reported per fold and aggregate: total return, annualized return, annualized volatility,
Sharpe (zero risk-free unless supplied), max drawdown, turnover, benchmark return and
excess return. The benchmark is equal weight with zero cost. Returns are simple daily
portfolio returns.

## Diagnostics and limits

* **Cost sensitivity:** the selected test strategy is rerun at 0, 2, 10 and 25 bps
  commission. This is a sensitivity check, not a transaction-cost model for every asset.
* **Parameter stability:** selected family and lookback per fold are retained. Stability
  is descriptive; it is not evidence of robustness.
* **Block bootstrap:** a deterministic moving-block bootstrap estimates a sampling
  distribution for the test excess return. The block length is disclosed in the result.
* **Multiple testing:** the raw p-value is accompanied by a Bonferroni-adjusted value and
  a warning. Neither converts a negative or insignificant result into alpha.
* **Data snapshot:** the universe content hash and observation count are recorded.

The test interval is still one historical path. Embargo reduces overlap leakage but does
not eliminate regime change, survivorship, model-class selection or researcher degrees of
freedom. Do not describe a single passing fold as a validated strategy.

## Results obtained

Two folds (`train=180`, `validation=40`, `test=40`, `embargo=5`) produce aggregate test
return **-16.93%**, excess **-3.23%**, raw bootstrap p **0.6955**, adjusted p **1.0** and
24 attempts. The negative result is retained. It is not evidence that the framework works
or fails as an investment method; it is a transparency demonstration.

## API

`POST /api/institutional/validate` returns the full result and persists a run plus attempts
when `persist=true`. `GET /api/institutional/runs/{id}/attempts` returns the retained
candidate log. The Lab's Out-of-sample validation tab renders the partitions, aggregate,
diagnostics and attempt table.
