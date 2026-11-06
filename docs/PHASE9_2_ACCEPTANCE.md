# Phase 9.2 acceptance matrix

**Status: implementation and common-equity correction verified; master-spec gate blocked.**
See the root [`PHASE9_2_FINAL_ACCEPTANCE.md`](../PHASE9_2_FINAL_ACCEPTANCE.md).

| Area | Status | Evidence / remaining gap |
| --- | --- | --- |
| Genuine master specification | **Blocked** | File absent; verifier exits 1. No substitute generated. |
| Migrations and fresh install | **Verified** | Schema 13; fresh 1→13 and migration tests. |
| Official FR Y-9C evidence | **Verified snapshot** | FFIEC `BHCF20241231.ZIP`, 3,806 rows, JPM RSSD 1039502, 17 observations. |
| Parent/subsidiary separation | **Verified** | Parent consolidated and CERT 628 are non-additive; parent capital not used per share. |
| Common-equity bank valuation | **Verified** | SEC total less same-period SEC preferred; JPM $324.708B, GS $108.743B. |
| Common book/share and ROE | **Verified** | JPM $116.0666 and 17.5136%; GS $350.0457 and 12.4376%. |
| SEC/FR Y-9C reconciliation | **Verified** | JPM GAAP total/preferred equal FR Y-9C BHCK3210/BHCK3283; no cross-basis subtraction. |
| Point-in-time regulatory history | **Not claimed** | No publication timestamp or vintage. |
| Information cutoff | **Verified** | 2025-06-30 selects price 2025-06-30 and accounting 2024-12-31. |
| Market-data rights | **Verified containment** | Restricted prices absent from report/package; `price_included=false`. |
| Nasdaq automated collection | **Blocked / disabled** | No authorization record; local CSV only. |
| Browser interaction | **Cloud visual pass; A–J partial** | JPM workspace and cutoff control render in Cloud browser. Local Playwright crashes in Chromium 156, so the full A–J suite is not claimed. |
| 390 px mobile | **Not rerun** | Previous evidence predates this UI result; layout code unchanged. |
| Frontend tests and build | **Verified** | 4/4 tests; `tsc -b && vite build` passes. |
| Backend regressions | **Verified** | 446 passed. |
| Independent model audit | **Verified** | Phase 9.2 28/28; Phase 9.1 16/16. |
| Clean package reproduction | **Verified** | Fresh schema 13; `reproduced`; `differences={}`. |

No model is promoted to `economically_reviewed` or `independently_benchmarked`.

## Evidence

- `artifacts/phase9_2_reproduction.json` — common-equity outputs and package hash.
- `artifacts/phase9_2_model_audit.json` — 28 independent checks.
- `artifacts/phase9_2_benchmarks.json` — timings and source sizes.
- `artifacts/phase9_2_application.atlas` — 61,281-byte export.
- `artifacts/phase9_2_final_desktop_jpm.png` — Cloud-browser JPM workspace.
- `artifacts/phase9_2_e2e_final.log` — local runner failure, retained rather than hidden.

## Remaining blockers

1. Genuine master specification absent and unverified.
2. Full local A–J and 390×844 rerun blocked by the container Chromium renderer crash.
3. Point-in-time FR Y-9C prohibited without a release timestamp.
4. Parent tangible book per share and dollar RWA unmapped.
5. Nasdaq automated data authorization absent.
