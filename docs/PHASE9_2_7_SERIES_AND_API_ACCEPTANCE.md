# Phase 9.2.7 Acceptance — Canonical Market Series and API Architecture

**Starting commit:** `699f3ca051f2b43186ed3671a1ac272465a1710b`
**Branch:** `freebuff/41a4fd2abe41a6515dc8d5bb`
**Database schema:** 13 (no migration added)
**Backend suite:** 577 passed (560 before this phase + 17 new)
**Frontend:** 4 unit tests, typecheck and production build pass

## Source-level defects corrected

1. **Markets Overview bypassed canonical selection.**
   `market_overview()` called `BarStore.query(..., "1990-01-01", today)` and used
   `series[-1]`, `series[-2]`, `series[-252]`. `query` keeps every provider's newest
   revision, so two providers on one session produced two rows for one date; the "previous"
   row could be the same day from another provider; a correction rewrote a historical
   point; a sparkline could contain duplicate dates; and `series[-252]` is neither a
   calendar year nor one provider's year.
2. **The chart had the same shape.** `market_series()` filtered by security and venue, not
   provider, so its bars could interleave providers and its last bar could disagree with
   the price the page quoted.
3. **Historical issuer metrics used a current price.** `issuer_metrics(as_of=...)` applied
   the cutoff to accounting evidence but called `latest_observation` without it, so a
   report as of 30 June could use a 1 July price.
4. **Cached metrics could not say which question they answered.** The materialized-metrics
   cache always supplies an instant, which made every cached response look point-in-time.

## What changed

| Area | Change |
| --- | --- |
| `market/evidence.py` | `MarketSeriesSelection`, `select_series`, `SeriesChange`, `series_changes`, `MarketObservation.to_bar()`, lazy identity |
| `terminal/read_models.py` | `market_overview` and `market_series` on the canonical series; `issuer_metrics` split into current vs point-in-time with `market_basis`, `market_cutoff` |
| `terminal/metric_store.py` | passes `market_basis="current"` when the caller supplied no `as_of`; model version `v2` |
| `terminal/routes/market.py` | market group extracted from `api.py` (139 routes unchanged) |
| `terminal/api.py` | includes the market router; request models live with their routes |
| `scripts/benchmark_market_series.py` | reproducible synthetic tiers, query counts, memory, size |
| tests | `tests/test_phase9_2_7_market_series.py` (17), `tests/fixtures/openapi_phase9_2_7.json` |

## Series semantics

One provider is chosen by the canonical selection at the cutoff (or explicitly) and held
constant for the window. One selected observation per session; excluded providers,
revisions and missing sessions are reported; competing observations and superseded
revisions stay stored. A mixed-provider series is not produced, because a change across
two providers is not a change in one observed series.

## Return conventions

| Basis | Meaning | Label |
| --- | --- | --- |
| `price` | raw close-to-close | not adjusted for splits or dividends |
| `split_adjusted` | split-adjusted price change | dividends not reinvested |
| `total_return` | total-return index change | dividends reinvested |

One day uses the preceding distinct session of the same series. One year uses the last
session at or before the same calendar date a year earlier, and reports `change_1y_target`,
the actual from/to sessions and `change_1y_span_days`. A short series returns `null` with
the reason; `series[-252]` is gone.

## Adversarial coverage (17 tests)

Two providers on one session; different prices on that session; a correction; a missing
session; a holiday gap with a real calendar; a stock split; a dividend; a second venue; a
restricted vs permitted source; an explicit provider; a series that never reaches a year;
an unknown return basis; saved-pin replay after a correction; overview ↔ chart ↔ metrics
agreement on one `observation_id`; historical cutoff; corrected price inside a
point-in-time run; OpenAPI equality.

## Historical semantics

* no `as_of` → `market_basis = "current_market"`; latest price vs latest accounting
  evidence, both dates reported.
* `as_of` → `market_basis = "point_in_time"`, `market_cutoff` = that date; the price must be
  dated on or before it. A July price cannot enter a June run.
* A price dated before the cutoff is **not** proof that the vendor revision available then
  matched the one stored now. Every point-in-time response says so, and this is a stated
  limitation, not a reconstruction.

## Performance (measured, 2 vCPU VM, synthetic, 260 sessions)

| Metric | 100 securities | 1,000 securities |
| --- | --- | --- |
| rows / database | 28,610 / 14.8 MB | 286,100 / 142 MB |
| conflicting sessions (2 providers) | 2,600 | 26,000 |
| `latest_close` (median) | 0.026 ms | 0.025 ms |
| `select_price` (median) | 0.119 ms | 0.124 ms |
| canonical series 1Y (median) | 4.16 ms | 4.24 ms |
| one-year chart request | 7.95 ms, 32 statements | 9.66 ms, 32 statements |
| Markets Overview | 666 ms, 2,404 statements | 7,585 ms cold, 24,004 statements |
| overview statements per row | 24.04 | 24.00 |
| overview peak tracemalloc | 1.22 MB | 3.90 MB |

