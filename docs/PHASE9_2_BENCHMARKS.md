# Phase 9.2 benchmarks

Measured locally with `scripts/benchmark_phase9_2.py` on 2026-11-06. Hardware: 2 vCPU,
3.8 GiB RAM. Timings are single-run observations, not service-level guarantees.

| Path | Time |
| --- | ---: |
| FR Y-9C bulk import (3,806 rows, 17 observations) | 409.43 ms |
| Consolidated FR Y-9C evidence | 0.50 ms |
| FDIC regulatory evidence, JPM | 7.99 ms |
| Entity resolution | 0.08 ms |
| Bank v2, JPM | 12.04 ms |
| Bank v2, GS | 9.63 ms |
| Insurer model, UNH | 6.76 ms |
| JPM report generation | 2,189.33 ms |
| JPM application package | 2,080.33 ms |
| Package install, clean database | 5.50 ms |
| Package execution/replay | 6.32 ms |
| Browser journeys A–J (desktop + 390×844) | 46,597 ms |

Source and output sizes:

| Item | Size / identity |
| --- | ---: |
| `BHCF20241231.ZIP` | 1,509,964 bytes |
| FFIEC dictionary | 170,487 bytes |
| FR Y-9C rows in archive | 3,806 |
| FR Y-9C observations written | 17 |
| Report | 16,676 bytes |
| Exported package | 61,109 bytes |
| Exported package SHA-256 | `66deed04176f25b08228a75569917c6c0834e646742d8c05b7cd2ad183c80ce8` |
| Fixture database | 39,067,648 bytes |

The benchmark also installs and executes a freshly generated package on schema 13;
`reproduced=true`. A separately exported artifact is measured by the same script for
size and SHA-256 so the benchmark cannot silently stand in for the committed export.

Raw results: `artifacts/phase9_2_benchmarks.json`.
