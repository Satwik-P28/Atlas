# Phase 9.6.3 — Browser acceptance

## Status: not re-certified in this phase

The 9.6.2 journey passed 23/23 on this frontend. No frontend source changed in 9.6.3 (only
backend research modules, tests and scripts). Re-running `web/e2e/phase9_6_2_advanced.mjs` against
a restarted API failed at the first gate: the workstation never populated its instrument list
within 30 seconds (`page.waitForFunction` timeout), with zero console errors and zero failed
requests. That is an environment/startup symptom, not a verified regression, and it is **not**
reported as a pass.

## What is still covered

* Frontend unit tests: 50 passed (layout invariants from 9.6.2 included).
* TypeScript typecheck and production build pass.
* The backend the UI calls was exercised directly by the API health check and the case-study and
  evaluation runners.

## Required before release

Re-run the Advanced journey (including link groups A–D, two issuers, mode/cutoff persistence and
390×844) against a clean API and Vite start, and inspect desktop and mobile screenshots. Until
then, browser acceptance for 9.6.3 is **open**.
