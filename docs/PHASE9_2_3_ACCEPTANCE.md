# Phase 9.2.3 — acceptance, provenance and release integrity

Baseline: `96a398bbd2c68d8a7363efb4323958bb67afa7ec` on
`freebuff/41a4fd2abe41a6515dc8d5bb`. This checkpoint repairs the browser CI that Phase
9.2.2 broke when the restricted JPM prices were removed, exposes the observation identity
in the interface, tightens historical security identity, and reconciles the fixture rights
metadata. It does not add models, asset classes or subsystems.

## 1. The CI fixture mismatch that Phase 9.2.2 introduced

Phase 9.2.2 replaced the Nasdaq and Alpha Vantage history with a project-authored synthetic
`ATLS` series and made `scripts/import_phase9_2_prices.py` load that series by default. The
browser journey `web/e2e/phase9_2.mjs` was not updated: it asserted a JPM close of
`289.91` on `2025-06-30`, the literal source id `user-market-data`, and an *available*
market-implied valuation for JPM.

Every one of those assertions depended on data that had been deliberately deleted. On a
clean checkout the import produced no JPM observation at all, so the market card rendered
"unavailable" and the journey failed at the first price assertion. The workflow was green
only in the sense that nobody had run it.

The journey was not repairable by relaxing assertions: a passing test that fabricates a JPM
stock price would be worse than a failing one. It was replaced by two journeys with
different evidence bases.

## 2. Browser corrections

`web/e2e/phase9_2.mjs` is deleted and replaced by two scenarios, both run by the
`browser-e2e` job on `ubuntu-latest` with Playwright Chromium, desktop `1440x1100` and
mobile `390x844`.

**Scenario A — `web/e2e/phase9_2_jpm.mjs`.** Real, distributable JPM research: SEC filings,
the FR Y-9C consolidated block (RSSD 1039502, `BHCK2170` 4.00T, `BHCAP793` 15.68%) and the
FDIC subsidiary (certificate 628). It exercises the historical cutoff, residual-income
valuation, ROE/cost-of-equity sensitivity against an independent API call, FCFF rejection
for a bank, save/reopen reproduction, package export, existing routes and the mobile
viewport. It asserts the opposite of the old test where prices are concerned: the market
card must read "No observed price matches this issuer", `valuation.market.status` must be
`unavailable`, no price may be rendered, and the saved object must record
`price_included: false` with no observation pin. No JPM price is fabricated, and the text
`289.91` may not appear in the document.

**Scenario B — `web/e2e/phase9_2_market.mjs`.** Synthetic market functionality on `ATLS`:
synthetic labelling on the Markets page, the provenance panel, observation identity versus
the API, exact pin replay, a tampered pin that must report `exact_revision_unavailable`
rather than a substitute price, pin/copy/revision/provider controls, save/reopen of a
research object carrying the pin, and the mobile layout. Synthetic values are asserted to
be labelled synthetic and never described as exchange observations.

The workflow step that provisioned the reference database now also runs
`verify_distributable_fixtures.py --require-demo-db`, so a checkout whose fixtures cannot
support the journeys fails before the browser starts.

Removed assumptions: the `289.91` close, the `user-market-data` source id, the JPM
market-implied valuation, and export-denied market context for JPM (there is no JPM
observation to restrict).

## 3. GitHub Actions results — **not observed**

The workflow is committed and every step it runs was executed locally with the same
commands and fixtures:

| Job | Local result |
| --- | --- |
| backend | `pytest` — 494 passed |
| frontend | 4 unit tests, typecheck and production build pass |
| database-integrity | migrations/storage suites pass |
| research-integrity | market, rights, identity and bank suites pass; reproduction `differences={}` |
| distributable-fixtures | `verify_distributable_fixtures.py --require-demo-db` pass; clean-install pass |
| browser-e2e | **not observed** — no browser runtime in this environment |

