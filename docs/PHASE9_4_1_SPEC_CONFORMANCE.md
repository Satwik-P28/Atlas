# Phase 9.4.1 — master specification v3.1.0 conformance

Authoritative document: `ATLAS_MASTER_SPEC.md` v3.1.0, 333,547 bytes, SHA-256
`d1800cfea35d973e2ff2b3570f8bf564fd3a7aceabca2f623ec5de17931a1111`, verified by
`scripts/verify_master_spec.py`. 61 numbered sections, four appendices, ICB-01…ICB-64.

Scope note: this matrix covers the **Phase 9.4 workstation work**. It does not claim that Atlas
implements the specification's future quantitative systems merely because v3.1 describes them.

| Contract | Implemented behaviour | Evidence | Missing behaviour | Status |
| --- | --- | --- | --- | --- |
| Eight-system architecture, one experience | Two shells, one router, one API layer; no second calculation engine | `web/src/App.tsx`; all pages import the same `api.ts` and `format.ts` | Systems beyond research/workstation UI are not newly surfaced | Partial (UI layer only) |
| Shared UROS / TEK / FEC contracts | Panels consume the same evidence, statement and metric contracts as Standard pages | `terminal/panels/registry.tsx` reuses `StatementTable`, `Chart`, `api.*` | No new contract was introduced, none weakened | Conforms |
| Standard vs Advanced equivalence | Same routes, data, formatting and decisions in both shells; only composition differs | `App.tsx`; identical panel and page components; tests | — | Conforms |
| Data provenance and historical time semantics | Every value has an evidence path; cutoff and availability mode are desk-wide and stated | evidence inspector; `links.ts`; cutoff in header/status bar | Evidence panel not pinned across reload (by design) | Conforms |
| Security and permissions | No auth added or weakened; layout documents validated server-side; commands cannot execute code | `workspaces.py` v2 validator; `registry.ts` parser | API remains unauthenticated, loopback-oriented | Conforms within documented boundary |
| Research object persistence | `atlas.workspace.v2` persists panels, link groups and layout; v1 still loads; invalid layouts degrade safely | `workspaces.py`; `layout.ts`; both test suites | No cross-device sync beyond the existing store | Conforms |
| Workstation and application composition | Dockable desk, command palette, link groups, inspector, eight panels | `Workbench.tsx`, `CommandPalette.tsx`, panels | Detached windows, multi-monitor, workspace duplication | Partial |
| Data rights and exports | No new export path; memo exports untouched and still refuse unauthorised sources | `PHASE9_4_FINAL_REPORT.md` §12; phase 9.3 tests | Export bytes not re-verified in this phase | Conforms (unchanged) |
| ICB-49…ICB-64 capabilities | Scoreboard and registry now cover 64 benchmarks; registry test enforces the full id set | `artifacts/icb_registry.json`; registry tests (13 pass) | Capabilities remain `vision_only`/`prototype_verified` — no new status claimed | Conforms |
| Performance expectations | Entry chunk split by route; measured before/after | `PHASE9_4_1_PERFORMANCE.md` | No runtime latency measurement | Partial |
| Browser certification | Executed: 31 assertions, six viewports, screenshots | `PHASE9_4_1_BROWSER_ACCEPTANCE.md` | Single browser engine only | Conforms (Chromium) |
| Testing and release gates | Backend suite, 45 frontend tests, typecheck, build, spec integrity, registry consistency, browser journey | this phase's logs | Hosted CI still unobserved | Conforms locally |

## Reconciliations made instead of documentation edits

- The merged registry test still expected 48 unique ICB ids; the v3.1 registry has 64. The test was
  corrected with a comment, and the full ICB-01…ICB-64 assertion was left untouched.
- Phase 9.4 reports described browser acceptance as blocked. That statement is now false; it is
  superseded by `PHASE9_4_1_BROWSER_ACCEPTANCE.md`, and the older file is retained unchanged as a
  historical record of the Phase 9.4 environment.
- Phase 9.4 described a 767 kB bundle. It is now 301 kB entry / 754 kB total, measured above.

## Remaining gaps against v3.1

1. Quantitative result panels (backtest, factor, risk decomposition) have no validated run
   contract to expose; presenting them would fabricate results.
2. Detached/multi-window docking and saved personal templates are unimplemented.
3. Authentication and per-user isolation are prerequisites for any hosted deployment.
4. Cross-browser and assistive-technology verification.
