# ADR 0021 — Bootstrap Treasury par yields instead of treating them as zeros

**Status:** accepted (Phase 5)

## Context

The official Treasury daily file publishes par yields, not zero-coupon spot rates.
Discounting coupons with par yields would conflate coupon-bearing and zero instruments.

## Decision

Archive the exact 2024 CSV, record its SHA-256 and source URL, and bootstrap coupon tenors
sequentially under a semiannual convention. Use continuous zero rates, ACT/365F and linear
zero interpolation. Assert that every coupon node reprices at 100.0.

## Consequences

The curve is internally consistent and provenance is inspectable. It remains an indicative
public curve without dealer quotes, settlement calendars or a full term structure. Missing
dates are errors, never invented points.
