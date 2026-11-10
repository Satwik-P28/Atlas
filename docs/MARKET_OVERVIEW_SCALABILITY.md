# Market Overview scalability (Phase 9.2.8)

Status: **the statement-count defect is fixed and proven equivalent; the sub-second target for
1,000 securities was not met, and this document states the measured frontier instead of
claiming it.**

## 1. The defect

Phase 9.2.7 measured the Markets overview at 666 ms for 100 securities and 7,585 ms for
1,000, with roughly 24 SQL statements per security (~24,004 statements for 1,000). The read
model built a canonical series for every security by calling the per-security contract:

| Call per security | Statements |
| --- | --- |
| `master.security()` | 1 |
| `master.listings()` (default venue) | 1 |
| `latest_observation()` → `select_price()` | 2 (row + alternatives) |
| `select_series()` | 2 (points + excluded providers) |
| `TradingCalendar.session_dates()` | 1 |
| `ActionStore.list(computable_only=True)` | 2 (actions + supersession) |
| `master.current_ticker()` | 1 |
| `master.issuer()` | 1 |
| `_source_status()` | 1 |

That is a query-per-item plan for a page whose items share every dimension.

## 2. What was built

`src/atlas/terminal/market_projection.py` is a set-based **execution plan**, not a second
pricing policy. `read_models.market_overview(db, projection="bulk")` is the default and the
HTTP route's behaviour; `market_overview_scalar` keeps the original loop as the executable
definition of the contract, so the change can be proven equivalent rather than asserted.

The plan executes nine statements for any universe size:

1. universe (securities, issuer name, default venue, current ticker);
2. anchors: the winning observation per (security, venue);
3. computable corporate actions;
4. correction chains;
5. excluded providers per (security, venue);
6. trading calendar over the union window;
7. source kinds for `data_status`;
8. series points, streamed in `security_id` order;
9. source catalogue.

Preserved exactly: security and venue identity, provider selection
(`ts DESC, revision DESC, source ASC, mic ASC`), session identity, revision selection,
adjustment convention, corporate actions, source rights, missing observations, provider
conflicts, one-day and one-year returns, sparkline ordering, source status and observation
identity. Returns are still computed by `market.evidence.series_changes` over a real
`MarketSeriesSelection`; observation ids still come from `MarketObservation`.

Three implementation decisions were measured rather than assumed:

* **Index-usable bounds.** `substr(ts_utc,1,10) BETWEEN a AND b` wraps the indexed column,
  so the series scan could not use `(security_id, mic, interval, ts_utc)`. Stored timestamps
  are canonical `YYYY-MM-DDTHH:MM:SSZ`, so the same range is expressed as
  `ts_utc BETWEEN a||'T00:00:00Z' AND b||'T23:59:59Z'`.
* **Revision resolution in Python.** `_LATEST_REVISION_SQL` is a correlated subquery; once
  per candidate row it dominated the fetch. Rows now stream in
  `(security_id, ts_utc, revision_seq)` order and the maximum revision per session is chosen
  while streaming — the identical rule, evaluated once per row instead of once per row per
  query.
* **Streaming consumption.** Rows are consumed in security order and one item is built as
  soon as its rows end, so the plan holds one security's window, not the universe's.

One shared-code shortcut was added and proven: in `series_changes`, a `split_adjusted`
change over a series with **no corporate actions at all** skips the adjustment pass. With no
action there is no split factor, so `split_adjust` would divide every close by
`Decimal(1)` and return the same values in the same order; skipping it is the identical
computation. `test_action_free_split_adjusted_change_equals_the_raw_change` pins the
equality of both bases, and the full corporate-action suite still passes.

## 3. Measured results

Deterministic generator (`scripts/benchmark_market_overview.py`): 260 sessions per security,
a second provider on every tenth security, a revision on every twentieth, no corporate
actions; 2-vCPU reference environment, SQLite in WAL with `synchronous=FULL`; statements
counted at `Database.execute`, so each statement is counted once. Artifact:
`artifacts/phase9_2_8_market_overview.json`.

| Tier | Plan | Statements | Warm median | p95 | Cold | Peak traced memory |
| --- | --- | --- | --- | --- | --- | --- |
| 100 securities (28,610 rows) | scalar | 1,202 | 432.7 ms | 432.7 ms | 442.9 ms | 1.24 MB |
| 100 | bulk | **9** | 430.5 ms | 433.1 ms | 432.0 ms | 0.96 MB |
| 1,000 (286,100 rows) | scalar | 12,002 | 4,829.6 ms | 4,843.8 ms | 4,817.3 ms | 3.95 MB |
| 1,000 | bulk | **9** | 4,294.3 ms | 4,310.2 ms | 4,288.9 ms | 5.05 MB |

* Statement reduction: **133.6×** at 100 securities, **1,333.6×** at 1,000; the count is
  constant instead of linear.
* Latency: **1.01×** at 100, **1.12×** at 1,000 (warm median).
* Correctness parity: **true** at both tiers, compared as whole documents with exact
  equality.
* Peak memory: lower at 100 (1.29×), **higher** at 1,000 (0.78×) — reported as measured.

The Phase 9.2.7 figure of "24 statements per security" counted each statement twice: its
counter wrapped `query`/`query_one`/`execute`, and both of the first two reach `execute`.
The accurate scalar figure at this revision is ~12 statements per security, which is why the
statement reduction is 1,334× rather than 2,667×.

## 4. Why latency did not fall proportionally

Profiling at 100 securities after the projection:

| Stage | Cost |
| --- | --- |
| All nine statements, parse and execute | ~1.4 ms |
| Row transfer (`fetchall` of 28,610 rows) | ~90–170 ms |
| Per-point Python (`MarketObservation.from_row`, `_row_observation`, ordering) | remainder of ~430 ms |

The work that remains is per observation, not per query: roughly **16–25 µs per point**,
paid by both plans because both materialise the same typed observations. At 1,000
securities × 260 sessions that is ~260,000 points and ~4.3 s, which matches the measurement.

**The sub-second cached overview for 1,000 securities was not achieved.** The measured
frontier is 4.29 s warm with 9 statements; the target is 1.0 s. Reaching it requires not
materialising 260,000 observations — for example a bounded windowed projection that returns
only the sparkline sessions and the one-year comparison session, or SQL-side return
computation. That is a different read contract and would need its own equivalence proof, so
it is deliberately **not** smuggled into this checkpoint.

## 5. Complexity and boundaries

* Statements: **O(1)** per request (9), independent of securities, providers and revisions.
* Rows transferred: **O(N × W)** where W is the ~260 stored sessions in the 400-day window;
  only the winning providers' rows are fetched.
* Retained memory: **O(W)** — one security's window at a time.
* No pagination was introduced, so the response remains complete: every security with an
  observation at or before the cutoff is present, and `count` matches `items`.

## 6. Reproduction

```bash
python scripts/benchmark_market_overview.py --tiers 100,1000 --repeats 2 \
  --out artifacts/phase9_2_8_market_overview.json
python -m pytest tests/test_phase9_2_8_bulk_overview.py -q
```

The equivalence suite covers one provider, two disagreeing providers, revision chains, a
second venue, incomplete history, distinct security classes, a split, a dividend, a holiday,
no previous session, no one-year history, a historical cutoff, restricted rights, synthetic
sources, missing corporate actions, a 40-security batch, an empty universe, ordering
stability, source-selection ties, exact observation identities, plus generated scenarios and
an assertion that the statement count does not grow with the universe.
