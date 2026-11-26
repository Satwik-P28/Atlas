# Portfolio risk

## Inputs and alignment

Risk is computed from the 935-observation aligned synthetic return matrix. Only the three
active securities are included. Weights are long-only, finite and sum to at most 1; any
uninvested weight is cash with zero risk and zero return. The effective lookback defaults
to 252 sessions and may not exceed the available history.

Daily simple returns are used throughout. Sample covariance is annualized by 252.

## Measures

* **Volatility:** `sqrt(wᵀ Σ w)` with annualized covariance.
* **Component variance:** `w_i (Σw)_i`. Components sum exactly to portfolio variance.
* **Component volatility:** component variance divided by portfolio volatility. Components
  sum to portfolio volatility, verified within `1e-10`.
* **Contribution percentage:** component variance / total variance, summing to 1.
* **Beta:** sample covariance with the equal-weight active portfolio divided by benchmark
  variance.
* **Historical VaR 95%:** the positive loss at the lower 5% sample quantile, not the 95th
  percentile of returns. This distinction was a real defect found by the Phase 5 tests and
  corrected.
* **Expected shortfall 95%:** average loss in the worst 5% tail, at least as large as VaR.
* **Maximum drawdown:** worst peak-to-trough decline of the compounded equity curve.
* **Exposures:** gross, net, cash and sector weights from declared instrument metadata.

## Stress scenarios

| Scenario | Method | Status |
|---|---|---|
| Equity market −20% | linear beta approximation; cash unchanged | implemented |
| Severe combined −35% | linear beta approximation | implemented |
| Parallel rates +100 bp | requires a fixed-income sleeve | explicitly unsupported |
| Volatility shock | requires an option/vol sleeve | explicitly unsupported |

The unsupported rows return `null` with a reason. A linear beta scenario is not presented
as nonlinear revaluation or a forecast.

## Lookback sensitivity

At 252 sessions the equal-weight portfolio volatility is about **18.63%** and annualized
return about **18.24%**. Using all 935 sessions changes the estimate; the API reports the
actual lookback window and dates with every result. Neither estimate is a forecast.

## Statistical honesty

* The fixture is synthetic and has no market interpretation.
* Historical VaR/ES are sample quantiles; tail coverage beyond the sample is not guaranteed.
* Beta is measured against an equal-weight synthetic benchmark, not a market index.
* Sector classifications are fixture metadata, not GICS.
* No factor model, FX, derivatives, taxes, borrow or transaction costs are included.
* No high-precision claim is made from four synthetic instruments.

The risk report is persisted through the institutional run table and can be saved as a
research application with its weights, lookback, provenance and limitations.
