# Yield curve contract

## Source

`fixtures/phase5/treasury-par-yields-2024.csv` is the official U.S. Department of the
Treasury daily par-yield curve for 2024, downloaded as CSV:

```
https://home.treasury.gov/resource-center/data-chart-center/interest-rates/
daily-treasury-rates.csv/2024/all?type=daily_treasury_yield_curve
&field_tdr_date_value=2024&page&_format=csv
```

The exact local bytes have SHA-256
`6775840b76cd7fd41121f61d6f6c60184eca6b2ba49954ec7372c463cbeef34d`.
The file is public-domain U.S. government data. It is archived as a fixture, not fetched at
calculation time.

Default observation date: **2024-06-28**. The API accepts any date present in the file and
rejects malformed dates. A missing date is an error, not an interpolated curve.

## Tenors and bootstrap

Treasury labels (1M, 2M, 3M, 4M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y) are converted
into dated observations. Bills (≤ 1 year) are treated as zero-coupon observations.
Coupon tenors are bootstrapped sequentially under a **semiannual** coupon convention:

* For each coupon node, coupons are paid on the node's scheduled semiannual dates.
* Earlier cash flows are discounted with already-bootstrapped zero rates.
* The final cash flow (coupon + principal) determines the new zero rate.
* The resulting curve reprices every coupon node at exactly **100.0** per 100 face.

This identity is tested for every coupon node, not asserted from one point. Parsing par
yields as zero rates would be a contract violation.

## Conventions

| Item | Convention |
|---|---|
| Zero-rate compounding | continuous |
| Day count | ACT/365F |
| Interpolation | linear in zero rates |
| Extrapolation | flat |
| Coupon frequency | semiannual |
| Business-day adjustment | none |
| Calendar | none |
| Settlement | user-supplied date |
| Curve source | exact archived Treasury CSV |

Forward rates are derived from discount factors:

```
f(t1,t2) = ln(DF(t1)/DF(t2)) / (t2 - t1)
```

and tested against that identity. No missing curve point is invented.

## Data model

A curve response includes observation date, source name/URL/rights/retrieval time/SHA-256,
conventions, limitations, and each node's par yield, continuously compounded zero rate,
discount factor and years. Market data and model assumptions are separate fields.

## Limitations

* Treasury par yields are indicative public observations, not executable quotes.
* The bootstrap assumes a semiannual coupon structure at each node and no taxes,
  liquidity premium or credit spread.
* Interpolation can create unrealistic forward-curve shapes between sparse tenors.
* Business-day and holiday settlement rules are not modeled.
* No inflation, swap, OIS or SOFR curve is present.
