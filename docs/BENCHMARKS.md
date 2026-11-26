# Benchmarks

All numbers below were **measured in the Phase 1 environment**, not estimated. The raw
output is reproducible with the command in §2 and is archived at
`benchmarks/out/bench.json` when the script is run.

## 1. Environment

| Item | Value |
|---|---|
| Platform | Linux 6.1.102, x86_64 (container) |
| CPU | 2 vCPU (`cpu_count = 2`) |
| Memory | 3.8 GB |
| Python | 3.12.3 |
| SQLite | 3.45.1 |
| Storage | local filesystem, `journal_mode=WAL`, `synchronous=FULL` |
| Date measured | 2026-11-03 |

`synchronous=FULL` is included deliberately: it costs write throughput and buys
crash-consistency, which the brief prioritises over speed. Benchmarks run with the
default durability settings, not a tuned-for-benchmark configuration.

## 2. Command

```bash
.venv/bin/python benchmarks/bench.py --json benchmarks/out/bench.json --repeats 5
```

The script creates fresh databases in a temporary directory, warms up once, then reports
median/min/max over the repeats. Ingestion benchmarks are repeated 3 times (each includes
creating and migrating a database). Bulk-load and entity-resolution benchmarks use one
repeat because they are inherently stateful.

## 3. Datasets

| Dataset | Size |
|---|---|
| Apple `companyfacts` payload | 3,789,099 bytes, 505 XBRL elements |
| Apple `submissions` payload | 163,755 bytes, 1,001 recent filings |
| Evidence records produced | 5,737 (5,527 inserted + 210 superseding) |
| Distinct accessions referenced in evidence | 72 |
| Synthetic daily bars | 1,250 sessions (2019-01-02 onwards, weekdays) |
| Securities for resolution benchmark | 501 (500 synthetic + 1) |

## 4. Results — two independent runs

Run 1 was the first complete measurement. Run 2 was executed after installing the package
editable and re-running, to show run-to-run variance rather than a single flattering
sample.

| Benchmark | Run 1 median | Run 2 median | Run 1 min–max | n/run |
|---|---|---|---|---|
| SEC company ingestion (505 elements → 5,737 facts, incl. DB create/migrate) | 4,516 ms | **4,404 ms** | 4,471–4,539 ms | 3 |
| Statement query, 4 concepts, one instant | 22.9 ms | **25.3 ms** | 21.8–23.4 ms | 5 |
| Point-in-time selection, all concepts, one instant | 178.8 ms | **168.6 ms** | 163.2–206.8 ms | 5 |
| Revision history, one concept | 2.3 ms | **2.3 ms** | 2.2–2.3 ms | 5 |
| Provenance traversal (source + filing + raw doc + chain) | 0.15 ms | **0.15 ms** | 0.15–0.21 ms | 5 |
| Daily bar load, 1,250 bars | 42.7 ms | **40.0 ms** | single run each | 1 |
| Multi-year bar query (1,250 bars) | 11.5 ms | **11.1 ms** | 11.4–11.9 ms | 5 |
| Entity resolution, 500 ticker lookups | 14.4 ms | **10.2 ms** | single run each | 1 |

Observed run-to-run spread is up to ~29% on the entity-resolution batch and ~10% on the
query benchmarks.

## 4.1 Phase 1.1 — selection engine comparison

The SQL engine was written twice. The first formulation used correlated subqueries per
group; the second replaced them with a single window pass. Both were run against the same
dataset and both were slower than the Python default:

| Query | Python (run 2) | SQL correlated (run 2) | Python (run 3) | SQL window (run 3) |
|---|---|---|---|---|
| All concepts, one instant | 152.4 ms | 205.9 ms | **154.6 ms** | 235.8 ms |
| Four concepts, latest | 23.1 ms | 31.3 ms | **22.4 ms** | 35.3 ms |

