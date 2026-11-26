# Canonical Market-Series Selection Contract

**Contract:** `atlas.market_evidence.v1`
**Series policy version:** `atlas.market_series.selection.v1`
**Introduced:** Phase 9.2.7
**Implementation:** `src/atlas/market/evidence.py`

## The defect this closes

Phase 9.2.6 made "the price" one decision. It did not make *a price series* one decision.
`market_overview()` still read the raw `bar` table directly:

```python
series = bars.query(security_id, mic, "1990-01-01", iso_date(utcnow()))
latest = series[-1]
previous = series[-2] if len(series) > 1 else None
year_ago = series[-252] if len(series) > 252 else None
```

`BarStore.query` keeps every provider's newest revision. That is correct storage and
wrong selection: with two providers on one session it returns two rows for one date, so

* `latest` and `previous` could be the *same trading date* from two providers;
* `series[-252]` is not one calendar year, and is not even 252 sessions of one provider;
* a session could appear twice in a sparkline;
* a provider correction silently rewrote a historical chart point;
* a provider switch changed a displayed return without any record of the switch.

The chart path (`market_series`) had the same shape: it filtered by venue, not provider.

## The contract

`MarketSeriesSelection` is an immutable record of *which series was selected and why*:

| Field | Meaning |
| --- | --- |
| `policy_version` | `atlas.market_series.selection.v1` |
| `security_id`, `mic`, `interval` | permanent identity and venue; never inferred from a ticker |
| `start`, `end` | the window that was actually queried |
| `information_cutoff` | the information date the selection honoured (`None` for "no cutoff") |
| `policy` | `single_provider_held_constant` or `explicit_source` |
| `points` | ordered `MarketObservation`s, one per trading session |
| `requested_source_id` | the provider a caller demanded, if any |
| `excluded_providers` | providers holding observations in the window that were **not** spliced in |
| `coverage` | sessions, first/last session, requested sessions, missing sessions, revisions |
| `missing_sessions` | sessions the venue calendar says traded but the provider has no observation |
| `limitations` | every comparability caveat, as text, in the response |
| `missing_status` | why the series is empty, when it is |

### Provider policy

The provider is decided **once**, by the canonical price selection at the request's
cutoff (`select_price`), or by an explicit `source_id`. It is then held constant for the
whole window. Sessions the provider does not cover remain missing. They are never filled
from another provider, because a change computed across two providers is not a change in
one observed series.

If a mixed-provider series is ever wanted, it must be an explicit policy with every
switch recorded. It is deliberately not implemented here: no consumer currently claims
that such a series is comparable, and silently producing one is the defect above.

### One observation per session

The query keeps `MAX(revision_seq)` per `(security, mic, interval, session, source)`, then
orders by session. With one provider that is exactly one point per session. A test asserts
`len(points) == len({p.session_date for p in points})` for two providers on one session.

Competing observations and superseded revisions remain stored. The series references the
chosen revision by `observation_id`; the alternatives remain replayable.

## Return conventions

`series_changes(selection, actions, basis=...)` computes one-day and one-year changes on a
declared basis:

| `basis` | What is measured | Label in the response |
| --- | --- | --- |
| `price` | raw close-to-close | "raw close-to-close price change (not adjusted for splits or dividends)" |
| `split_adjusted` | split-adjusted close change | "split-adjusted price change (dividends not reinvested)" |
| `total_return` | total-return index change | "total-return index change (dividends reinvested)" |

`price` is never labelled a total return. `split_adjusted` is never labelled a total
return. A raw change across a recorded corporate action carries an explicit limitation
saying it is not comparable.

### One day

The preceding **distinct session of the same series**. Because the series has one provider
and one point per session, the previous point cannot be another provider's statement about
the same day.

### One year

The last selected session at or before the same calendar date one year earlier
(`last_session - 1 year`, 29 February handled as 28 February). The response reports
`change_1y_target`, the actual `from`/`to` sessions, and `change_1y_span_days`. A series
that does not reach the target returns `change_1y: null` with the reason — it never
substitutes `series[-252]`.

### Corporate actions

Adjustment is delegated to the existing `atlas.market.adjust` operators, which refuse to
adjust anything that is not raw, so an adjustment can never be applied twice. Dividends
enter only the total-return index; the index level is a multiple of 1.0 and is never
presented as a price.

## Where the contract is consumed

| Consumer | Selection | Basis |
| --- | --- | --- |
| `market_overview()` | `select_series`, window = last session − 400 days | `split_adjusted` |
| `market_series()` (chart) | `select_series` over the requested window and cutoff | caller's `view` (`raw` / `split` / `total_return`) |
| `issuer_metrics()` | `select_price` (single observation) | raw price |
| `_security_summary`, X-Ray metrics | `latest_observation` | raw price |
| equity coverage | `latest_observation` | raw price |

Market Overview's `sparkline` is the last 30 points of the same series whose last close and
`price_observation_id` it reports, so the sparkline and the quoted price cannot come from
different selections.

## Historical point-in-time semantics

`issuer_metrics(as_of=...)` answers a different question from `issuer_metrics()`:

* **current** (`as_of` absent): `market_basis = "current_market"`, the latest price against
  the latest accounting evidence, with both dates reported;
* **point-in-time** (`as_of` present): `market_basis = "point_in_time"` and
  `market_cutoff`, and the price must be dated on or before the cutoff. A July price can
  never enter a June run.

A price dated before the cutoff is **not** proof that the vendor revision available on that
date was the one stored now. Atlas preserves its own revisions but not vendor vintage, so
every point-in-time response says so in `notes`. This is a limitation, not a reconstruction.

## Precision and identity

Values are `Decimal` inside the contract and become JSON numbers only at the existing
serialization boundary. Observation identity is computed lazily from the same canonical
decimal text as before, so persisted `MOB-` ids and saved pins are unchanged; a correction
adds a revision, it never rewrites one.

## Known scaling limitation

`market_overview` builds one canonical series per security. Measured on the synthetic
1,000-security tier it costs ~7.6 s cold (24 SQL statements per row, ~4.2 ms of which is the
series itself). The measured bottleneck — per-point identity hashing — was removed
(series 10.5 ms → 4.2 ms); the remaining cost is per-security series construction. A bulk
projection of the same contract (one query for all securities, grouped in Python, asserted
equal to the per-security result) is the next step if the overview must scale past ~1,000
securities.
