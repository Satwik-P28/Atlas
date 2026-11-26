# Phase 4 validation

## Backend

Baseline at `9b893ba3d36208061dc508c220d764589e2684b9`: **333 passed**.
Phase 4 adds 11 targeted tests, for **344 passed** in the final full-suite run.

```
.venv/bin/python -m pytest -q -p no:warnings
```

The Phase 4 tests independently assert:

* schema 6 tables and migration;
* a hand-computed ledger (cash, basis, realized P&L, split, dividend, final equity);
* invalid quantities and insufficient cash;
* next-open fill, not same-close;
* split/dividend applied once and ordered before the mark;
* costs reduce results and repeated execution is deterministic;
* feature cutoff excludes a later bar;
* content-addressed archive hashing and rights/provider status;
* 1,000-node compiler correctness and a generous wall-clock ceiling;
* Lab API save/replay/archive;
* vectorized preview labeling (`vectorized_preview`, `not_a_fill_simulation`, no ledger);
* rejection of silent strategy parameter reuse.

Existing 333 tests were not deleted or weakened; schema assertions moved from 5 to 6.

## Frontend

```
cd web && npm run build
cd web && npm test -- --run
```

TypeScript/Vite production build passes; 4 Vitest tests pass.

## Browser acceptance

`web/e2e/phase4.mjs` (Chromium, 1440×960 and 390×844) verifies:

1. historical cutoff selection, model execution, save, close, reopen and re-execution;
2. preserved cutoff/evidence/assumption/result values after reopen;
3. IBM buy-and-hold Quant Lab run with accounting;
4. trend and custom Model Forge signal runs;
5. Time Capsule and replay fingerprint equality;
6. saved experiment comparison;
7. experiment JSON export;
8. mobile layout with no horizontal overflow.

Legacy `journeys.mjs` (12 journeys, 0 problems) and `studio.mjs` (11 checks) pass unchanged.

Screenshots: `artifacts/22-studio-historical-reopen.png` through
`artifacts/28-quant-lab-mobile.png`.

## Acceptance matrix

| Requirement | Evidence |
|---|---|
| A historical point-in-time research | feature cutoff tests; historical Studio replay |
| B strategy creation | strategy registry API and Lab save |
| C chronological backtest | next-open test; 2,977-session IBM runs |
| D accounting reconciliation | independent hand ledger; every run reconciled |
| E benchmark | buy-and-hold in same engine |
| F costs | commission test and cost-adjusted runs |
| G custom model | Model Forge signal in IBM run |
| H parameter variation | changed specs require new version; variants persisted |
| I experiment history | save, reopen, fork/version, comparison |
| J historical integrity | feature and fill timing tests |
| K credibility report | report API/UI persisted with runs |
| L Time Capsule | replay fingerprint equality |
| M error handling | validation tests; unsupported universes rejected |
| N regression | 333 baseline tests + 12 journeys + 11 Studio checks |

## Known gaps

* Source archives exist and are hash-verified, but real vendor bytes are not archived, so
  the IBM capsule is provider-dependent.
* No out-of-sample, walk-forward or purged CV result is claimed.
* The browser e2e has written many demonstration runs/applications to `var/atlas.db`;
  they are local artifacts, not test fixtures.
* UI browser checks cannot run in this environment after archiving without reinstalling
  the local Chromium sysroot.
