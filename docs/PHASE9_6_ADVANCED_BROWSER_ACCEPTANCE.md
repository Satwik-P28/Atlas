# Phase 9.6 — Advanced Filings Panel Acceptance

## Result: NOT CERTIFIED (not executed)

This is the one required deliverable Phase 9.6 did not complete, and it is recorded as a failure
rather than inferred from other checks.

| Check | Result |
| --- | --- |
| `web/node_modules` reinstalled (`npm ci`) | pass |
| Frontend unit tests (45) | pass |
| `npm run typecheck` | pass |
| `npm run build` | pass, entry 301.37 kB (94.33 kB gzip) |
| Advanced `filing` panel Playwright journey | **not run** |
| Standard vs Advanced equivalence under one cutoff | **not measured** |
| Issuer switch / stale-result leak check | **not run** |
| Save / reload / linked-panel restore | **not run** |
| 390 px clipped theme control | **not verified visually** |
| Screenshots captured and inspected | **none** |

## Why

The browser harness needs a live API server on the corpus database plus a Vite preview server, and
the cloud session had no browser available for this phase. Claiming the panel works because the
build compiles would be exactly the substitution this phase forbids: a successful build says
nothing about the panel's behaviour under an issuer switch or a cutoff change.

## What is already true

* The Advanced panel still targets the same authoritative backend routes
  (`/api/knowledge/search`, `/api/knowledge/claims`, `/api/knowledge/documents/{id}`); no
  second evidence path was introduced.
* The Phase 9.5 Playwright harness (`web/e2e/phase9_5_filings.mjs`) is unchanged, so the
  certification can be completed without designing new coverage.
* The retrieval contract changed in a backward-compatible way: new optional fields
  (`query_coverage`, `support_policy`, `absent_terms`) are additive, and existing callers keep
  the balanced policy.

## To close it

1. Start the API on `var/phase9_6.db` and Vite with the preview host allowlist.
2. Extend `phase9_5_filings.mjs` to the `filing` panel: bind issuer → set cutoff → search → open
   passage → inspect provenance → create claim → switch issuer (assert no stale unit ids) →
   save/reload → restore linked state.
3. Capture desktop and 390 px screenshots and inspect them, including the theme control.
4. Compare Standard and Advanced output for one identical query/cutoff/issuer.

Until then no browser-acceptance claim is made for Phase 9.6.
