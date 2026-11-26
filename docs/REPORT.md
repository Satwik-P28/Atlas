# Phase 1 technical report (revised for Phase 1.1)

**Date:** 2026-11-04 (Phase 1: 2026-11-03)
**Scope:** Atlas Quant Phase 1.1 — financial data and temporal evidence foundation
**Status:** implemented, tested, demonstrated. Phase 1.1 added complete SEC filing
history, an independent reconciliation path, a persistent reverse dependency index, and a
measured SQL selection engine (correct, slower, therefore not adopted). Not everything in
the brief is complete; §8–§11 state exactly what is not.

---

## 1. Executive summary

Phase 1 delivers a working, tested, local-first financial data platform with five
integrated capabilities (SEC data, market data, corporate actions, security master,
temporal evidence kernel) and a developer interface that demonstrates them end to end.

Measured against real data and verified offline:

| Fact | Value |
|---|---|
| Source code | 11,382 lines (`src/atlas`), 3,965 lines of tests |
| Automated tests | **258, all passing, no network required** |
| Schema | v2, 22 tables, append-only versioned migrations |
| Real SEC data | 4 issuers: Apple, Microsoft, Walmart, Alphabet (13,977 filings stored) |
| Concept coverage (Apple) | 31 of 32 canonical concepts; 474 unmapped elements reported, not guessed |
| Availability quality (Apple) | **5,737 facts exact** (SEC acceptance timestamp), 0 date-precision, 0 unknown |
| Independent reconciliation | 5,737/5,737 Apple observations re-derived from the source, 0 mismatches |
| Isolation | zero runtime dependencies (Python stdlib only) |
| Acceptance tests A–H | all eight executed and passing (see §5) |

---

## 2. What was implemented

### 2.1 Domain contracts (`atlas.core`)

* Deterministic, prefixed identifiers for issuers, securities, listings, ticker
  assignments, identifiers, evidence, filings, actions, raw documents, quality issues.
* Exact decimal money/quantity with typed units; binary floats rejected at the boundary.
* Four-way time model (reporting period, effective interval, publication, observation)
  with `Availability` carrying precision and evidence basis.
* 32-concept registry with ordered XBRL tag priorities, unit kinds, period types, sign
  policies, notes and three declared derivations.
* Typed error hierarchy with stable codes and context (no string parsing at call sites).

### 2.2 Storage (`atlas.storage`)

* SQLite with WAL, `synchronous=FULL`, `foreign_keys=ON`, busy timeout.
* Append-only versioned migrations applied transactionally and recorded; refuses a
  database newer than the binary.
* Nestable transactions (SAVEPOINT) so ingestion composes without early commits.
* Source registry with licence/redistribution metadata; raw document store with SHA-256,
  ETag and retrieval time.
* Data-quality issue log with stable codes, severities and resolution.

### 2.3 Temporal evidence kernel (`atlas.evidence`)

* Immutable evidence records covering value, units, full reporting period, taxonomy
  element, source document, filing/acceptance time, evidenced availability,
  observation time + monotonic ingest order, revision kind, derivation kind/rule, quality,
  verification, limitations and transformation lineage.
* Idempotent ingestion keyed on content hash; explicit identity-collision detection.
* Supersession only when the value changes; append-only, traversable in both directions.
* Point-in-time selection answering two distinct questions (public availability vs Atlas
  ingestion), with completeness, exclusion counts and contradiction reporting.
* Provenance (Financial X-Ray): structured report plus narrative from value back to raw
  document, including derived-input evidence ids.

### 2.4 Entity master (`atlas.entities`)

* Issuer → security → listing → ticker hierarchy with time-bounded ticker and identifier
  assignments carrying confidence and status.
* Inspectable resolution returning `confirmed | probable | ambiguous | none` with
  reasoning; simultaneous claims raise rather than guessing.
* Ticker change, reuse, delisting, multi-class issuers, conflicting identifiers,
  corporate relationships.

### 2.5 SEC ingestion (`atlas.ingestion`)

* Fair-access-compliant client: mandatory contact User-Agent, host allowlist, token-bucket
  rate limit (default 5/s), bounded exponential backoff with jitter and `Retry-After`,
  loud 403 handling, raw-document caching with conditional requests.
