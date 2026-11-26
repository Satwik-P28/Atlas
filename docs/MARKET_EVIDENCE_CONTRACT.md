# Market Evidence Contract

Status: implemented in `src/atlas/market/evidence.py`, contract version
`atlas.market_evidence.v1`, selection policy version `atlas.market_price.selection.v2`.

## 1. The duplication this replaces

"The price of a security on a date" was answered in three places:

| Consumer | Before | Chosen by |
| --- | --- | --- |
| Price summary, price history, equity market context | `research/prices._selected_row` | policy `latest_session` / `latest_revision` / `explicit_source` / `pinned`, provider-deterministic |
| Markets page, security lists | `read_models._security_summary` → `BarStore.latest_close` | `ORDER BY ts_utc DESC, revision_seq DESC` for one venue, no provider tie-break |
| Issuer metrics and X-Ray | `read_models.issuer_metrics` → `BarStore.latest_close` | the same query, a second time |
| Equity coverage label | a third inline `SELECT … FROM bar … ORDER BY b.ts_utc DESC` | newest row of any source |

The three queries usually agreed, which is why the duplication survived. They disagree
exactly when it matters: two providers report the same session, a provider corrects a
session, a security has two venues, or a saved analysis pins an older revision. Two
accepted defects in Phase 9.2.4 (a Markets value that did not match the observation
inspector, and a market-cap value with no observation identity) were consequences.

There is now one engine, `evidence.select_price`, and every consumer calls it.

## 2. The three typed records

### `MarketObservation` (immutable)

One provider's statement about one security, venue, session and revision:

- permanent security identity (`security_id`), venue (`mic`), interval, session timestamp;
- raw OHLCV as `Decimal`, plus the canonical decimal text used for hashing;
- currency and adjustment convention (only raw observations are stored);
- provider (`source_id`), dataset/source name, licence, redistribution class, source kind;
- revision sequence and the revision it supersedes;
- retrieval and ingestion timestamps;
- `observation_id` (`MOB-…`) and `content_hash` computed by
  `atlas.research.observations` — unchanged by this phase, so saved pins remain valid;
- derived `export_allowed` and `rights_class`.

`to_pin()` emits the lawful reference without the value. `to_dict()` is the existing
observation payload.

### `PriceSelection` (immutable)

The recorded *decision*:

- policy (`latest_session`, `latest_revision`, `explicit_source`, `pinned`) and its version;
- information cutoff (never the `2999-12-31` sentinel);
- the selected observation, or `None`;
- requested constraints (`source_id`, `mic`) and the constraints actually applied;
- competing observations at the same session, and whether they conflict;
- rationale, `missing_status`, `exact_replay`, and `exact_replay_eligible`;
- `to_legacy()` — the single translation to the published JSON shape.

A selection never says "latest price". It says which session, provider and revision it
chose, and why.

### `MarketComparison` (immutable)

A model output against one selection: valuation date, accounting period, model version,
mixed-date flag and day gap, currency, look-ahead rejection, source restrictions, implied
metrics and explicit uncertainty notes. `compare_model_to_market` refuses to compare a
model with a price after the information cutoff.

## 3. Selection semantics

| Policy | Basis | Tie-break |
| --- | --- | --- |
| `latest_session` | newest session at or before the requested date, newest revision of that session | `source_id ASC, mic ASC` |
| `latest_revision` | newest ingestion first — "latest import", not "latest information" | `ts_utc DESC, revision_seq DESC, source_id ASC` |
| `explicit_source` | newest session from one named provider | `ts_utc DESC, revision_seq DESC, mic ASC` |
| `pinned` | the exact revision a saved analysis recorded | none — exact or unavailable |

Only the newest revision of a session participates; superseded revisions stay stored and
are reachable through their pin. A pinned revision that no longer resolves returns
`exact_revision_unavailable` with `price: null`; the latest observation is never
substituted.

Missing data is a value, not an absence: `MISSING_NO_OBSERVATION` when nothing exists at or
before the cutoff, `MISSING_FILTERED` when the requested provider or venue excludes every
candidate. No consumer fills a gap with another provider, an undated quote or a synthetic
series.

## 4. Numerical precision

- Values are `Decimal` inside the contract. `Decimal` is parsed from the stored decimal
  string, never from a `float`.
- `close_decimal_text` is `canonical_decimal(close)` — the exact text the content hash was
  computed over. Formatting changes cannot silently invalidate a persisted `MOB-` id.
- Public JSON keeps its existing types: `close` and `latest_close` remain JSON numbers, so
  no client breaks. The typed layer is internal.
- `MarketComparison.price_close` returns the `Decimal`; any float conversion happens only
  where the existing response already used one.

## 5. Consumers

| Consumer | Uses |
| --- | --- |
| `prices.price_summary` / `price_history` / `price_on_or_before` | `select_price`, `to_legacy` |
| `read_models._security_summary`, `_batch_security_summaries` | `latest_observation` |
| `read_models.issuer_metrics` (X-Ray) | `latest_observation`; payload carries `price_observation_id`, `price_source_selection`, and every derived-market metric carries `price_observation_id` |
| `EquityResearchService._issuer_coverage` | `latest_observation` for the price-source label |
| Equity market context and valuation | `price_on_or_before` / `price_for_pin` (unchanged signatures) |

`BarStore.latest_close` still exists for range queries and is no longer used to decide
which observation represents "the price".

## 6. Rights

`research/rights.classify` is the single decision contract. `applications/rights` now
consumes it instead of keeping a parallel table:

- `public_domain`, `project_authored`, `permitted` → ingest, analyse, package, export;
- `restricted`, `user_responsibility`, `private` → ingest, store and analyse locally only;
- unknown or incomplete → **no action permitted** (previously the applications engine
  allowed local actions for an unknown class, which contradicted the research engine).

A permissive copyright licence is not a public-domain dedication: declaring
`public_domain` with `Apache-2.0` downgrades to `project_authored`. A restricted
observation may be used in local analysis without gaining redistribution rights, and a
portable package that references one is refused.

## 7. API compatibility

No existing response type changed. Two additive fields were introduced where the mission
requires the price to link to its immutable observation:

- `issuer_metrics.price_observation_id` and `issuer_metrics.price_source_selection`;
- `price_observation_id` on each `derived_market` metric (`market_cap`, `pe`, `ps`,
  `earnings_yield`, `fcf_yield`, `book_to_market`, `ev`, `ev_revenue`).

Both are additive; no field was removed, renamed or retyped. Selection dictionaries keep
the exact key set and ordering they had under `atlas.market_price.selection.v2`.

## 8. Not supported

- Intraday intervals: only `1d` observations participate.
- Adjusted observations as stored data: adjusted series are derived on read.
- Provider failover: a selection never falls back to a different provider.
- "Latest price" as a concept: use `latest_session` and read the recorded basis.
