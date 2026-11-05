# Phase 7 benchmarks

Artifact: `artifacts/phase7_benchmarks.json`.
Script: `scripts/benchmark_phase7.py`.
Measured: 2026-11-05T20:40:28Z.

## Environment

| Item | Value |
|---|---|
| Platform | Linux 6.1.102 x86_64, glibc 2.39 |
| CPU count | 2 |
| Python | 3.12.3 |
| NumPy | 2.5.4 |
| SQLite | 3.45.1 |
| Backend | CPU-only SQLite + NumPy |
| Peak RSS | 52.6 MB |
| Database | 1.63 MB in the temporary benchmark run |
| Panel | 365 days, 1,095 observations, 3 series |
| Graph | 12 entities, 12 edges |
| Scenario | 2,000 and 10,000 coefficient draws |

The benchmark builds a temporary file-backed database, runs one untimed warm-up and then
records five to seven wall-clock samples. It uses the same service code as the API. It does not
include HTTP serialization or browser rendering.

## Results

| Operation | Result |
|---|---:|
| Migrate schema 1→9 | 18.15 ms |
| Ingest sources and bootstrap 1,095 observations + graph | 438.90 ms cold |
| Panel query, first | 9.52 ms |
| Panel query, warm median | 8.32 ms (8.19–8.84) |
| Indexed graph traversal, first | 0.56 ms |
| Indexed graph traversal, warm median | 0.29 ms (0.28–0.30) |
| Geographic SQL join | 0.63 ms |
| Model fit, validation selection and frozen test | 25.76 ms |
| Model plus persistence | 34.05 ms |
| Scenario 2,000 draws, FEC compile and persistence | 15.90 ms |
| Scenario 10,000 draws, compile and persistence | 13.29 ms |
| Sentinel refresh | 3.10 ms |
| Historical replay (365 rows, fingerprint) | 26.79 ms |
| Research memory query | 0.46 ms |
| Application save | 1.56 ms |
| Application restore | 0.12 ms |
| Application export manifest | 0.55 ms |
| Observation revision + invalidation | 1.15 ms |
| Stale-run read | 0.33 ms |
| Memory after invalidation | 0.42 ms |

Monte Carlo throughput: **752,672 coefficient draws/second** for the 10,000-draw scenario;
**62.91 scenarios/second** including FEC compilation and persistence at 2,000 draws.

The 10,000-draw call is faster than the first 2,000-draw call because the latter includes
cold compilation. Do not compare draw counts as if both were warm; the benchmark reports
one-shot operations honestly.

Serialized sizes: analysis JSON 19,672 bytes; scenario JSON 4,128 bytes; catalog JSON 12,036
bytes; application export 5,772 bytes.

## Browser rendering

See `artifacts/phase7_browser.json` for the measured navigation timing, DOM node count,
first paint and first contentful paint from the Phase 7 journey, captured after a fresh
navigation at 1440×1100. The figures are browser/container-specific and are not a production
CDN measurement.

## Interpretation

The workload is small and CPU-bound. The cold cost is dominated by ingesting 1,095 observations
and constructing the graph, not by model arithmetic. Warm panel queries take about 8 ms; the
model and 2,000-draw scenario together run in tens of milliseconds. No distributed
infrastructure, GPU, Rust extension or second compiler is justified by these measurements.

The database is tiny (1.9 MB for the shipped file including the research application) and the
whole application remains local-first. Peak RSS under 60 MB is not evidence of scalability to a
national multi-year panel; no such claim is made.

## Bottlenecks and non-optimizations

* Panel reconstruction queries all three series and reconstructs JSON metadata per row.
* Replay reruns the full model rather than caching intermediate matrices.
* The FEC compiler initializes per scenario, accounting for the first-call overhead.
* The chart renders 365 SVG points in the browser; this is acceptable and was not optimized.
* No query cache or materialized daily panel exists yet.
* No incremental model update; a revision invalidates the run rather than patching it.

## Reproduction

```bash
.venv/bin/python scripts/benchmark_phase7.py --out artifacts/phase7_benchmarks.json
```

The benchmark modifies only a temporary database. It is a measured snapshot, not a universal
performance guarantee.