* Parsers for `submissions` (issuer metadata, 1,001 filings, acceptance timestamps,
  amendments, unfetched-history reporting) and `companyfacts` (canonical mapping, unit
  typing, deduplication, contradiction detection, amendment marking, availability
  precision).
* Orchestration that ingests submissions first (so acceptance timestamps upgrade fact
  availability to exact), then facts in a single transaction, and links cover-page tickers
  with honest confidence.

### 2.6 Market layer (`atlas.market`)

* Rule-based NYSE/Nasdaq calendars stored per venue with UTC instants and early closes.
* Immutable OHLCV bars with provider-revision rows, structural quality flags and dataset
  validation (OHLC, volume, duplicates, gaps, off-calendar dates, unexplained moves).
* Corporate actions: splits, reverse splits, cash dividends, ticker changes; corrections
  append-only; mergers/spin-offs/distributions recorded but explicitly not computed.
* Adjustment engine: split-adjusted prices/volumes, dividend-reinvested total-return
  index, knowledge-time filtering, double-adjustment refusal, continuity verification.
* CSV and optional Parquet import with column aliasing, adjusted-column refusal, session
  timestamping and per-row issue reporting.

### 2.7 Interface, validation, operations (`atlas.cli`, `atlas.validation`, `atlas.demo`)

* 19 CLI commands across init, SEC sync/filings/history, entity inspection, facts/as-of,
  explain, reconcile, deps, bars import/show/validate, actions list/add, validate, stats,
  concepts, demo.
* Dataset integrity validation: schema version, foreign keys, temporal invariants, unit
  consistency, conflicts within filings, supersession graph cycles/dangling edges, ticker
  overlap, action semantics, bar integrity and calendar conformance.
* Offline demonstration executing the acceptance scenarios with real SEC data plus clearly
  labelled synthetic market/identity fixtures.

### 2.8 Phase 1.1 hardening

**Complete filing history.** `SecIngestor` now follows every archive in `filings.files`,
with `--no-history` / `--history-limit` for explicit shallow syncs. Archives are stored as
raw documents, hashed, and skipped when unchanged, so repeated syncs do no parsing work.
Coverage (`expected`, `recorded`, `missing`, advertised vs stored rows) is reported, and a
shortfall is an explicit issue. The archive layout is *not* the layout of `recent` — the
live files are a flat map of parallel arrays with no `filings` wrapper — and tests assert
that against four real issuers.

Measured effect on Apple: filings 1,001 → **2,272**; facts with exact availability
3,740 → **5,737**; date-precision facts 1,997 → **0**.

**Adversarial temporal audit.** Three defects were found and fixed:

1. `atlas_ingested` mode fetched unknown-availability records twice (as known and as
   excluded) and reported them as a coverage gap although it had selected them. Under
   ingestion-time semantics the observation time is the evidenced instant, so they are now
   knowable and counted once.
2. Contradictions at identical availability were adjudicated by quality alone, which could
   discard a correction that arrived with the same acceptance timestamp as the original.
   Adjudication now prefers the revision-chain tip, then quality, then ingestion order, and
   names the selected record in the contradiction report.
3. Selection ranking was implicit. Policy v2 states and tests it, and two independent
   implementations exist.

**Independent reconciliation.** `atlas reconcile` re-derives the expected observation set
from the raw payload with its own tag walk and decimal conversion, then compares values,
presence in both directions, period/fiscal metadata, duration starts, amendment marking,
and availability evidence (exact equals acceptance time; date equals end-of-day UTC).
Apple: 5,737/5,737 verified, 0 errors, 3,238 expected `period_end` vs cover-page
`reportDate` warnings. Each check is tested by corrupting storage with direct SQL.

**Reverse dependency index.** Schema v2 adds `computation` / `computation_input`.
`DependencyIndex` records computations automatically when a derived record with lineage
inputs is ingested, backfills older records, and answers direct/transitive dependents,
stale inputs (superseded or missing), impact, and integrity findings. Phase 1.1 does not
implement the compiler; it builds the index the compiler will use.