GitHub Actions execution could not be observed from this environment: the repository API and
the Actions UI are not reachable, only `fetch`/`push` over the authenticated remote. No run
URL, job conclusion or log is recorded here, and no CI pass is claimed. The pushed commit is
the trigger; the first party who can open the Actions tab should treat the `browser-e2e` job
as the only unverified gate.

## 4. Observation provenance inspector

New `web/src/components/ObservationProvenance.tsx`, embedded in the Markets table
("Inspect" per security) and in the Equity Research market card when a report carries an
observation. It shows, for one selected observation:

security and listing identity, provider and dataset, market session, adjustment convention,
source licence, redistribution class and exportability, retrieval and ingestion timestamps,
revision sequence and the revision it supersedes, the immutable `MOB-…` identifier, the
content hash, and the historical-availability caveat.

Controls: inspect the source, view the revision chain, compare competing provider
observations for the session, pin the exact observation, copy the immutable identifier,
reopen the analysis with the pin, and explicitly update to a newer revision while showing
the resulting change. Replay runs through the existing backend contracts
(`/api/market/replay`, and `/api/equity/{identifier}/report` with `observation_pin`); no
market calculation is duplicated in the browser.

When a pin cannot be resolved the panel shows the exact status
(`exact_revision_unavailable`, `exact_revision_content_mismatch`, `pin_invalid`, or a
security mismatch), keeps the pin, states that reconnection or an explicit update is
required, and never displays the latest quote as if it were the pinned one.

New endpoints: `GET /api/securities/{security_id}/observations`,
`GET /api/market/observations/{observation_id}`,
`GET /api/market/observations/{observation_id}/replay`, `POST /api/market/replay`.

## 5. Exact replay verification

Backend tests and the synthetic journey verify: an identical replay is idempotent and adds
no revision; a correction appends revision 2 while revision 1 stays resolvable; a pin whose
revision is absent returns `exact_revision_unavailable` with `price: null`; a pin whose
content hash was tampered with returns `exact_revision_content_mismatch`; a pin from another
security is refused; competing providers keep independent pins; a saved research object
replays its stored revision after a correction lands, and opting into the newer revision
creates a separate object rather than mutating the old one. Packages keep the immutable
reference, not the value, so a restricted price is never embedded.

## 6. Historical identity policy

`_validate_batch_sessions` now classifies every session instead of flagging and importing:

| State | Treatment |
| --- | --- |
| `verified_assignment` | stored — the session is inside this security's active listing/ticker assignment |
| `source_backfill` | stored — no live assignment, but a verified basis names the permanent identifier, venue, source record and author |
| `ambiguous` | quarantined — rows are excluded, the exact sessions and reason are reported, the batch's other rows still import |
| `known_conflicting_identity` | batch rejected — a session resolves to another security (ticker reuse, migration, delisting, mixed batch) |
| `unsupported_identity` | batch rejected — no venue/assignment evidence exists |

A batch whose every session is ambiguous fails with
`no session in this batch has a verified historical identity` and writes nothing. A backfill
basis must match the resolved security id, the venue, the permanent identifier, cite
evidence, name who established it, and cover the session, so a current ticker is never
accepted as evidence about the past. Backfill records are marked
`distinct_from_live_assignment: true` and retained on the import result.

Imports remain atomic: validation, quarantine filtering and the write happen inside one
transaction, and the content hash is computed over the rows actually stored.

## 7. Data-rights audit

`src/atlas/research/rights.py` separates the two questions that were conflated:

- **copyright licence** — what the holder permits a licensee to do (Apache-2.0, CC0, vendor
  entitlement, nothing);
- **redistribution permission** — whether a recipient of an Atlas artefact may receive the
  bytes.

Classes: `public_domain` (explicit dedication), `project_authored` (original content under
a permissive licence), `permitted` (explicit grant), `user_responsibility`, `restricted`,
`private`, `unknown`. Only the first three are exportable; `unknown` fails closed at import
and at export. A permissive licence presented as `public_domain` is downgraded to
`project_authored` with a warning, and `project_authored` without a declared licence becomes
`unknown`.

