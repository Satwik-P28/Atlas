# Phase 4 benchmarks

Measured by `scripts/bench_phase4.py` against `var/atlas.db`; raw output is
`artifacts/bench_phase4.json`.

## Environment and dataset

* Linux 6.1.102 x86_64, glibc 2.39, Python 3.12.3, shared cloud VM (CPU model string
  `19/01`; no dedicated hardware claim).
* IBM (`SEC-84034a36d48e517c9e3a`), Alpha Vantage raw bars, 6,793 stored sessions
  (1999-11-01 through 2026-11-03). Backtests use 2,977 sessions from 2015-01-02.
* Median of repeated runs; CPU only, single process. These are local figures, not
  comparisons with LEAN, NautilusTrader, Bloomberg or TradingView.

## Compiler

| Nodes | Median compile | Peak MiB | Plan nodes |
|---:|---:|---:|---:|
| 10 | 0.152 ms | 0.02 | 11 |
| 100 | 0.850 ms | 0.19 | 101 |
| 1,000 | 8.154 ms | 1.96 | 1,001 |
| 1,900 | 16.368 ms | 3.70 | 1,901 |

The previous Phase 3 report measured approximately **1,797 ms** for 1,000 nodes. The
replacement adjacency + heap topological pass is therefore about **220× faster** on this
case (1,797 / 8.154), while retaining cycle detection, arity validation and type inference.
The comparison is the same graph size but not a controlled rerun on identical hardware, so
treat it as an order-of-magnitude result rather than a precise speedup claim.

## Features

| Definitions | Points | Median |
|---:|---:|---:|
| 6 | 2,977 | 265.619 ms |

## Event-driven simulator

| Strategy | Sessions | Trades | Duration | Sessions/s | Peak MiB | Return |
|---|---:|---:|---:|---:|---:|---:|
| Buy and hold | 2,977 | 1 | 2,023 ms | 1,471 | 19.15 | 108.60% |
| SMA 20/100 | 2,977 | 50 | 3,414 ms | 872 | 19.15 | -39.49% |
| 60-session momentum | 2,977 | 141 | 1,977 ms | 1,506 | 19.15 | 16.12% |
| Model Forge signal | 2,977 | 333 | 4,039 ms | 737 | 19.16 | 24.17% |

All runs reconciled. Throughput varies with decision count and model evaluation; the
custom signal is slowest because it invokes the compiled Decimal runtime. There is no
claim that this is faster than a production engine.

## Vectorized preview

Close-to-close buy-and-hold reports **54.18%**, versus **108.60%** for the event-driven
ledger on the same period, because it excludes dividends/splits and does not model fills.
This is documented to prevent the two modes being mistaken for equivalent estimators.

## What was not benchmarked

Multi-asset panels, intraday data, GPU kernels, thousands of parameter configurations,
network ingestion and browser rendering under load. No GPU backend exists.
