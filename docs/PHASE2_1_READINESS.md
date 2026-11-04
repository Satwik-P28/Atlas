# Phase 2.1 — Real-data hardening and research readiness

**Status: ready for institutional-research pilots on a single-node, local database.**
This report separates what is real, what is simulated, what has been independently
verified, and what is deliberately unsupported. Every performance number below was
measured in this workspace, not estimated.

## 1. What changed, and what did not

The Phase 2 terminal architecture is preserved: the Temporal Evidence Kernel remains the
only source of facts, selection policy `atlas.select.point_in_time.v2` is unchanged, and
the HTTP API is still a presentation layer over `atlas.terminal.read_models`. Phase 2.1
adds a real-market path, read-path indexes and caching, independent validation, research
views and versioned research-object contracts. No Financial-Economic Compiler or
simulation engine was started.

### Demonstrated defects fixed

| Defect | Fix |
|---|---|
| `BarStore.latest_close` used a correlated `MAX(revision_seq)` subquery per candidate row, scanning the bar table (≈28 ms per call, 1.52 s of a company list) | Indexed newest-row lookup (`ts_utc DESC, revision_seq DESC`) plus migration 004 index |
| Company list ran 2–3 queries per security (N+1) | Batched listings, tickers, coverage, latest closes, evidence/filing counts |
| No invalidation-safe read cache | Generation token from evidence `ingest_seq`, bar/filing/action counts, user-data timestamps, and database identity |
| Screener reported a **unit** (e.g. `USD`) as its `data_status` | Aggregates each row's source status to `reported` / `synthetic` / `mixed` |
| Alpha Vantage serialises absent dates as the string `"None"` | Adapter normalises `"None"`, `""`, `null` to an absent date |

## 2. Real versus simulated data

| Issuer | Fundamentals | Prices / actions | Label |
|---|---|---|---|
| IBM (CIK 0000051143) | SEC EDGAR companyfacts + submissions fixtures | **Alpha Vantage IBM demo feed**, archived under `fixtures/market/` | `reported` |
| Apple, Microsoft, Walmart, Alphabet | SEC EDGAR fixtures | Deterministic synthetic OHLCV and actions | `synthetic` |

Real IBM observations: **6,793 daily bars** from 1999-11-01 to 2026-11-03 on XNYS, and
**114 vendor actions** (splits including the 2021 1.046 adjustment, plus cash dividends).
The source row records the provider, licence, restricted redistribution and retrieval
notes. Each market response carries `data_source`, `data_status`, `real_data`, the last
bar's `observed_at`/`ingested_at`, and explicit limitations.

### Provenance and availability semantics

* Bars are timestamped at the **session close** in `America/New_York`, not at retrieval.
  A daily observation is not knowable during the session.
* Vendor payloads are archived with SHA-256, URL and retrieval time in
  `fixtures/market/alphavantage_manifest.json`; SEC payloads have equivalent manifests.
* Corporate actions carry an availability time derived from the vendor's effective date,
  so a historical request cannot apply an action Atlas learned later.
* No vendor revision history is archived. Re-fetching a changed value creates a new bar
  revision (`supersedes_bar`) rather than overwriting the old observation.
* Actions are **not independently confirmed by an exchange notice**; they are vendor
  terms, including non-integer spin-off adjustments.

## 3. Independent validation

`atlas.research.validation` recomputes values with arithmetic written separately from the
functions under test. IBM currently reports **233/233 checks passing** (`verified`),
including:

* net, gross and operating margins; ROE; total debt; free cash flow; market cap;
  enterprise value; P/E × earnings yield = 1;
* adjusted close = raw close ÷ cumulative split factor for every bar in a five-year window;
* total-return index rebuilt from prices, split factors and dividends;
* action uniqueness, positive dividend amounts and positive split factors.

Tolerances are explicit: decimals exact, adjusted prices `$0.011` (rounding), ratios
`1e-9`. A check lists expected, actual, difference, tolerance and evidence ids. Passing
proves consistency with the declared formulas; it does not prove the vendor data is
error-free.

## 4. Measured performance

Environment: Linux container, 2 vCPU, 3.8 GB, Python 3.12.3, SQLite (WAL,
`synchronous=FULL`). Phase 2 baseline and Phase 2.1 results use the same machine class.

### Real terminal database (5 issuers, 8 securities, 17,363 bars, 23,583 evidence)

| Operation | Phase 2 baseline | Phase 2.1 | Change |
|---|---:|---:|---:|
| Company list, cold | 1,341 ms | **48.3 ms** | −96.4% |
| Company list, cached | not cached | **8.7 ms** | — |
| Screener, 5 issuers | 3,285 ms | **1,604 ms** | −51.2% |
| IBM 5Y market series, 1,255 bars | 28 ms (1Y synthetic baseline, not comparable) | **387 ms** | — |
| Independent validation, IBM | none | **1,200 ms** (233 checks) | — |

The screener is now dominated by per-issuer point-in-time metric selection (≈1.5 s),
not SQL. The API caches time-relative screens for 60 s and explicit as-of screens
indefinitely within a generation; peer comparisons are cached for 120 s.

### Scale benchmark (`scripts/benchmark_scale.py`)

Disposable in-memory databases, one security per issuer, 180 calendar days of synthetic
bars, no financial facts. This isolates read-model/kernel overhead, not real evidence
selection.