Only a measured bottleneck was optimized. Profiling showed per-point identity hashing cost
8.5 ms of a 10.3 ms series read (with 1.25 ms of SQL); making identity lazy — same values,
same ids, computed on first access — reduced the series to ~4.2 ms and the 1,000-security
overview from 13.5 s to 7.6 s. No further speedup is claimed.

**Known limitation:** the overview builds one series per security in Python. At 1,000
securities it takes ~7.6 s and 24 statements per row. A bulk projection of the same policy
(single query, grouped in Python, differentially tested against the per-security result) is
the next step and is recorded in the gap analysis. The 10,000-security tier was **not**
run: at this shape it would need ~5.2 M rows and minutes of build time, and the 1,000 tier
already characterises the per-row cost.

## Financial regression results

| Gate | Result |
| --- | --- |
| Backend suite | **577 passed**, exit 0 |
| Frontend tests | **4 passed** |
| TypeScript typecheck | pass |
| Production build | pass (2.70 s) |
| Phase 9.2 audit | `status: pass`, **29/29** |
| Phase 9.1 audit | `status: pass`, **16/16** |
| Reference reproduction | `differences: {}`, `295.4643539226478`, package `3bbaca54…` |
| Distributable fixtures | `status: pass` |
| Clean install | `status: pass`, `101.21579153430544`, `differences: {}`, `network_used: false` |
| OpenAPI contract | 139 routes / 125 paths identical to the pre-refactor snapshot |

The JPM package hash and value are unchanged from `699f3ca`, which is the intended
result: this phase changed *which* observation a series uses, not the arithmetic of any
model.

## Browser acceptance (cloud Chromium)

| Check | Result |
| --- | --- |
| Markets overview desktop | **verified** — 1 security, ATLS $109.50, +0.92% one-day, one-year `—` (honest: 10 sessions), 30-session sparkline, session 2024-12-13, SYNTHETIC label |
| Company page desktop | **verified** — price 2024-12-13, point-in-time note replaced by current-market semantics after the cache fix |
| Charts tab | **opened and rendered**, chart request verified directly: 10 bars, 0 duplicate dates, ordered, single provider, source matches the quoted price |
| Chart API | `view=split`, 10 bars, `policy=single_provider_held_constant`, `excluded_providers=[]` |
| Mobile 390×844 | **not verified** — the Playwright tool failed with an internal `options.mode` error, and the Cloud browser panel exposes no viewport control. Reported as a limitation, not as a pass. |

Screenshots: `artifacts/phase9_2_7_markets_desktop.png`,
`artifacts/phase9_2_7_company_desktop.png`, `artifacts/phase9_2_7_chart_desktop.png`.

## API architecture

`terminal/api.py` retains application wiring, middleware, exception mapping, static
mounting, `/api/health`, `/api/schema`, and the dependency; the market group
(8 routes) lives in `terminal/routes/market.py`, built with
`build_market_router(get_db)`. No cycle: `api → routes.market → read_models → domain`.
The OpenAPI document, captured before the move into
`tests/fixtures/openapi_phase9_2_7.json`, is required to match afterwards. Additive
response fields (`change_basis`, `change_1d_dates`, `change_1y_dates`, `change_1y_target`,
`change_1y_span_days`, `price_observation_id`, `series_policy`, `series_limitations`,
`series`, `market_basis`, `market_cutoff`) are the only public changes.

## Master specification

**Blocked.** `find / -name 'ATLAS_MASTER_SPEC*'` returns nothing and
`scripts/verify_master_spec.py` exits 1. No clause mapping was attempted and no content was
reconstructed. The market-series work does not depend on it.

## Hosted CI

**Unobserved.** The repository is private, `gh` has no credential, and
`GET /repos/Satwik-P28/Atlas/actions/runs?head_sha=…` returns **404**. The workflow now
includes `tests/test_phase9_2_7_market_series.py` in the research-integrity job, but no run
is claimed.

## Remaining blockers

1. Master specification absent (unchanged).
2. Hosted CI unobservable (unchanged).
3. Mobile-layout browser verification blocked by tooling (new, reported).
4. Markets Overview does not scale past ~1,000 securities without the bulk projection.
5. Restricted historical vendor bytes remain in earlier history; no rewrite performed.
6. The API is still unauthenticated; a non-loopback bind requires explicit acknowledgement.
