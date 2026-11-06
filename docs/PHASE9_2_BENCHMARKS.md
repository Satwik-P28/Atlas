# Phase 9.2 benchmarks

Measured locally with `scripts/benchmark_phase9_2.py` on 2026-11-06. Hardware: 2 vCPU,
3.8 GiB RAM. Timings are single-run observations, not service-level guarantees.

| Path | Time |
| --- | ---: |
| FR Y-9C bulk import (3,806 rows, 17 observations) | 421.24 ms |
| Consolidated FR Y-9C evidence | 0.52 ms |
| FDIC regulatory evidence, JPM | 8.55 ms |
| Entity resolution | 0.08 ms |
| Bank v2, JPM | 13.29 ms |
| Bank v2, GS | 11.44 ms |
| Insurer model, UNH | 8.18 ms |
| Market analysis, JPM | 10.73 ms |
| JPM report generation | 2,253.45 ms |
| JPM application package | 2,202.81 ms |
| Package install, clean database | 6.42 ms |
| Package execution/replay | 7.41 ms |
| Browser journeys A–J | **not rerun**; local Chromium 156 crashed |

Source and output sizes:

| Item | Size / identity |
| --- | ---: |
| `BHCF20241231.ZIP` | 1,509,964 bytes |
| FFIEC dictionary | 170,487 bytes |
| FR Y-9C rows in archive | 3,806 |
| FR Y-9C observations written | 17 |
| Report | 16,176 bytes |
| Exported package | 61,281 bytes |
| Exported package SHA-256 | `e99e6269ec47f7953177281f5ee85b73ef3dfb144b4321c28cfc1ad606ed09ed` |
| Benchmark package | 61,459 bytes |
| Fixture database | 37,523,456 bytes |

The benchmark also installs and executes a freshly generated package on schema 13;
`reproduced=true`. A separately exported artifact is measured by the same script for
size and SHA-256 so the benchmark cannot silently stand in for the committed export.

Raw results: `artifacts/phase9_2_benchmarks.json`.
