# Phase 9.4.1 — release decision

## Gate results

| Gate | Requirement | Result |
| --- | --- | --- |
| Repository reconciliation | Merge v3.1 into development without losing either side | PASS — merge `ff71f44`, no conflicts, both parents preserved |
| Specification integrity | v3.1.0 byte-identical | PASS — 333,547 bytes, SHA-256 `d1800cfe…` |
| Registry consistency | 61 sections, four appendices, ICB-01…ICB-64 | PASS — 64 unique ids, 13 registry tests |
| Backend suite | No failures or errors | PASS — full suite exit 0 |
| Frontend unit tests | All pass | PASS — 45 tests, 4 files |
| Typecheck | Clean | PASS |
| Production build | Succeeds, no oversized-chunk warning | PASS — 2.93 s, entry 300.92 kB |
| Browser certification | Real Chromium journey, screenshots, clean console | PASS — 31 assertions, six viewports |
| Visual review | Screenshots inspected, defects fixed | PASS — 8 defects found and corrected |
| Security | No weakened boundary, no executable layout config | PASS — server-validated v2 grammar unchanged in strength |
| Data rights | No export bypass, no rights mutation | PASS — no export path added |
| Performance | Measured improvement, no correctness regression | PASS with caveat — entry −60.8 %, total gzip +4.3 % |

## Decision

**Promote to `main` by fast-forward.** No critical or high-severity defect remains open. The eight
defects found in this phase are fixed and re-verified by the browser journey that found them.

## Conditions attached to this decision

1. **Internal / invitation-beta scope only.** The API is unauthenticated and single-user by design.
   Nothing in this phase makes hosted multi-user deployment safe.
2. **Chromium only.** Single-process Chromium in a container is the certified engine. Firefox,
   WebKit, Safari, screen readers and forced-colours modes are unverified.
3. **Repository stays private.** The history contains restricted vendor market bytes from earlier
   phases; public release still requires a rights and history audit.
4. **No quantitative result panels.** Backtest, factor and risk panels remain unimplemented because
   no validated run contract exists to back them. Their absence is stated in the interface rather
   than filled with simulated output.
5. **Hosted CI unobserved.** All gates ran in this environment; `cloud_git` push is not CI.

## What would block the next release

- Any change to the memo hash, preview/save consistency or export-rights paths without re-running
  their suites.
- Any new panel type that bypasses the server-side layout validator.
- Any hosted deployment without an authentication boundary.

## Phase 9.5 suggested scope

1. Authentication + per-user isolation design, gated before any hosted deployment.
2. A validated backtest/run contract, so ICB quantitative capabilities can be exposed honestly.
3. Cross-browser certification (Firefox/WebKit) and an assistive-technology pass.
4. Runtime performance instrumentation (paint, interaction, memory) to complement bundle numbers.
5. Detached-window docking only if a workflow genuinely requires it.