**SQL selection engine.** Implemented with window functions and proven equivalent to the
Python path by differential tests (randomised histories, adversarial scenarios, the real
Apple payload across modes and statements). Measured slower (235.8 vs 154.6 ms for all
concepts; 35.3 vs 22.4 ms for four), so it is available but not the default.

---

## 3. Architecture decisions

Ten ADRs in `docs/adr/`:

1. **Python core + SQLite** — no Rust toolchain in the environment; zero runtime
   dependencies; `Decimal` and explicit invariants instead of compile-time types. Rust is
   the right long-term choice for a compute core; deferred with criteria.
2. **Identity conventions** — issuer/security/listing/ticker separation; ticker is
   time-bounded and never part of a security id.
3. **Storage engine** — SQLite as system of record (`WAL`, `synchronous=FULL`, FKs on);
   columnar/DuckDB and Parquet export deferred with an explicit migration path.
4. **Temporal evidence model** — immutable records, four times, evidenced availability
   with conservative end-of-day handling, two explicit query modes, supersession only on
   change, ingestion-order tie-break, versioned selection policy.
5. **XBRL normalisation** — closed registry, ordered priorities, no fuzzy matching,
   original element preserved, units typed, currencies separated, sign policy declared,
   derivations rule-stamped.
6. **Market data and adjustment** — raw immutability, flagged-not-fixed validation,
   documented split/return mathematics, knowledge-filtered actions, no double adjustment,
   stored calendars.
7. **Scope and Phase 2 contract** — what Phase 1 owns, what it deliberately does not, and
   the rules later phases must follow.
8. **SEC filing history** — fetch `filings.files` archives, parse their distinct layout,
   sync incrementally by content hash, and report coverage instead of assuming it.
9. **Selection policy v2 and dual engines** — explicit ranking, chain-aware contradiction
   adjudication, ingestion-mode fix; SQL implementation differentially proven and measured,
   not adopted because it was slower.
10. **Reverse dependency index** — `computation` / `computation_input` as the indexed
   projection of lineage, with precise staleness semantics for the future compiler.

---

## 4. Commands

```bash
# setup
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# verification
.venv/bin/python -m pytest -q                  # 258 tests, offline
.venv/bin/python benchmarks/bench.py --json benchmarks/out/bench.json

# demonstration (offline, real SEC fixtures)
.venv/bin/atlas demo

# live SEC ingestion (needs contact User-Agent)
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
.venv/bin/atlas sec sync --cik 320193
.venv/bin/atlas sec filings --cik 320193 --form 10-K --limit 10

# research queries
.venv/bin/atlas facts --cik 320193 --statement cashflow
.venv/bin/atlas asof --cik 320193 --date 2024-06-01 --concept revenue
.venv/bin/atlas explain --evidence-id EV-...            # full X-Ray
.venv/bin/atlas entity show --ticker AAPL --as-of 2020-01-01
.venv/bin/atlas entity show --cik 320193

# market data
.venv/bin/atlas bars import --file fixtures/market/aapl_split_bars.csv \
    --security-id SEC-... --mic XNAS
.venv/bin/atlas actions add --security-id SEC-... --type split --ex-date 2020-08-31 \
    --ratio 4:1 --available-at 2020-08-28T20:30:00Z
.venv/bin/atlas bars show --security-id SEC-... --mic XNAS \
    --start 2020-08-01 --end 2020-09-30 --adjustment total_return
.venv/bin/atlas bars validate --security-id SEC-... --mic XNAS

# operations
.venv/bin/atlas validate
.venv/bin/atlas stats
.venv/bin/atlas concepts
```

Every command accepts `--json` (place before the subcommand) for machine-readable output.

---

## 5. Acceptance tests — actual results

All eight ran successfully against the committed code and fixtures. Evidence is in
`tests/test_acceptance.py` (automated) and the `atlas demo` transcript.

