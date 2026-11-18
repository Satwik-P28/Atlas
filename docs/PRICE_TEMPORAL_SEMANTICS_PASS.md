# Price evidence temporal-semantics pass (v3.2)

Review branch: `review/price-intelligence-v3.2-temporal`, based on
`review/price-intelligence-v3.2-integrity` at `5b8605e`. `main` and
`ATLAS_MASTER_SPEC.md` were not modified. The master specification still verifies at
357,970 bytes and SHA-256
`6ab1a00569a29830deda050c44eaa93dc0f65081be53966ed2a6d00b164447e2`.

This pass resolves the four findings in the draft-PR #4 audit and completes the browser
acceptance that the integrity pass could not run.

## 1. End-of-window explanatory eligibility

Eligibility is now decided by the availability instant, not the SEC calendar filing date:
a filing is an explanatory candidate only when its publication instant is **strictly
before** the final selected session's close. Anything at or after that close is retained
in the timeline with `relation: "subsequent_to_price_window"`,
`explanatory_eligible: false` and an explicit `explanatory_eligibility` object naming the
final session, its close, the first eligible trading session and the reason. It is never
cited as supporting evidence, and `_interpret` abstains with a dedicated
`filing_after_final_session_close` warning.

For the demo Apple 8-K (`0000320193-24-000120`, accepted `2024-10-31T20:30:25Z`) with a
window ending 31 October:

```json
{
  "relation": "subsequent_to_price_window",
  "explanatory_eligible": false,
  "explanatory_eligibility": {
    "final_session": "2024-10-31",
    "final_session_close": "2024-10-31T20:00:00Z",
    "first_eligible_session": "2024-11-01",
    "basis": "publication instant is at or after the final selected session's close",
    "reason": "published at 2024-10-31T20:30:25Z, at or after the close ..."
  }
}
```

Session membership, the final close and the first tradable session come from stored
exchange sessions (`XNYS`), not UTC calendar dates. Weekend, holiday and after-hours
releases therefore resolve to the next stored session; date-only filings are conservatively
available at end-of-day UTC and never at the first second of their date.

## 2. Venue-local publication context

`publication_context` now takes the venue timezone, derives the session date from
venue-local time, and returns `local_time`, `local_date`, `utc_date`, `session_date`,
`is_trading_session`, `tradable_session`, `tradable_session_basis`, `phase` and
`phase_basis`. It handles midnight-UTC crossings (for example 2025-01-02 19:30 Eastern =
2025-01-03T00:30Z, whose session date remains 2025-01-02), after-hours releases, weekends,
holidays and DST boundaries using the IANA database. The timezone-shift warning is emitted
only when the venue-local date genuinely differs from the UTC date.

## 3. Saved-investigation clocks and vintages

Saved documents are schema `atlas.price_investigation.v2` with an explicit
`spec.temporal` block separating:

| Clock | Field | Retrospective value |
| --- | --- | --- |
| Market observation period | `temporal.observation_period` | selected sessions |
| Public knowledge cutoff | `temporal.public_knowledge_cutoff` | run time, basis `analysis_run_time_retrospective` |
| Retrospective analysis time | `temporal.analysis_time` | run time |
| Saved-object creation | `temporal.object_created_at` | run time |
| Source vintages | `temporal.source_vintages` | prices `unverified`, filings by accession |

The top-level `as_of` for a retrospective run is the run time, never the historical
period's end. Historical reconstruction uses the cutoff's end-of-day. Legacy documents
without `spec.temporal` remain readable but are labelled `legacy_document` with basis
`legacy_as_of_field_unverified`; their `as_of` is explicitly not treated as a verified
knowledge cutoff. The top-level UROS research-object schema is unchanged. Adversarial
tests cover later amendments and confirm that a saved object's own clocks and `as_of` do
not change when a later 8-K/A appears; only the impact comparison reports the change.

## 4. Reproduction versus drift

`reproduce` is explicitly a current-state comparison, not pinned-input replay:

* `comparison_kind: "current_state_recomputation"`
* `pinned_input_replay: false`
* `recomputed_at`: the actual recomputation instant
* `guarantee_scope`: states that a matching hash means the current store still produces
  the saved hash and does **not** prove the original inputs were archived or replayed
* impact responses use `comparison_kind: "current_state_drift_check"`

A hash match is therefore reported as reproducibility against today's database, not as
historical replay.

## 5. Browser acceptance

The Chromium harness (`web/e2e/price-explanation.mjs`, headless Chromium via Playwright)
was extended from 19 to **27 checks** and run against a freshly rebuilt demo database on
desktop (1440 px) and mobile (390x844): **27 passed, 0 failed, 0 console or page errors**.
It covers the original SEC document link, resolved passages with citation spans, citation
inspection, Save Investigation, duplicate-save refusal, Check for Changes, reopening saved
work with its clocks, authorized export, restricted export, failed requests with retry,
and mobile layout, touch selection, save and rights.

