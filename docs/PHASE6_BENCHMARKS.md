# Phase 6 benchmarks

Measured by `benchmarks/phase6_bench.py` on the local EODHD demo panel. Artifact:
`artifacts/phase6_benchmarks.json`.

## Environment

| Item | Value |
|---|---|
| Platform | Linux 6.1.102 x86_64, glibc 2.39 |
| CPU | 2 vCPU, x86_64 |
| Accelerator | CPU only |
| Python | 3.12.3 |
| NumPy | 2.5.4 |
| SciPy | 1.18.1 |
| scikit-learn | 1.9.1 |
| PyArrow | 26.0.1 |
| Database | 3,407,872 bytes |
| Peak process RSS | 158.9 MB |

The benchmark is local and offline. It reads restricted vendor demo rows from `var/`; those
rows are not committed.

## Dataset

| Item | Value |
|---|---:|
| Securities | 5 |
| Sessions | 752 |
| Bars | 3,760 |
| Feature rows | 3,455 |
| Features | 5 |
| Date range | 2023-01-03 → 2025-12-31 |
| Missing weekdays | 30 |
| Quality errors / warnings | 0 / 1 |

## Stage timings

Medians of three runs unless marked single.

| Stage | Median | Notes |
|---|---:|---|
| Dataset load and alignment | 67.0 ms | SQLite reads + panel validation |
| Feature generation | 47.0 ms | 3,455 rows, five features |
| Train/validation/test, 4 models | 800.6 ms | includes scaler, Platt, continuous companion |
| Batch inference | 1.48 ms | 685 test rows |
| Probability scoring/calibration | 6.88 ms | Brier, log loss, AUC, 10-bin table |
| Model audit | 0.009 ms | rule evaluation |
| Bounded discovery, 4 candidates | 169.0 ms | single run, ridge only |
| Persisted run replay | 2.78 ms | read 685 forecasts + result |
| Monitor snapshot | 116.1 ms | recent drift + realized calibration |

The reported experiment duration is **789.5 ms** for four candidates; the benchmark median
of 800.6 ms includes harness overhead.

## Result under measurement

| Item | Value |
|---|---:|
| Selected model | ridge |
| Validation Brier | 0.249669 |
| Test Brier | 0.248493 |
| Brier skill | -0.001354 |
| Test rows/forecasts | 685 / 685 |
| Conclusion | `not_supported` |
| Peak RSS | 158.9 MB |

## Interpretation

* The pipeline is small and CPU-appropriate. Training four candidates and persisting 685
  forecasts is sub-second on this workload.
* These timings do not establish performance on a market-wide panel, a long history, or
  hundreds of features. A larger panel would stress SQLite joins, feature construction and
  forecast persistence.
* No optimizer, GPU, custom CUDA kernel or distributed compute is used.
* Browser responsiveness is checked separately in `web/e2e/phase6.mjs`; it is not inferred
  from these backend timings.
* No speedup is claimed against a prior implementation. The numbers are a baseline for
  Phase 7.

## Reproduction

```bash
.venv/bin/python scripts/build_phase6_db.py --db var/atlas-phase6.db --force --offline
.venv/bin/python benchmarks/phase6_bench.py
```

A clean checkout without the restricted cache cannot reproduce the real-data timing; it can
still run the deterministic synthetic tests.