`fixtures/market/manifest.json` and `synthetic_manifest.json` were corrected accordingly:
`redistribution: project_authored`, `copyright_licence: Apache-2.0`, an explicit
`public_domain_dedication: false`, and a note that project authorship is not a dedication.
The synthetic source registered by the scripts now uses `project_authored` rather than
claiming `public_domain`. Exportability of legitimate original fixtures is preserved; the
restricted-import path is unchanged.

## 8. Master specification — **blocked**

`ATLAS_MASTER_SPEC.md` is still absent. `scripts/verify_master_spec.py` exits 1 with the
expected size (155419) and SHA-256
(`e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`). No substitute was
generated, so the gate remains blocked and the long-term specification is not claimed as
complete.

## 9. Test counts and verification actually run

- Backend: **494 collected tests pass** (`pytest -q`), including 14 new Phase 9.2.3
  acceptance tests and the extended Phase 9.2.2 identity tests.
- Frontend: 4 unit tests pass; `tsc -b --noEmit` passes; production build succeeds.
- Independent audits: Phase 9.2 `29/29` and Phase 9.1 `16/16`, both `status: pass`.
- Reproduction: `scripts/reproduce_phase9_2.py` — `differences={}`,
  `value_per_share=295.4643539226478`,
  package SHA-256 `3bbaca5447ffbd3421dce48fb833fccbd16a2977fa875e15498aae7bc4d1cfe8`.
- Distributable fixtures: `status: pass`, `exact_replay: true`, demo market
  `redistribution: project_authored`, 10,580 synthetic rows.
- Clean install: packaged AAPL research installed, reopened and executed on a fresh
  database with `differences={}` (`value_per_share=101.21579153430544`).

## 10. Browser screenshots and mobile

Not captured locally. Chromium cannot start renderers in this container, so no desktop
screenshot and no `390x844` measurement is claimed here. Both journeys write
`artifacts/phase9_2_*_desktop.png`, `*_mobile.png`, `*_browser.json` and, on failure,
`*_failure.png`; the workflow uploads them on failure. Mobile acceptance is therefore
**implemented and asserted in code, but not independently observed**.

## 11. Requirements traceability

| Requirement | Status |
| --- | --- |
| Browser tests no longer depend on deleted vendor data | Implemented and tested (locally, by API contract) |
| Real regulatory/SEC evidence in CI | Implemented and tested |
| Labelled synthetic market tests | Implemented and tested |
| GitHub Actions execution observed | **Blocked** — no API/Actions access from this environment |
| Observation identity visible in the UI | Implemented; typechecked and built, not browser-observed |
| Inspect and pin revisions | Implemented; backend tested, UI unobserved |
| Reopen preserves the exact pin | Implemented and backend-tested; UI unobserved |
| Identity ambiguity cannot enter trust silently | Implemented and tested |
| Rights metadata consistent and enforceable | Implemented and tested |
| Financial models reproducible | Implemented and tested |
| Desktop and mobile browser acceptance | **Implemented but not independently verified** |
| Clean installation | Implemented and tested |
| Existing regression suite | Implemented and tested |
| Master specification verified | **Blocked** — genuine file unavailable |
| Historical Git objects scrubbed | **Blocked** — history rewrite not authorised |

## 12. Remaining blockers

1. **CI execution unobserved.** Local reproduction of every step is recorded above; the
   remote run is the outstanding evidence.
2. **Browser/mobile unverified locally** for the reason in §10.
3. **Master specification blocked**; the traceability matrix is therefore provisional.
4. **Historical Git objects** still contain the removed vendor bytes; rewriting published
   history was not authorised.
5. **Regulatory leverage** and FR Y-9C point-in-time reconstruction remain limited by the
   absent bulk publication timestamps, as documented in Phase 9.2.1.