Screenshots (in `artifacts/`):

| File | Shows |
| --- | --- |
| `01-audit-desktop-panel.png` | investigation panel and statistics |
| `02-audit-desktop-resized.png` | coherent overlay after resize |
| `03-audit-error-state.png` | retryable API error |
| `04-audit-export-disabled.png` | restricted export explains why |
| `05-audit-document-passages.png` | after-final-close badge, original SEC link, fixture passage and citation |
| `06-audit-saved-investigation.png` | saved object with retrospective `as_of` |
| `07-audit-reopened-saved-work.png` | reopened snapshot, observation period and knowledge cutoff |
| `08-audit-desktop-final.png` | panel after closing Explain mode |
| `09-audit-mobile-chart.png` | mobile chart |
| `10-audit-mobile-panel.png` | mobile investigation panel |
| `11-audit-mobile-saved.png` | mobile saved summary and actions |
| `12-audit-mobile-rights.png` | mobile export and rights |

UI defects found during this pass and fixed: a stale duplicate-save error remained visible
after Check for Changes or reopening; the saved summary and action buttons wrapped
mid-sentence on mobile; saved objects whose historical end date had no stored ticker were
named with a raw security id; the reopened snapshot repeated its mode label; and the
after-close abstention text used "1 filing(s)". The saved list now uses the current ticker
only as a display label and never as the ticker in force at the observation date.

## 6. Independent verification

All commands were run in this workspace on 2026-11-17:

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `.venv/bin/python -m pytest -o addopts='' -q` | **762 passed**, 0 failed, 1 warning (135 s) |
| Focused temporal/feature | `pytest tests/test_price_evidence_integrity.py tests/test_price_explanations.py` | 63 passed |
| Frontend unit | `cd web && npx vitest run` | 50 passed (5 files) |
| Typecheck | `cd web && npx tsc -b --noEmit` | exit 0 |
| Production build | `cd web && npm run build` | built in 3.14 s |
| Browser E2E | `node e2e/price-explanation.mjs` | 27 passed, 0 failed, 0 console/page errors |
| End-to-end acceptance | `scripts/accept_price_integrity.py` | **46 passed, 0 failed** |
| OpenAPI compatibility | `pytest tests/test_phase9_2_7_market_series.py` | 17 passed; 163 operations / 148 paths |
| Spec checksum | `scripts/verify_master_spec.py` | size and SHA-256 verified |
| Test inventory | `scripts/verify_test_inventory.py` | observed 762, reconstructed baseline 699 labelled |
| Research-object integrity | reopen + `reproduce` + `impact` in acceptance | saved v2 document validates, legacy path tested |

The OpenAPI fixture was regenerated additively: one added path (GET saved investigation),
no removed or changed existing path. The acceptance artifact is
`artifacts/price_integrity_acceptance.json`; the inventory is
`artifacts/test_inventory.json`.

## 7. Evidence, licences and limitations

* **Filing metadata is real and archived** (SEC submissions fixtures, including the Apple
  8-K accession, acceptance time and primary-document locator).
* **No live EDGAR retrieval was attempted in this pass.** The environment is offline by
  design, so no live document was downloaded or quoted.
* **The demo database has no archived filing HTML.** Passage and citation rendering in the
  browser was exercised with an offline UI fixture that says
  "TEST FIXTURE: offline UI fixture ... not a real Apple excerpt." The production
  `not_ingested` path was verified separately: it returns no fabricated excerpt or URL.
* **Demo prices are the project's deterministic synthetic series**, labelled synthetic.
  No licensed market data, news archive, consensus history or macro-release vintage is
  present, and no accuracy or predictive claim is made.
* **No ICB benchmark is marked passing.** ICB-65 … ICB-75 remain proposed; this pass
  supplies evidence for several but runs no independent benchmark acceptance.
* **Browser coverage is Chromium-only** at desktop and one mobile viewport. Other
  browsers, real screen readers and assistive technology were not tested.

## 8. Remaining gaps

1. Pinned-input replay is not implemented. Reproduction is a current-state comparison and
   is labelled as such.
2. The demo database does not archive filing HTML; live ingestion and quotation require a
   licensed/allowlisted EDGAR retrieval path.
3. Prices, news, consensus and macro releases remain unavailable/unlicensed; temporal
   correctness is verified against synthetic prices and archived filing metadata.
4. No ICB benchmark has acceptance evidence sufficient to change its status.
5. Mobile verification covers layout and touch interaction at 390x844, not a device lab.
