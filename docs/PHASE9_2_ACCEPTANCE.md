# Phase 9.2 acceptance matrix

**Final status: not fully accepted.** See the root
[`PHASE9_2_FINAL_ACCEPTANCE.md`](../PHASE9_2_FINAL_ACCEPTANCE.md) for identities,
commands and browser evidence. "Verified" means a command or assertion ran in this
worktree; it does not upgrade economic validity.

| Area | Status | Evidence / remaining gap |
| --- | --- | --- |
| Genuine master specification | **Blocked** | File absent; verifier exits 1. Expected SHA-256 `e54c5973…ba5c9`. No substitute generated. |
| Migrations and fresh install | **Verified** | Schema 13; fresh 1→13, upgrade, rollback, backup restore. |
| Official FR Y-9C evidence | **Verified snapshot** | FFIEC `BHCF20241231.ZIP`, 3,806 rows, JPM RSSD 1039502, 17 observations. |
| Consolidated FR Y-9C capital | **Verified snapshot** | $4.0028T assets; $344.758B total equity; $324.708B common; 15.6768% CET1. |
| Parent/subsidiary separation | **Verified** | Parent consolidated and CERT 628 standalone are non-additive; parent capital not used per share. |
| Bank residual income v2 | **Arithmetic verified; input blocked** | Independent audit 19/19, but opening book is total stockholders' equity, not common equity. Preferred stock is unmapped. |
| Point-in-time regulatory history | **Not claimed** | Bulk archive has no publication timestamp or vintage; historical cutoff use is blocked. |
| Information cutoff | **Verified** | Cutoff 2025-06-30 selects price 2025-06-30 and accounting 2024-12-31. |
| Market-data rights | **Verified containment** | Restricted price excluded from report/package; `price_included=false`. |
| Nasdaq automated collection | **Blocked / disabled** | No provider authorization record; local CSV import only. |
| Browser journeys A–J | **Verified** | Desktop and 390×844; save/reopen, export, method rejection and regression routes. |
| 390 px mobile layout | **Verified** | Width 390/390; no clipped values; 44 px controls; table scroll containment. |
| Frontend tests and build | **Verified** | 4/4 tests; `tsc -b && vite build` passes. |
| Backend regressions | **Verified** | 445 passed. |
| Independent model audit | **Verified** | 19/19 passed. |
| Clean package reproduction | **Verified** | Fresh schema 13; install/execute `reproduced`; `differences={}`. |
| Saved research object | **Verified** | `URO-APP-fa8186f1b037` reopened at 305.7000. |

No model is promoted to `economically_reviewed` or `independently_benchmarked`.

## Evidence

- `artifacts/phase9_2_browser.json` — A–J assertions and mobile measurements.
- `artifacts/phase9_2_final_desktop_jpm.png`
- `artifacts/phase9_2_final_saved.png`
- `artifacts/phase9_2_final_reopened.png`
- `artifacts/phase9_2_final_mobile.png`
- `artifacts/phase9_2_reproduction.json` — clean install/execute, package hash and parent form.
- `artifacts/phase9_2_final_audit.txt` — 19 independent checks.
- `artifacts/phase9_2_benchmarks.json` — timings and source sizes.

## Remaining blockers

1. Genuine master specification is absent and unverified.
2. Common-equity starting book is not implemented; the model uses total stockholders'
   equity and flags `common_equity_status=not_derived_preferred_stock_unmapped`.
3. Point-in-time FR Y-9C is prohibited without a genuine release timestamp.
4. Parent tangible book per share and dollar RWA remain unmapped.
5. Nasdaq automated data access remains unauthorized.
