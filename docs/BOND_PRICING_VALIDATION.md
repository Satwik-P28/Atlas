# Bond pricing validation

## Scope

Fixed-coupon, option-free, hypothetical government bonds valued from the dated Treasury
zero curve. Settlement is user-supplied; coupons are semiannual; day count is ACT/365F.
No business-day adjustment, call feature, credit spread, tax or liquidity adjustment is
modeled.

## Method

For settlement `s`, maturity `m`, coupon rate `c`, face `F` and semiannual dates
`d_1 … d_n`:

```
accrued_days = s - previous_coupon_date
coupon_period_days = next_coupon_date - previous_coupon_date
accrued = c * F / 2 * accrued_days / coupon_period_days
dirty = Σ coupon_j * DF(t_j) + F * DF(t_n)
clean = dirty - accrued
```

Yield to maturity is solved from the same schedule by bisection on a nominal annual,
semiannually compounded yield. Macaulay duration is the present-value-weighted time;
modified duration is Macaulay divided by `1 + y/2`; convexity is the second-order
cash-flow-weighted term. DV01 is the dirty-price change for a one-basis-point parallel
zero-curve shift.

## Reference case

Curve 2024-06-28, settlement 2024-07-01, maturity 2029-06-30, coupon 4.25%, face 100:

| Measure | Value |
|---|---:|
| Clean price | 99.6348620554 |
| Dirty price | 99.6464740773 |
| Accrued interest | 0.0116120219 |
| Yield to maturity | 4.32939344% |
| Macaulay duration | 4.461737 years |
| Modified duration | 4.461737 / (1 + y/2) |
| Convexity | 23.26619 |
| DV01 | 0.0454221 per 100 face |

Exact displayed precision depends on the API; tests assert tighter internal tolerances.

## Independent checks

The test suite verifies, rather than restating the implementation:

1. Sum of every discounted coupon and principal equals dirty price.
2. Clean + accrued equals dirty.
3. Macaulay duration recomputed manually from published cash-flow PVs.
4. Modified duration × dirty × 1 bp approximates curve-revaluation DV01 within 4%.
5. Every coupon node in the bootstrapped curve reprices at par 100.0 within 1e-8.
6. A settlement after maturity is rejected with HTTP 422/typed validation error.
7. Shocks revalue the curve; they are not duration approximations alone.

## Precision policy

Internal calculations use Python binary floats. Tests use absolute tolerances of
`1e-9`–`1e-8` for identities, `1e-10` for duration, and 4% relative agreement for the
first-order DV01 approximation. API output is not rounded before persistence; the UI
rounds for display only.

## Limitations

* The curve is a par-yield bootstrap, not a dealer zero curve.
* The bond is hypothetical and not a registered tradable instrument.
* No settlement calendar, ex-coupon rules or accrued-interest conventions beyond the
  stated simple schedule.
* A duration/DV01 approximation is not a substitute for full revaluation; both are shown.
