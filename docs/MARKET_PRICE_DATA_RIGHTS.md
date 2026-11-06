# Market price data rights

Observed daily OHLCV was imported from the Nasdaq quote-history endpoint with retrieval time,
provider identity, unadjusted semantics and `restricted` redistribution. The series is stored
locally for analysis and is **not** packaged or exported.

Only `public_domain` series may be exported. The package state records `price_included: false`
and the provider reference so a user with their own entitlement can reconnect the data.

Price comparisons use the last observation at or before the accounting period end. When no
such observation exists, the latest price is shown with a mixed-date warning. Prices are never
synthesised or forward-filled.
