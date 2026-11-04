# Phase 3 implementation — Universal Financial Runtime

Status: **implemented vertical slice, independently validated and browser-verified**. Last verified against schema 5 at commit after `d094904`.

## What is implemented

| Capability | State | Evidence |
|---|---|---|
| Materialized issuer metrics | Implemented and verified | `metric_store.py`, `tests/test_phase3_metrics.py` |
| Historical snapshot isolation | Implemented and verified | exact as-of + mode + generation key; amendment test |
| Typed compiler pipeline | Implemented and verified | `src/atlas/fec/compiler.py`, `tests/test_fec.py` |
| Allowlisted equation parser | Implemented and verified | `src/atlas/fec/parser.py`; AST, no `eval` |
| Deterministic runtime + node cache | Implemented and verified | `runtime.py`; cache key includes input values and operator version |
| Incremental recomputation | Implemented and verified | independent subgraph cache-hit test |
| Python SDK | Implemented and verified | `sdk.py`; equivalence test |
| DCF / reverse DCF / scenarios / sensitivity | Implemented and independently validated | `valuation.py`; `test_phase3_validation.py` recomputes every path with separate arithmetic |
| Research object lifecycle | Implemented and browser-verified | fork/compare/export/execute; Studio Open/Fork/Compare/Export; run snapshot in manifest |
| Studio UI | Implemented and browser-verified | `/studio`, valuation/equations/visual graph tabs, historical cutoff |
| Browser journeys | Verified in this environment | 12 Phase 2.1 regression journeys + 11 Studio checks; 0 unexpected page/console errors |

## Preserved contracts

Phase 1–2.1 evidence semantics, migrations 001–004, API error envelope, identity
resolution, X-Ray and terminal routes are unchanged. Migration 005 is additive.
Research objects remain `atlas.research_object.v1`; `financial_metric` is added as a
new kind without changing existing documents.

## Verification summary

- Backend: **333 passed** with `.venv/bin/python -m pytest -q -p no:warnings`.
- Frontend: production build passes; **4** Vitest tests pass.
- Browser: existing 12 journeys pass with 0 problems; Studio passes historical cutoff,
  current DCF, scenarios/sensitivity, reverse DCF, save/reopen, fork/compare, export,
  invalid-model diagnostics, equation execution, graph validation and 390 px layout.
- Screenshots: `artifacts/13-studio-valuation.png` through
  `artifacts/21-studio-error.png`.

## Honest limitations

- The historical financial model is scoped to concepts stored by the evidence kernel.
  A complete three-statement reconciliation is not claimed.
- D&A, tax, WACC and working-capital inputs default to labelled assumptions when no
  reported value exists. They are never presented as observed facts.
- Where a reported share count is absent, Studio derives implied weighted diluted shares
  from net income / diluted EPS and labels that derivation; it never assumes one share.
  The final valuation normalisation has no implicit one-share default.
- The visual editor is a functional drag/connect canvas, not a mature graph IDE.
- The browser journey covers the complete primary Studio path and the existing terminal
  journeys, but it is not an exhaustive separate automation of every A–N item. Incremental
  recomputation is verified at unit/API level, not through a browser interaction.
- Export manifests now include the persisted run inputs, outputs and trace, but Atlas does
  not archive source-evidence bytes for indefinite reproduction after source withdrawal.
- `ATLAS_MASTER_SPEC.md` was absent from the repository; work followed
  `docs/PHASE3_CONTRACT.md` and the Phase 3 prompt.

## Reproduction

```bash
.venv/bin/python -m pytest -q -p no:warnings
cd web && npm run build && npm test -- --run
.venv/bin/atlas --db var/atlas.db serve --host 127.0.0.1 --port 8000
```

The database must be migrated to schema 5 before the API will serve. The browser checks
run against `http://127.0.0.1:8000` and write screenshots into `artifacts/`.
