# Historical universe integrity

## Declared universe

`SYN-UNIVERSE-PHASE5` is a synthetic, four-name fixture. Its membership is explicit:

* `SYN-ALPHA` and `SYN-BETA` from 2021-01-04.
* `SYN-GAMMA` begins 2021-06-01; earlier dates are labeled `before_listing`.
* `SYN-DELTA` stops 2023-12-29; later dates are labeled `after_delisting`.

Membership rows are generated for every weekday in the panel and carry a boolean plus a
reason. This makes missing sessions inspectable instead of silently filling them.

## Survivorship

The fixture includes one delisted path, so it is not built only from today's survivors.
It is nevertheless **not survivorship-bias-free**: four synthetic names cannot represent a
market, delisting returns are not modeled, and the panel does not reconstruct historical
index membership. The API states:

```
delisted_security_present: true
broad_market_universe: false
survivorship_bias_free: false
```

Every research application repeats the synthetic boundary. A future real universe must
add delisting returns and point-in-time membership before any stronger claim.

## Calendar and missing sessions

The calendar is weekdays only, with no exchange holidays. A return is formed only when
the active security has prices on both adjacent panel dates. This avoids inventing a
zero return for a missing session. The cost is a shorter active matrix (935 observations)
and no holiday-aware annualization beyond 252 sessions.

## Corporate actions and currencies

No splits, dividends or other corporate actions are present in the synthetic fixture;
its prices are already a total-return-like path. This is a fixture convention, not a claim
about real total-return accounting. All instruments are USD, and no FX conversion is
implemented.

## Identity over time

Tickers are display attributes; stable `security_id` values identify instruments.
Membership records use ISO dates. A delisted instrument is never reassigned to a new
ticker or included in the active sleeve.

## Known gaps

* No vendor corrections, restatements, or revision history.
* No provider licensing or redistribution rights because the data is generated locally.
* No exchange-specific calendars or halts.
* No real share counts, free float, index weights or corporate-action adjustments.
* No claim that the content hash proves historical market availability.
