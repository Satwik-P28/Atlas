# ADR 0006 — Market data and adjustment conventions

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

Price series are where financial data platforms most often corrupt history: adjusted
prices overwrite raw ones, split factors are applied twice, dividends are labelled as
prices, or a split announced after a backtest's decision date is applied retroactively.

## Decision

### 1. Raw observations are immutable

`bar` rows are keyed by `(security, mic, interval, ts_utc, source, revision_seq)`.
Re-ingesting identical data is a no-op. A provider correction appends `revision_seq + 1`
and sets `supersedes_bar`; the original row is never modified. Queries default to the
latest revision and can request all revisions.

### 2. Suspicious data is flagged, never repaired

Impossible OHLC relationships, non-positive prices, negative volume, VWAP outside the
range, observations on non-session dates, missing sessions and unexplained large moves
become quality flags and `data_quality_issue` rows. Values are stored exactly as
received. During development this caught a genuine error in my own synthetic fixture
(a close above its high), which is the behaviour we want from a validator.

### 3. Adjusted series are derived views with explicit semantics

* **Split-adjusted**: `price_adj = price_raw / factor`,
  `volume_adj = volume_raw × factor`, where
  `factor(bar) = Π ratio_to/ratio_from` over splits with `ex_date > bar_date`.
  The reference-date bar is unchanged, and `adjusted × factor == raw` exactly.
* **Total return**: an **index** (base 1.0), never a price:

  ```
  TR[t] = TR[t-1] × (adj_close[t] + div_adj[t]) / adj_close[t-1]
  div_adj[t] = cash_amount / split_factor(ex_date)
  ```

  Calling a dividend-adjusted number a "price" invites exactly the error the brief
  forbids, so the API returns `total_return_index` alongside split-adjusted prices and
  labels the series `total_return_adjusted`.

### 4. Adjustments can be knowledge-filtered

`knowledge_as_of` restricts applied actions to those with evidenced availability at or
before that instant; withheld actions are listed in the result. A backtest can therefore
reproduce what was knowable, not what is known now.

### 5. Never twice

Only `adjustment_status == 'raw'` bars may be adjusted. Passing an adjusted series raises
`ValidationError`; ingestion refuses non-raw bars outright.

### 6. Action scope is explicit

Computable: `split`, `reverse_split`, `cash_dividend`. Recorded but not computed:
`merger`, `spin_off`, `distribution`, `ticker_change` (identity event applied through the
master, not a price adjustment). Attempting to compute an unimplemented type raises
`UnsupportedActionError` instead of producing a plausible wrong number.

### 7. Calendars are stored, not inferred

Sessions come from a rule-based NYSE/Nasdaq generator (weekends, standard holidays as a
function of year, Juneteenth from 2022, 13:00 ET early closes) stored per venue with UTC
instants from `America/New_York`, so DST is handled by the zone database. Gaps and
off-calendar observations are reported, never interpolated.

## Consequences

* Two independent views (`split`, `total_return`) are always distinguishable from raw and
  from each other; a researcher cannot accidentally compare them.
* Revisions and corrections are fully auditable.
* Rule-based calendars are wrong for unscheduled closures (weather, mourning days). This
  is documented, and validation surfaces bars that fall outside the rules so the gap is
  visible rather than silent.
* Volume adjustment is conventional (`× factor`) but not universal; it is documented and
  tested rather than assumed.

## Alternatives considered

* In-place adjusted prices: rejected — destroys the source and makes double adjustment
  undetectable.
* Vendor "adjusted close" as the stored close: rejected — it mixes split and dividend
  adjustments and hides which basis was used.
* Inferring sessions from observed bars: rejected — it makes every provider gap look like
  a holiday and every holiday look like a data error.
