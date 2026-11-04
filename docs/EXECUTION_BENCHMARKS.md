# Phase 3 execution benchmarks

Environment: Linux cloud VM, Python 3.11 virtualenv, SQLite WAL with
`synchronous=FULL`, single process. Measurements are medians where repeated; the
reproducible script is `scripts/bench_phase3.py`.

## Materialized screener

| Universe | Cold | Warm |
|---|---:|---:|
| Delivered `var/atlas.db` — 5 issuers, 23,583 evidence rows | 1,609 ms | **32.3 ms** |
| Synthetic 300-issuer benchmark | 298 ms | **30.5 ms** |

The 300-issuer universe is **fully synthetic**, not market coverage. The delivered
database contains real IBM SEC facts and Alpha Vantage observations; other demonstration
securities retain synthetic prices. Phase 2.1 reported roughly 1.6 s for five issuers;
the warm materialized path is now about 50× faster and below the 200 ms target. Cold
screens still pay the evidence-selection cost.

The warm result depends on the implicit-now cutoff normalizing to end-of-day. Explicit
historical cutoffs remain distinct cache keys.

## Compiler and runtime

| Nodes | Compile | Compile peak | First execute | Cached execute |
|---:|---:|---:|---:|---:|
| 10 | 1.4 ms | 15.2 KiB | 0.35 ms | 0.19 ms |
| 100 | 24.1 ms | 172.1 KiB | 1.73 ms | 1.42 ms |
| 1,000 | 1,797 ms | 1.68 MiB | 15.7 ms | 14.6 ms |

The 1,000-node compile is dominated by the current Kahn implementation's repeated
frontier sorting and dependency scans (roughly quadratic). It is usable for the tested
scale but is a known optimisation target before much larger graphs.

## Not benchmarked

- Browser rendering/memory for the graph editor.
- Multi-scenario wall-clock at production scale.
- GPU/vectorised or external execution backends (not installed).
- DCF compile/execute latency in isolation; API tests cover correctness, not a
  statistically robust latency distribution.
