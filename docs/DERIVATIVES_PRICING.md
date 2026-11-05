# Derivatives pricing — first adapter

## Implemented model

European vanilla call and put under Black-Scholes-Merton with continuous rate and
dividend yield:

```
d1 = (ln(S/K) + (r - q + σ²/2)T) / (σ√T)
d2 = d1 - σ√T
call = S e^(-qT) N(d1) - K e^(-rT) N(d2)
put  = K e^(-rT) N(-d2) - S e^(-qT) N(-d1)
```

`src/atlas/finance/options.py` uses the standard library `erf` for the normal CDF.
Greeks are analytical: delta, gamma, vega, theta and rho. Implied volatility uses bisection
on a bounded positive interval and returns `null` when no valid solution exists.

## Conventions

| Output | Unit |
|---|---|
| price | currency per underlying unit |
| delta | change per 1.00 underlying |
| gamma | change in delta per 1.00 underlying |
| vega | per 1.00 (100 percentage points) volatility |
| theta | per year |
| rho | per 1.00 rate |
| volatility | annualized |
| rate / dividend yield | continuously compounded |

## Reference case

`S=K=100`, `T=1`, `r=5%`, `q=0`, `σ=20%`:

| Value | Call | Put |
|---|---:|---:|
| Price | 10.4505835722 | 5.5735260223 |
| Delta | 0.6368306512 | -0.3631693488 |
| Gamma | 0.0187620173 | 0.0187620173 |
| Vega | 37.5240346917 | 37.5240346917 |
| Theta (annual) | -6.4140281681 | -1.6578804239 |
| Rho | 53.2324810192 | -41.8904609047 |

These are well-known reference values, not values read back from the implementation.
Put-call parity residual is below `1e-12`; implied volatility recovers 20% within `1e-8`.
Delta and vega are additionally checked against central finite differences.

## Edge behavior

* `T=0` returns intrinsic value.
* Non-positive spot, strike or volatility are rejected.
* A price outside no-arbitrage bounds yields no implied volatility rather than a fabricated
  number.
* Negative rates are accepted where the formula remains defined.
* Deep out-of-the-money values can underflow to zero; the response does not claim precision
  below floating-point resolution.

## What this is not

This is not a market quote, an executable volatility surface, a local/stochastic volatility
model, an American option, or an index-volatility-derived chain. No option is included in
the portfolio ledger or risk covariance. The adapter exists so a future model can replace
it behind the same operator/API contract.
