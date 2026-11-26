# Portfolio optimization

## Problem

Minimum-variance long-only allocation on the synthetic active universe:

```
minimize    wᵀ Σ w
subject to  Σ w_i = 1 - cash_weight
            0 <= w_i <= max_weight
            optional: μᵀw >= target_return
```

`Σ` is sample covariance from all 935 aligned observations, annualized by 252. `μ` is the
historical sample mean, explicitly not a forecast. Optional diagonal shrinkage blends
off-diagonal covariance toward zero.

## Solver

The implementation enumerates active sets (each asset at zero, at its cap, or free) and
solves the equality-constrained KKT system with Gaussian elimination and partial pivoting.
It supports at most eight assets and reports the number of feasible active sets. This is a
transparent small-portfolio solver, not a general-purpose QP backend.

Infeasibility returns `feasible: false` with a reason. Singular systems are skipped; if no
active set is feasible, the API says so rather than returning an invalid portfolio.

## Constraints

| Constraint | State |
|---|---|
| Long only | implemented |
| Maximum position | implemented |
| Cash allocation | implemented |
| Target historical return | implemented; infeasibility reported |
| Diagonal shrinkage | implemented |
| Turnover cap | rejected as unsupported |
| Sector/group caps | rejected as unsupported |
| Transaction costs | not in the optimization objective |

## Reference result

Equal-weight starting point, cap 60%, no cash, no target: the solver returns
`SYN-BETA 0.4`, `SYN-GAMMA 0.6`, `SYN-ALPHA 0.0`. The sum is 1, the cap is respected,
and variance is no greater than the equal-weight variance. This is a constrained
minimum-variance estimate on synthetic data, not an investment recommendation.

## Diagnostics

The response includes weights, cash/invested totals, expected return, variance, volatility,
constraint checks, active-set count, covariance matrix, turnover (if current weights are
provided), solver name and limitations. The UI renders original and optimized weights plus
a constraint audit.

## Limitations

* Historical means are unstable and are not forecasts; the target-return objective is
  especially sensitive to them.
* Sample covariance from 935 synthetic sessions is not a robust risk model.
* No estimation-error resampling, robust optimization or Black-Litterman.
* No turnover, sector, tax, borrow, lot size or transaction-cost constraints.
* The exhaustive active-set enumeration does not scale beyond eight assets.