| Test | Result | Evidence |
|---|---|---|
| **A. Company research** | **PASS** | Apple, 1,001 filings, 5,737 facts; each selected fact exposes period, unit, accession, original element, availability; 3,740 exact-precision, 1,997 date-precision, 0 unknown |
| **B. Historical reconstruction** | **PASS** | Synthetic 10-Q (100,000,000 USD, accepted 2024-05-01T16:05:12Z) and 10-Q/A (90,000,000 USD, accepted 2024-08-15T20:31:44Z): as-of 2024-06-01 returns 100,000,000 with 1 record withheld; as-of 2024-09-01 returns 90,000,000; both versions retained; no leakage |
| **C. Security identity** | **PASS** | Ticker change closes the old assignment on the effective eve; reused ticker resolves to different security ids by `as_of`; the gap between owners resolves to nothing; simultaneous claims raise `AmbiguousResolution` |
| **D. Corporate actions** | **PASS** | 8 raw bars; 4-for-1 split on 2020-08-31: 499.23 → 124.8075 adjusted, volume ×4, post-split bars unchanged, `adjusted × factor == raw`, continuity check 0 discrepancies, raw rows byte-identical after deriving views |
| **E. Financial X-Ray** | **PASS** | Apple `capex` 6,799,000,000 USD: element `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, filing 0000320193-26-000020 (10-Q), accepted 2026-07-31T10:01:02Z, rule `atlas.normalize.magnitude_outflow.v1`, raw document SHA-256 linked |
| **F. Incremental update** | **PASS** | Second sync: 0 inserted, 5,737 duplicates, evidence count unchanged; corrected source value creates a third superseding record while history (100M → 90M → 89M) is preserved and the pre-restatement as-of still returns 100M |
| **G. Offline reproduction** | **PASS** | Full suite runs with no network; SEC payloads archived; a `SecClient` given an exploding transport is never able to reach it; fixtures documented with provenance |
| **H. Reliability** | **PASS** | `KeyboardInterrupt` mid-ingestion rolls back to 0 evidence rows; database reopens with `PRAGMA integrity_check = ok`; retry ingests successfully with no manual repair |

---

## 6. Test suite composition

258 tests, all offline:

* **core** — identifier normalisation, unit typing, decimal canonicalisation, time
  semantics, concept resolution, period invariants.
* **evidence** — idempotency, immutability, supersession vs re-assertion, both temporal
  modes, date-precision conservatism, unknown-availability exclusion and reporting,
  contradictions, tier precedence, period/unit separation, pagination, provenance.
* **entities** — ticker change/reuse/gaps/overlap, multi-class issuers, delisting,
  identifier conflicts, relationships, listing prerequisites.
* **SEC** — submissions and facts parsing on real payloads, unit-kind rejection, currency
  separation, magnitude-outflow flagging, deduplication, in-filing contradictions,
  unmapped tags, sync idempotency, correction preservation, client policy/retry/cache/rate
  limit/host allowlist.
* **market** — holiday and early-close rules (including Juneteenth from 2022), DST, gaps,
  immutable bars and revisions, structural flags, non-session detection, split/reverse
  split/cumulative factors, double-adjustment refusal, knowledge filtering, total-return
  mathematics, hand-computed reference checks.
* **storage** — migration idempotency, restart persistence, rollback, nested savepoints,
  foreign keys, quality-log dedupe, validation detectors (invalid OHLC, missing
  availability, ticker overlap, supersession cycles).
* **CLI** — every documented command executes; as-of output proves no leakage; bars
  import/show/validate; error paths return status 2 without tracebacks.
* **properties** — decimal round-trip, timestamp round-trip, split factor algebra,
  monotonic factor ordering.
* **history** — real archive layouts for four issuers, object-list variants, count
  mismatches, content-hash checkpointing, incremental skip without availability
  regression, coverage reporting when archives are absent.
* **selection engines** — differential equivalence over randomised and adversarial
  histories plus the real payload; date-boundary conservatism, simultaneous corrections,
  backfills, ingestion-mode unknown availability, tier precedence.
* **reconciliation** — clean Apple and synthetic payloads, plus deliberate corruption of
  value, presence, amendment marking, period start and availability.
* **dependencies** — automatic indexing, transitive traversal, staleness after supersession
  (but not after re-assertion), idempotent recording, rejection of non-derived outputs,
  missing inputs and self-reference, backfill and structural integrity.
* **multi-issuer** — Microsoft, Walmart and Alphabet: fiscal calendars, multi-class
  provisional identity, industry-specific coverage, reconciliation, whole-dataset validation.
* **determinism** — byte-identical replay of the same payload into fresh databases, stable
  as-of answers, Parquet/CSV equivalence, column-alias independence, two providers keeping
  separate raw series.
* **acceptance** — the eight scenarios above.

### Defects found and fixed during this build (now regression-tested)

| Defect | Impact | Fix | Regression test |
|---|---|---|---|
| Evidence identity omitted `period_start` | Annual and quarterly facts sharing an end date collided on insert | Added `period_start` to the identity tuple | `test_annual_and_quarterly_periods_coexist` |
| Supersession recorded for unchanged re-assertions | Misrepresented source history; inflated revision counts (5,737 → 283 genuine links) | Supersede only when the value changes | `test_unchanged_value_keeps_earliest_evidence` |
| Cycle detector flagged every supersession as a cycle | 6,077 false validation errors | Corrected path-ancestry check | `test_validation_detects_supersession_cycle` |
| Corrections with identical availability ordered by hash | Nondeterministic "latest" value | Added monotonic `ingest_seq` tie-break | `test_sync_preserves_history_when_source_value_is_corrected` |
| Multi-currency observations were not distinguished | Risk of mixing EUR and USD revenue | Separate facts per currency + `multi_currency_concepts` report | `test_restatement_payload_keeps_currencies_separate` |
| Synthetic market fixture closed above its high | Would have silently entered test data | Validator flagged it; fixture corrected | `test_invalid_ohlc_is_flagged` |
| History archives parsed with the `recent` layout | Real archives yield zero filings while reporting success | Dedicated layout detection (`parallel_arrays` / `object_list`) and tests against four real issuers | `test_parse_real_archive_uses_top_level_parallel_arrays` |
| `atlas_ingested` counted unknown-availability records twice | Duplicate facts and a false coverage gap | Treat ingestion time as the evidenced instant for unknown-availability records | `test_atlas_ingested_mode_includes_unknown_availability_exactly_once` |
| Contradiction adjudication ignored the revision chain | A correction with the same acceptance timestamp could be discarded for an older value | Adjudicate by chain tip, then quality, then ingestion order; report the selection | `test_simultaneous_corrections_are_adjudicated_and_reported` |
| Adjusted-only CSV raised "missing columns" | The real reason (refusing a derived price series) was hidden | Specific `NotSupportedError` before the generic column check | `test_adjusted_only_file_is_refused` |

---

## 7. Measured performance

Hardware: 2 vCPU, 3.8 GB RAM, Linux 6.1, Python 3.12.3, SQLite 3.45.1, WAL with
`synchronous=FULL`. Full methodology in [BENCHMARKS.md](BENCHMARKS.md).

Latest measurment (run 3), with the two earlier runs in `BENCHMARKS.md`. Medians of 5.

| Benchmark | Median |
|---|---|
| SEC company ingestion (505 elements → 5,737 facts, incl. create+migrate) | 4,387 ms |
| Statement query, 4 concepts | 22.9 ms |
| Selection, all concepts — Python engine (default) | **154.6 ms** |
| Selection, all concepts — SQL engine | 235.8 ms |
| Selection, 4 concepts — Python / SQL | **22.4 ms** / 35.3 ms |
| Revision history, one concept | 2.3 ms |
| Provenance traversal | 0.15 ms |
| Daily bar load, 1,250 bars | 40.2 ms |
| Multi-year bar query (1,250 bars) | 11.1 ms |
| Entity resolution, 500 tickers | 10.1 ms |

These are baseline measurements. The only change Phase 1.1 adopted on evidence is the
filing-history fetch, which is a correctness improvement, not a speed one: it adds one
conditional request per archive and removes 1,997 date-precision facts.

---

## 8. Known data limitations

**SEC coverage**

1. Filing history is complete only when the SEC-advertised archives are fetched. They are
   fetched by default and tracked, and `atlas sec history` reports expected vs recorded
   files; `--no-history` opts out and leaves date-precision availability. With history,
   Apple has 2,272 filings and all 5,737 facts carry exact availability. EDGAR's API has no
   filings before 1994, and pre-XBRL years yield no facts regardless.
2. XBRL mapping covers 31 of 505 elements for Apple. **474 elements are unmapped** and
   reported. Meaningful gaps: segment/dimensional facts, IFRS (`ifrs-full`) registrants,
   detailed debt/lease/pension breakdowns, share-based compensation detail.
3. Amendment handling uses form type (`/A`) plus value change. The amendment's explanatory
   text is not parsed, so "why" a value changed is not recorded.
4. `dei:EntityCommonStockSharesOutstanding` is a cover-page figure at the filing date, not
   a period-end count; this is documented on the concept and must not be treated as
   balance-sheet shares.

**Identity**

5. Share-class identity for multi-ticker issuers is provisional (`unverified`, confidence
   0.3) because SEC submissions do not map symbols to classes; Alphabet's cover page lists
   four symbols, and Atlas creates four provisional securities rather than guessing which
   are primary. One-ticker issuers get `probable` (0.6). Confirmed identity requires a
   share-class source, which is not ingested.
5a. Ticker **start dates are not evidenced** by SEC. Assignments begin at the retrieval
   date, so `resolve_ticker("MSFT", as_of="2015-01-01")` returns nothing, with a reason
   naming the date. This is deliberate conservatism: assuming the symbol was active would
   be an unevidenced claim. Historical ticker resolution therefore needs a listing-history
   source.
6. ISIN/FIGI/CUSIP are supported as assignment schemes with licence notes but no licensed
   source is ingested; assignments are manual.
7. Corporate relationships (parent/subsidiary/merger) are schema-supported with confidence
   but no SEC-derived ingestion.

**Market**

8. No live external market-data adapter is implemented. Raw OHLCV arrives via CSV/Parquet.
   The reason is licensing/redistribution: every free feed examined either forbids
   redistribution or is explicitly unstable, and the brief requires not misrepresenting
   provider coverage. The store, validation, calendar and adjustment layers are
   provider-agnostic and ready for an adapter.
9. Calendars are rule-based, so unscheduled closures (weather, national mourning) are
   wrong until the venue data is amended. Validation surfaces bars outside the rules.
10. Daily bars only. The schema and store are interval-keyed so minute/tick data can be
    added, but no intraday path, quotes, order book, or auction data exists.
11. One currency per bar; no FX conversion, no multi-currency portfolio arithmetic.
12. Total-return index does not model withholding tax, reinvestment timing or fees.

**Corporate actions**

13. Splits, reverse splits and cash dividends are computed; mergers, spin-offs,
    distributions and ticker changes are recorded but not computed economically.
14. No automated corporate-action source; actions are entered via CLI or fixtures.

**Evidence**

15. The kernel is general (any entity/security + concept), but only SEC financial facts
    are connected. No macroeconomic or economic-observation connector exists.
16. Derived facts are supported and rule-stamped, but no automatic derivation *pass* runs
    after ingestion; derived records are created explicitly (and then indexed).
17. The reverse dependency index has no cycle detection for chains longer than a direct
    self-reference; traversal is depth-limited (8) and returns each computation once, so a
    cycle truncates rather than looping.
18. Reconciliation compares against SEC's `companyfacts` API view, not the raw XBRL
    instance documents. A defect in SEC's own derivation would not be caught, and concept
    *mapping* choices are not independently re-litigated (both sides use the registry).

---

## 9. Unsupported features (by design, Phase 2+)

Financial-Economic Compiler; a dependency-graph *computation* service (the index exists;
the compiler that consumes it does not); model registry; simulation engine; backtesting
engine; research workflow layer; graphical terminal (a read contract exists in
`TERMINAL_CONTRACT.md`, no implementation); streaming market adapters; AI/LLM integration;
portfolio analytics; credit models; options/futures/derivatives; FX; licensed identifier
and price data; multi-user access control; HTTP/RPC API.

---

## 10. Technical debt (ranked by impact)

1. **Point-in-time selection is still ~155 ms for all concepts.** A SQL implementation was
   built and differentially verified, but measured *slower* (236 ms), so it was not
   adopted. The remaining lever is a `current_fact` snapshot table per knowledge instant or
   a columnar engine, both of which change the storage model and need their own
   measurement.
2. **Whole-payload parsing in memory.** A 3.8 MB JSON document is loaded and transformed
   at once. Fine for one company; a whole-market bootstrap needs streaming and chunked
   ingestion.
3. **Two validation code paths.** `BarStore.validate` and `validation._check_bars` overlap;
   consolidate to one implementation to avoid drift.
4. **`corporate_action` does not persist `availability_basis`.** Time and precision are
   stored, so the as-of behaviour is correct, but the evidence explanation for an action
   is weaker than for a fact.
5. **Migration splitter is simplistic** (line-based, assumes no embedded semicolons). It
   is documented and guarded by a build-time check, but a real SQL parser or per-migration
   statement lists would be safer as the schema grows.
6. **`validation._check_bars` stale-revision reporting is skipped when filtering by
   security** (a reporting gap, not a correctness issue).
7. **No CI configuration.** Tests are a single documented command but are not enforced on
   push. Adding GitHub Actions with the offline suite is cheap and valuable.
8. **No concurrency test.** WAL permits one writer with concurrent readers; multi-process
   ingestion, lock contention and busy-timeout behaviour are unverified.
9. **No backup/restore or retention policy.** `Database.checkpoint` exists; archival of
   superseded evidence and old bar revisions is undefined.
10. **CLI and demo duplicate table formatting.** Cosmetic, but they will drift.
11. **Two selection implementations must stay in step.** The differential test is the only
   thing preventing divergence; if it is ever weakened, delete the SQL engine.
12. **Dependency writes are row-at-a-time.** Fine for hundreds of computations, untested
   for a whole-market model run producing millions; batching would be required.
13. **Reconciliation is O(payload) per run** and re-parses the whole document. Acceptable
   for a per-company gate, not for a nightly whole-market job without streaming.

---

## 11. Recommended next engineering priorities

1. **Dimensional facts** — segment/geography/product XBRL facts, with dimension-aware
   evidence keys. Required for any fundamental model worth building, and the largest
   remaining data gap.
2. **Automatic derivation through the index** — run declared derivations after ingestion so
   derived records and their `computation` rows appear without manual construction, then
   invalidate exactly the stale outputs on each new filing.
3. **Selection performance** — a knowledge-time snapshot table (or columnar engine) is the
   measured next step, since SQL grouping alone lost to the Python path. Target sub-10 ms
   and re-run the same benchmark.
4. **Listing-history source** — evidenced ticker start/end dates, so historical identity
   resolution stops returning `none` for every past date.
5. **Licensed market data adapter** — one vendor behind the existing importer contract,
   with licence metadata and an explicit experimental flag; add minute-bar partitioning.
6. **XBRL instance-level reconciliation** — compare against the raw `.xml` and `R` files,
   not only SEC's derived `companyfacts` view.
7. **Operational hardening** — CI, concurrency tests, backup/restore verification, and a
   retention policy for superseded rows.
8. **Economic observation connector** — reuse the kernel for macro series, proving the
   evidence model generalises beyond SEC facts.

---

## 12. Honest closing assessment

The data and evidence layer is real: it ingests actual SEC filings, keeps every version,
answers both temporal questions without leaking later information, traces any value back to
a hashed source document, and refuses to guess about identity, units or timing. The
acceptance scenarios pass because they were executed, not because they were designed.

Phase 1.1 strengthened the two things that matter most for trust: the filing history is now
complete enough that every Apple fact has an exact acceptance timestamp, and every stored
fact has been independently re-derived from the source and compared — 5,737 of 5,737, with
the test suite proving the checker catches deliberate corruption.

The layer is still not complete. SEC coverage is one API surface, 31 mapped concepts and
four issuers; dimensional facts are absent; market data has no live adapter; corporate
actions cover four types; ticker start dates are unevidenced; and the things that make
Atlas distinctive as a *platform* — the compiler, models, research workflow, terminal — are
specified as contracts, not built. The dependency index those systems will use now exists
and is tested; the systems themselves do not. Those gaps are listed above rather than
papered over, which is the only way the next phase can trust what it inherits.
