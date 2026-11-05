# Phase 9 workflow benchmarks

Measured by `scripts/benchmark_phase9_equity.py` on the real 20-company fixture in this
Linux VM. Raw data: `artifacts/phase9_benchmarks.json`. These are single-machine
observations, not service-level objectives.

| Step | Median | Range (3 runs) |
| --- | ---: | ---: |
| Coverage for all 20 issuers (runs the DCF core for 17) | 272 ms | 1 run |
| Issuer workspace (statements, history, peers, validation, evidence) | 2,197 ms | 2,150–2,240 ms |
| Full analysis (report + scenarios + 5×5 sensitivity) | 2,382 ms | 2,330–2,450 ms |
| Build the portable package | 2,348 ms | 2,300–2,400 ms |
| Install the package into a clean database | 4.6 ms | 4.3–4.9 ms |
| Execute the package in a clean database | 4.8 ms | 4.5–5.1 ms |

## Interpretation

- The coverage call is cheap despite running 17 DCFs because each execution is a compiled
  graph over cached evidence reads.
- The workspace and analysis calls are dominated by the existing validation and peer read
  models, not by the DCF: executing one DCF is a few milliseconds, while `workspace()`
  rebuilds statements, history, filings, peers and the research validation report.
- Packaging costs about the same as one analysis because it renders the report and then
  serialises the deterministic archive.
- Install and execute are fast because the package is a declarative archive: install
  verifies hashes and stores bytes; execution compiles the packaged model spec.

## What is not measured

- Cold-cache first access on a fresh process (the numbers above include the OS page cache).
- Concurrent users: the terminal is a single-user local application.
- Large universes beyond 20 issuers.
- Network download of new SEC payloads.

No number here is an estimate; if a step was not measured it is listed above as unmeasured.
