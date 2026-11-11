# Phase 9.4 — final implementation report

## 1. Commits

- Starting commit: `e0b3119fca3a97c7fe5e9acc215a8975738ce576` (verified `main` and development tip,
  658 backend tests, 4 frontend tests, spec v3.0.0 verified).
- Ending commit: the commit that adds this report — the branch tip
  (`git log -1 --format=%H`). It is the only commit of this phase; nothing was force-pushed and
  `main` was not advanced.

## 2. Files changed

Backend: `src/atlas/terminal/workspaces.py` (v2 layout grammar, link groups, three panel types),
`src/atlas/terminal/api.py` (layout schema in `/api/schema`), `tests/test_phase9_4_workspace_layout.py`.

Frontend: `App.tsx`, `main.tsx`, `types.ts`, `components/SecuritySearch.tsx`,
`design/tokens.css`, `design/advanced.css`, `shell/StandardShell.tsx`, `shell/AdvancedShell.tsx`,
`terminal/links.ts`, `terminal/linkContext.tsx`, `terminal/command/{registry.ts,CommandPalette.tsx}`,
`terminal/docking/{layout.ts,Workbench.tsx}`, `terminal/panels/registry.tsx`,
`pages/Workstation.tsx`, and tests `docking/layout.test.ts`, `command/registry.test.ts`,
`links.test.ts`.

Verification assets: `web/e2e/phase9_4_workstation.mjs`, this documentation set.

## 3. New dependencies and licences

None. React 19, Vite, Lightweight Charts, Vitest and Playwright were already present.
`flexlayout-react` (MIT, 0.11.1, React 19 peer range) was evaluated and not adopted; the reasons
are in the research document (§3).

## 4. Architecture changes

- One router, two shells, one data layer. `App.tsx` selects Standard or Advanced from the
  persisted setting; both mount the same routes and the same API modules.
- A validated layout grammar (`atlas.workspace.v2`) implemented twice — Python for persistence,
  TypeScript for editing — with the same refusals on both sides.
- Link-group context with a pure reducer; panels declare accepted parameters.
- Typed command registry with candidates on failure, executed only by real handlers.
- Typed panel registry replacing page-specific fetch code inside the desk.

## 5. Actual functionality implemented

Two distinct interfaces; a six-panel default desk with splits, tabs, resize, drag-to-dock,
maximize, add/close, save, reopen, reset and invalid-layout recovery; a command palette with
instrument/workspace/cutoff/panel commands and typed errors; link groups A–D with a desk-wide
cutoff and availability mode; eight real panels; v2 workspace persistence with server-side
validation and an unchanged v1 path; shared instrument search.

## 6. Features deferred

Detached windows and multi-monitor docking; route-level code splitting; table virtualisation;
backtest-result inspection (no validated run contract); factor/risk decomposition; authenticated
multi-user deployment. Each is named in the product where a user could otherwise expect it.

## 7. Screenshots and visual review

**None.** No screenshot was produced, and no visual review was performed, because no browser could
start in this environment. No claim in this report is based on seeing the interface render.
The design was checked by reading the token values, computing WCAG contrast ratios, typechecking
and building the production bundle — which is not the same thing.

## 8. Test outcomes

| Suite | Result |
| --- | --- |
| Backend (full) | PASS — no failures, errors or skips |
| New layout tests (13 cases) | PASS |
| Frontend unit (45 tests, 4 files) | PASS |
| TypeScript typecheck | PASS |
| Production build | PASS (2.89 s) |
| Master specification v3.0.0 | PASS — byte-identical, SHA-256 `c1228db9…` |
| Browser journeys | NOT EXECUTED |

Four frontend tests failed on first run; two were incorrect expectations (tab-group identity after
a split, and a mode label), and one exposed a real bug — `completeCommands` trimmed a trailing
space, so `AAPL ` never offered topics. The implementation was fixed, not the assertion.

## 9. Browser outcomes

BLOCKED with evidence: Chromium 156 downloaded, NSPR/NSS extracted unprivileged, nine X11/GTK/ALSA
libraries still unresolved, archive fetches 404, `sudo` refused by the sandbox policy. No journey,
screenshot, console capture or network capture exists. Details in the browser acceptance report.

## 10. Performance measurements

Build 2.89 s; JS 767.15 kB (225.52 kB gzip); CSS 57.46 kB (11.10 kB gzip); Vitest 45 tests ≈4 s.
No runtime measurements were possible. The >500 kB chunk warning is recorded as a regression risk
with route-level splitting as the next step. Backend memo timings are unchanged and were not
re-run.

## 11. Security findings

- Workspace documents remain data: unknown node types, unknown keys, duplicate or orphaned panels,
  bad weights and excessive nesting are refused by the server, so a saved layout cannot carry
  executable configuration.
- The command parser executes only registered handlers; there is no shell, no `eval`, no dynamic
  import from a command string.
- No new network surface, no CORS change, no auth change. The API remains unauthenticated and
  loopback-oriented; this phase does not make it safe for hosted multi-user use.
- Focus states, `aria-selected` tabs, separators with keyboard resizing and labelled controls were
  added; this improves accessibility but is unverified by an assistive-technology pass.

## 12. Data-rights findings

No rights logic changed. Panels display the badges and licences the API returns; the memo panel
exposes only listing and change-check, never an export that could bypass the rights engine. The
repository stays private: earlier commits still carry restricted vendor bytes.

## 13. Master-spec compliance

The specification is byte-identical (289,963 bytes, SHA-256 `c1228db9…`). All 61 requirements and
48 ICB rows are untouched. This phase adds presentation and a new persisted document version; it
does not amend the specification. If the project wants the workstation recorded in the spec, that
is an explicit specification change, not a silent one.

## 14. Remaining blockers

1. Browser execution (all six viewports, docking, palette, mobile) — environment-blocked.
2. Visual acceptance — impossible without a browser.
3. Phase 9.3 memo browser journey — still outstanding for the same reason.
4. Bundle size — 767 kB single chunk; needs splitting.
5. Hosted CI — unobserved in this environment.

## 15. Release recommendation

**Internal research use only.** Not invitation beta, not public beta. The workstation is a real
engineer-verified implementation at the model, type and test level, but a professional interface
cannot be certified by a typecheck. The gate to clear is one browser run of
`web/e2e/phase9_4_workstation.mjs` with screenshots inspected; until then, presentation defects
are probable and unmeasured.

## 16. Next engineering priorities

1. Run the committed journey in a browser-capable environment; fix what it finds.
2. Split the bundle by route and measure against the 767 kB baseline.
3. Add table virtualisation for large claim registers and screeners.
4. Define a validated backtest-run contract before exposing QuantConnect-style result panels.
5. Browser-level memo journey from Phase 9.3, including export-byte verification.
6. Authentication boundary before any hosted, multi-user deployment.