Verdict: the SQL engine is correct (differential tests) but not adopted. The window
rewrite did not help — replacing correlated subqueries widened the intermediate relation
and SQLite still pays for partitioning plus a second hydration pass. Run 3 also re-measured
ingestion (4,387 ms; unchanged), revision history (2.3 ms), provenance (0.15 ms), bar load
(40.2 ms), bar query (11.1 ms) and entity resolution (10.1 ms).

The Phase 1.1 filing-history work adds one conditional HTTP request per archive on first
sync and nothing to query latency: the benchmark database is built from payloads that were
already fetched, and the availability upgrade (3,740 → 5,737 exact) is a correctness
change, not a speed one.

## 5. Interpretation (no invented speedups)

* Ingestion is dominated by JSON parsing and per-record validation/insert, at roughly
  **0.77–0.79 ms per evidence record** (4,404–4,516 ms ÷ 5,737). 5.7k records for a large
  registrant is a few seconds — fine for per-company sync, not yet for a whole-market bulk
  load.
* Per-fact statement queries are ~22–25 ms, which is interactive. Selecting **every**
  concept for an instant costs ~153–179 ms because grouping and policy evaluation run over
  all candidate rows. Moving the grouping into SQL was measured and did **not** help
  (236 ms), so the remaining lever is a snapshot/columnar model, not a query rewrite.
* Provenance is effectively free (0.15 ms) because it is a handful of indexed lookups;
  there is no excuse for a UI not to show it.
* Ticker resolution at ~20–29 µs per lookup means identity resolution will not be the
  bottleneck in a research pipeline.

The Phase 1.1 comparison that *was* measured is the SQL engine against Python (above),
including a negative result. Other changes in that phase (history fetch, reconciliation,
dependency indexing) are correctness/coverage work and are not claimed as speedups;
reconciliation in particular costs a full payload re-parse per run.

## 6. Caveats

* 2 vCPU / 3.8 GB container; absolute numbers will differ on other hardware, and the
  ratios are more portable than the values.
* The ingestion benchmark includes `CREATE TABLE`/migration cost (~tens of ms) and SQLite
  WAL setup, so it slightly overstates steady-state incremental sync.
* The bar-load benchmark is a single run; treat it as indicative.
* These are single-process, cold-ish measurements without OS page-cache tuning. No
  concurrency benchmark exists; WAL allows one writer with concurrent readers, but that
  path is untested under load and is listed as technical debt.

---

## Phase 2 terminal (2026-11-04)

Measured by `benchmarks/terminal_bench.py` against `atlas serve` on `var/atlas.db`
(41.2 MB, 18,657 evidence records, 10,570 synthetic bars), 7 samples per endpoint,
local SSD, Python 3.12.3, SQLite WAL. Server RSS 87.2 MB.

| Endpoint | Median | p95 |
|---|---|---|
| `GET /api/health` | 172.4 ms | 177.3 ms |
| `GET /api/companies` | 1,341.1 ms | 1,396.3 ms |
| `GET /api/companies/{id}` | 205.0 ms | 208.9 ms |
| `GET /api/companies/{id}/statements` | 205.5 ms | 222.2 ms |
| `GET /api/companies/{id}/metrics` | 563.2 ms | 586.5 ms |
| `GET /api/securities/{id}/market` (1Y split) | 28.2 ms | 30.2 ms |
| `POST …/market` (1Y total return, 4 indicators) | 34.7 ms | 35.5 ms |
| `GET …/statements` as-of 2023-12-31 | 185.7 ms | 202.8 ms |
| `GET /api/evidence/{id}` | 2.6 ms | 2.8 ms |
| `POST /api/screeners/run` | 3,285.1 ms | 3,303.1 ms |
| `GET /api/companies/{id}/filings?limit=50` | 6.5 ms | 6.9 ms |

Cold first read (open database + company page + statements): 1,817 ms.
The company list and screener are recomputation-bound (per-issuer aggregates and
point-in-time metrics), not I/O-bound; no caching or optimisation is claimed.
