# Phase 9.2 acceptance matrix

Status at the acceptance pass. "Verified" means a command or browser assertion was run
in this worktree; it does not upgrade economic validity.

| Area | Status | Evidence / remaining gap |
| --- | --- | --- |
| Genuine master specification | **Blocked** | File absent; verifier exits 1. No substitute was generated. |
| Versioned migrations 11–12 | **Independently verified** | Fresh install, 9.1→12 upgrade with preserved rows, interrupted rollback, repeated startup, concurrent startup, backup restore: 6 tests pass. |
| Read-only service constructors | **Independently verified** | Constructor leaves a version-10 database without regulatory DDL. |
| FDIC subsidiary evidence | **Independently verified** | JPM CERT 628 and GS Bank USA CERT 33124, six periods; explicit `subsidiary_standalone` basis. |
| Consolidated FR Y-9C | **Blocked** | No official observation retrieved. `parent_capital.status` is `blocked_fr_y9c_unavailable`; subsidiary capital is never promoted. |
| Parent/subsidiary separation | **Independently verified** | Mixed basis and period tests raise reconciliation errors. |
| Bank residual income v2 | **Partially implemented / verified arithmetic** | Executes on consolidated SEC equity; tangible equity is subsidiary-only; no segment forecast; contract stops at arithmetic verification. |
| Implied cost of equity | **Independently verified** | June-2025 JPM: 9.80%, residual 1.4e-8, unique root, converged in 28 iterations. Earlier 8.75%/8.66% values are not repeated as current. |
| Information cutoff | **Partially browser verified** | API at 2025-06-30 selects price 2025-06-30, accounting 2024-12-31, filing 2025-02-14. UI passed the cutoff to report after fixing the DCF path; see browser notes. |
| Price history cutoff | **Independently verified** | History truncated to the cutoff; future sessions excluded. |
| Nasdaq automated collection | **Blocked / disabled** | No provider authorization record. The importer is local CSV only; series are `automated_access_authorized=0`, `restricted`. |
| Restricted-data containment | **Independently verified** | Price value excluded from `report.md`, packages and downloaded artifact names; package state `price_included=false`. |
| JPM browser workflow | **Partially browser verified** | Production bundle renders; JPM selects; CERT 628 card visible; ROE/CoE controls submit; DCF rejected; cutoff 2025-06-30 produced price 289.91 on 2025-06-30, accounting 2024-12-31, implied CoE 9.80%; package fetch 66,636 bytes with `price_included=false`. Desktop screenshots saved. |
| Frontend unit tests | **Verified** | 4/4 pass. |
| Production frontend build | **Verified** | `tsc -b && vite build` passes. |
| Full backend regressions | **Verified** | 437 passed after the migration, cutoff, rights and solver changes. |
| Independent model audit | **Verified** | 16/16 checks pass after replacing the period-end equality test with cutoff-safety. |
| Clean package reproduction | **Independently verified** | Application install/execute reproduces outputs from the packaged public snapshot. |
| 390 px mobile layout | **Unverified** | No completed viewport assertion. |
| Save/reopen research | **Unverified** | No dedicated save/reopen journey completed in this pass. |

No model is promoted to `economically_reviewed` or `independently_benchmarked`.


## Browser evidence

- `artifacts/phase9_2_browser_initial.png` — production bundle and issuer list.
- `artifacts/phase9_2_browser_jpm.png` — JPM and regulatory card.
- `artifacts/phase9_2_browser_cutoff.png` — cutoff interaction.
- June-2025 report: price 289.91 on 2025-06-30; accounting period 2024-12-31;
  filing availability 2025-02-14; implied cost of equity 9.80%, residual 1.4e-8,
  unique root; restricted export.
- DCF message: `rejected_method`; FCFF is inadmissible for a bank.
- Package response: HTTP 200, 66,636 base64 bytes, `price_included=false`.
- No console errors; document, CSS, JS and API requests returned 200.

The 390 px screenshot could not be captured because the browser tool rejected viewport
resizing (`options.mode must be one of: strip`). It is not reported as verified.