| Issuers / securities | Bars | Companies cold | Companies cached | Screener | Market series |
|---:|---:|---:|---:|---:|---:|
| 5 / 5 | 640 | 1.1 ms | 0.1 ms | 1.5 ms | 4.9 ms |
| 25 / 25 | 3,200 | 2.5 ms | 0.1 ms | 4.6 ms | 3.7 ms |
| 100 / 100 | 12,800 | 9.6 ms | 0.1 ms | 19.7 ms | 3.6 ms |
| 300 / 300 | 38,400 | 30.5 ms | 0.2 ms | 84.6 ms | 3.5 ms |

Raw output: `artifacts/bench_phase21.json`. Command:
`.venv/bin/python scripts/benchmark_scale.py --repeats 2`.

## 5. Research experience

Company → **Research** adds:

* annual financial history with evidence-linked points and no interpolation;
* peer comparison across every issuer in the database, with target highlighting and
  medians over companies that actually report each input;
* restatements/amendments with the superseded value retained;
* the independent validation report with per-check status.

Peer medians are explicitly **not an industry index**; the universe is the local database.

## 6. Universal Research Object contracts

`atlas.research.objects` defines **`atlas.research_object.v1`** for five kinds:
`dataset`, `model`, `experiment`, `strategy`, `application`.

* Required fields are validated, top-level unknown fields rejected, versions must be
  semver, and each kind has required `spec` fields.
* Code-like keys (`code`, `sql`, `python`, `javascript`, `executable`, `script`, `lambda`)
  are rejected anywhere in the document. Objects are declarations, not execution.
* Every object cites evidence ids checked against the kernel; links live in
  `research_object_evidence` with foreign keys.
* Reads return linked evidence and **reverse dependency** computations from the existing
  `DependencyIndex`; X-Ray now includes `research_impact`.
* Documents are immutable by `(owner, kind, name, version)` and content-hashed.
  A change requires a new version.

No simulation, backtesting or model execution is implemented.

## 7. Migration, offline and error handling

* Migration **004** is additive: two bar indexes, an evidence index, two research-object
  tables and their indexes. A v3 database upgrades in place; a test inserts issuer and
  setting rows at v3, migrates to v4 and verifies both survive.
* The full backend suite and browser fixtures run offline from archived SEC and Alpha
  Vantage payloads. The terminal requires no network after the database is built.
* The browser suite exercises a visible API-failure state, an empty/missing database
  (`503 database_missing`), and mobile layout at 390×844 with no horizontal overflow.

## 8. Verification performed

| Check | Result |
|---|---|
| Backend pytest suite | **313 passed** (offline) |
| Frontend Vitest | 4 passed |
| Frontend production build | passed |
| Browser journeys | **12/12 passed**, screenshots `artifacts/01`–`13` |
| IBM independent validation | **233/233**, status `verified` |
| Scale benchmark | 5 → 300 issuers completed |
| Schema | v4, integrity check `ok` |

Reproduce:

```bash
.venv/bin/python scripts/build_terminal_db.py --db var/atlas.db --force
.venv/bin/python -m pytest -q
cd web && npm run build && npm test -- --run
.venv/bin/atlas --db var/atlas.db serve --host 0.0.0.0 --port 8000
cd web && LD_LIBRARY_PATH=../.pwlibs/sysroot/usr/lib/x86_64-linux-gnu \
  FONTCONFIG_FILE=$PWD/../.pwlibs/fonts.conf node e2e/journeys.mjs
```

The browser environment needs local fonts; the config used here is `.pwlibs/fonts.conf`.
Without usable fonts Chromium lays out text at zero size and interaction tests fail.

## 9. Readiness matrix

| Capability | State | Evidence |
|---|---|---|
| Real historical daily prices for IBM | **Real, verified** | 6,793 AV bars, `reported` |
| Real SEC fundamentals for 5 issuers | **Real, verified** | 23,583 evidence records |
| Splits/dividends for IBM | **Real vendor terms, not exchange-confirmed** | 114 actions |
| Technical indicators | **Verified within the terminal suite** | 9 indicators, formula/version |
| Financial ratios and trailing valuations | **Independently recomputed** | 233 IBM checks |
| Point-in-time reconstruction | **Verified** | kernel tests + as-of journey |
| Peer comparison / history / revisions | **Working, local universe** | research tab + API |
| Research-object contracts | **Working, versioned, non-executable** | v1 schema + tests |
| Market-wide screens | **Unsupported** | universe is local DB |
| Live/intraday feeds | **Unsupported** | archived EOD only |
| Production vendor licensing | **Unsupported** | demo key restricted to IBM |
| Backtesting / simulation / model execution | **Deliberately out of scope** | no engine |
| Multi-user auth / tenancy | **Unsupported** | local-first single owner |

## 10. Remaining risks and next work

1. **Screener latency** is still ≈1.6 s for 5 issuers because each issuer runs a full
   point-in-time selection. Materialising per-issuer latest metrics keyed by evidence
   generation is the next optimization; it needs its own invalidation tests.
2. **Default list width** is 200 issuers in `list_companies` (API may request up to 500).
   Large-universe UI pagination is not implemented.
3. **Real-data coverage** is one issuer for prices. Adding licensed feeds must preserve
   the archived-payload and source-metadata discipline demonstrated here.
4. **Validation window** is five years for market checks to stay below the browser
   downsample threshold; earlier IBM history is stored but not part of the pass count.
5. **Vendor revision history** is absent; Atlas revisions are its own ingest revisions.
6. **Browser fonts** are an environment dependency, now documented and configured
   locally; CI images should install fonts explicitly.
