# Phase 4 implementation — Quant Lab and Alpha Foundry

Status: **implemented vertical slice, independently validated and browser-verified on schema 6.**

## Delivered capabilities

| Capability | State | Evidence |
|---|---|---|
| Point-in-time feature engine | Implemented | `src/atlas/quant/features.py`, anti-leakage tests |
| Versioned strategy objects | Implemented | `atlas.strategy.v1`, existing `atlas.research_object.v1` registry |
| Next-open chronological simulator | Implemented | `src/atlas/quant/simulator.py`; event-order tests |
| Independent portfolio ledger | Implemented | `src/atlas/quant/portfolio.py`; hand-calculated tests |
| Buy-and-hold benchmark | Implemented | same bars, costs and sessions |
| Model Forge custom signal | Implemented | model equation compiled by the shared FEC; custom IBM run |
| Parameter variation | Implemented | strategy name includes windows/costs; changed specs cannot silently reuse a version |
| Vectorized research preview | Implemented, explicitly non-fill | `src/atlas/quant/vectorized.py`; no ledger claim |
| Persistent runs and experiments | Implemented | `quant_run`, experiment research objects |
| Time Capsule, replay and comparison | Implemented | persisted run, source status, deterministic fingerprint |
| Source-evidence archives | Implemented | `source_archive`, `source_archive_link`, SHA-256 integrity |
| Research Credibility Report | Implemented | evidence/diagnostics, no invented score |
| Quant Lab UI | Implemented | `/lab`; charts, ledger, accounting, history, capsule, export |
| Historical Studio reopen | Browser-verified | 22-studio-historical-reopen.png |

## Schema and migration

Migration 006 is additive:

* `source_archive` — content-addressed source bytes, rights, retention, parser/schema versions.
* `source_archive_link` — evidence-to-archive linkage.
* `feature_snapshot` — feature fingerprint, cutoff, input generation, values and metadata.
* `quant_run` — strategy, config, result, reconciliation, metrics, experiment link.

The live database was migrated from 5 to 6; `/api/health` now reports
`"schema_version": 6, "supported_schema": 6`.

## Real-data demonstration

IBM raw Alpha Vantage observations (source `alphavantage`), 2,977 sessions from
2015-01-02 through 2026-11-03, initial capital $100,000, 2 bps commission and 5 bps
slippage, signals at the close and fills at the next open:

| Strategy | Total return | Max drawdown | Trades | Accounting |
|---|---:|---:|---:|---|
| Buy and hold | 108.60% | -35.26% | 1 | reconciled |
| 20/100 SMA trend | -39.49% | -56.23% | 50 | reconciled |
| 60-session momentum | 16.12% | -44.62% | 141 | reconciled |
| Model Forge close/SMA signal | 24.17% | -46.69% | 333 | reconciled |

These are **research results, not alpha claims**. The trend strategy losing money is a
useful outcome and is retained rather than hidden.

## Verification

* Backend: baseline 333 tests plus 11 Phase 4 tests, for **344 passed** (full command in
  `PHASE4_VALIDATION.md`).
* Frontend: 4 Vitest tests pass; production `vite` build passes.
* Browser: 12 legacy journeys, 11 Studio checks and the Phase 4 historical/Lab journey
  pass with zero unexpected page or console errors.
* Determinism: stored run and replay produce the same SHA-256 result fingerprint.
* Accounting: every run publishes the cash identity and a Boolean reconciliation.

## Honest limitations

* Single instrument and long-only; the strategy contract rejects a multi-instrument
  list rather than simulating an unsupported universe.
* The reference simulator models next-open fills, commissions and slippage. It does not
  model partial fills, queues, market impact, borrow, shorting or intraday data.
* Corporate actions are applied from stored actions known at the cutoff. Missing or
  unavailable actions are not imputed.
* The vectorized path is a close-to-close triage preview without dividends, orders or a
  cash ledger. It is neither claimed nor used as the authoritative backtest.
* Primary price observations are raw vendor rows. Their historical display vintage is not
  proven unless the exact source bytes are archived; the Time Capsule says so explicitly.
* Validation is in-sample. Walk-forward, purged/embargoed cross-validation and formal
  multiple-testing correction are extension points, not completed claims.
* No live trading, order routing or production execution is present.

## Reproduction

```bash
.venv/bin/python -m pytest -q -p no:warnings
cd web && npm run build && npm test -- --run
.venv/bin/atlas --db var/atlas.db serve --host 0.0.0.0 --port 8000
cd web && LD_LIBRARY_PATH=../.pwlibs/sysroot/usr/lib/x86_64-linux-gnu \
  FONTCONFIG_FILE=$PWD/../.pwlibs/fonts.conf node e2e/phase4.mjs
```
