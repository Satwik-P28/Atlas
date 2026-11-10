# Phase 9.3 acceptance — evidence-grounded memos, claim verification, versioning, change detection

Checkpoint date: 2026-11-10. Branch: `freebuff/41a4fd2abe41a6515dc8d5bb`.

| Item | Value |
| --- | --- |
| Starting commit | `37142b54fb4113cc1d929f2835cd4776d38eab61` |
| Master specification | v3.0.0, 289,963 bytes, SHA-256 `c1228db9…c4752d`, verified |
| New modules | `atlas/research/claims.py`, `atlas/research/memo.py`, `atlas/research/changes.py` |
| Modified | `atlas/research/objects.py` (kind `memo`), `atlas/research/equity.py` (narrative), `atlas/terminal/api.py`, `web/src/{api.ts,pages/EquityResearch.tsx}`, registries, README |
| Database migration | **none** — the memo reuses `research_object`; schema stays at 13 |
| Memo contract | `atlas.research_memo.v1` (version `1.0.0`) |
| Claim contract | `atlas.research_claim.v1` (version `1.0.0`, arithmetic `atlas.claim.arithmetic.v1`) |
| Change report | `atlas.research_change_report.v1` |
| Integrity report | `atlas.research_integrity.v1` |

## 1. What was built, and what it refuses to do

The existing equity report was **upgraded, not duplicated**. `EquityResearchService.analyse()`
still produces the Markdown report; the memo layer turns the same analysis into a typed claim
register, verifies it, and renders exports from that register.

Refusals that are enforced in code and pinned by tests:

* a factual claim without resolvable evidence is `missing_evidence`, not a fact;
* a claim citing another issuer, a different period, unit, currency or value is `unsupported`
  with a named diagnostic;
* evidence available after the cutoff is rejected;
* an analyst assumption or hypothesis never carries a factual outcome;
* a model output requires a passing independent component audit and a matching compiler
  version;
* export is refused when a cited source is not redistributable;
* a saved memo version is never rewritten, and change detection never re-points a claim.

## 2. The report-narrative defect

`_render_report()` described every issuer as a "non-financial operating company". It now calls
`methodology_narrative(eligibility)`, which is derived from the business-model classification
that selected the method:

* JPM (SIC 6021, bank holding company) — "`residual_income_equity`… `unlevered_fcff_dcf` is
  not applied to this issuer type";
* AAPL (SIC 3571, operating company) — "`unlevered_fcff_dcf` for an operating company".

The same fix applies to the unavailable-valuation label, which now names the rejected method
and the business model instead of saying "DCF unavailable". Both directions are pinned by
tests.

## 3. Claims observed on the reference database

| Issuer | Method | Claims | Verified | Not applicable (assumption / hypothesis / disclosure) | Unsupported |
| --- | --- | --- | --- | --- | --- |
| JPM | `residual_income_equity` (v3) | 36 | 12 | 24 | 0 |
| AAPL | `unlevered_fcff_dcf` | 48 | 21 | 27 | 0 |

Every observed fact and every derived metric verified; every model output verified against
its recorded audit. The 24 and 27 non-factual claims are assumptions, the research-question
hypothesis and methodology disclosures, which carry the explicit `not_applicable` marker.

## 4. Research integrity outcomes

| Issuer | Evidence | Computational | Statistical | Decision |
| --- | --- | --- | --- | --- |
| JPM | pass | pass | not_applicable | **fail** — verdict not economically supported |
| AAPL | pass | pass | not_applicable | pass |

The JPM decision failure is the correct result: residual-income v3 stops at "arithmetically
verified", with no economic review or external benchmark recorded. Reporting it as a pass
would be the failure this dimension exists to catch.

## 5. Versioning, exports and citations

* Saving writes an immutable `research_object` of kind `memo`; a second save creates a new
  version and the first hash is unchanged.
* `compare()` reports added, removed and changed claims with before/after values, plus
  assumption and model-fingerprint differences.
* Export formats: Markdown, sanitized HTML, JSON. Each carries a manifest with the SHA-256 of
  the exported bytes, the memo content hash, evidence dependencies, observation pins, model
  fingerprints, integrity outcomes and the rights decision. A tampered export is detected by
  `verify_export()`.
* Citations resolve to accession number, form type, filed date, acceptance timestamp, period,
  concept, value, unit, evidence id, source document id and content hash. `passage` is `null`
  with a stated reason: Atlas does not invent page numbers or quotations.
* HTML escapes all source and analyst text; an injected `<script>` renders as text.

## 6. Verification results

| Gate | Result |
| --- | --- |
| Phase 9.3 tests (`tests/test_phase9_3_research_memo.py`) | **39 passed** |
| Full backend suite | **654 tests, 0 failures, 0 errors, 0 skipped** |
| Frontend tests / typecheck / build | 4 tests passed, `tsc -b --noEmit` clean, `vite build` succeeded (2.64 s) |
| Master-spec integrity | pass (size and SHA-256) |
| Requirements + ICB registry validation | pass |
| Financial audits 9.2 / 9.1 | 29/29 and 16/16 |
| Reference reproduction | 295.4643539226478, differences none |
| OpenAPI contract | 147 routes across 133 paths; the 139-route Phase 9.2.7 capture is unchanged for every existing path and the baseline fixture was regenerated for the eight additive memo routes |
| Hosted GitHub Actions | **unobserved** (private repository, no Actions credential) |

### The pre-existing `artifacts/phase9_1_model_audit.json` diff

The regenerated audit artifact differs from the committed one only in the `db` field and the
`model` value of the two `package_deterministic` checks (the recorded `package_sha256`
prefix). Two consecutive runs against the same database are byte-identical, all 16 checks
pass in both files, and every `passed` verdict is unchanged. The difference is therefore
environment-dependent: the package hash embeds the snapshot of the rebuilt demo database, so
it changes when that database is rebuilt rather than when the model changes. The artifact was
left uncommitted and is reported here instead of being committed as if it were a new result.

## 7. Browser and mobile

Not executed in this checkpoint. No desktop or 390×844 result is claimed for the new memo
panel. The last executed browser evidence remains the Phase 9.2.5 run at `af4e184`. The panel
was added with `data-testid` hooks (`equity-memo-panel`, `equity-memo-create`,
`equity-memo-save`, `equity-memo-check`, `equity-memo-export-*`) so the journeys can be
extended without touching the assertions.

## 8. Registry and ICB status

* Clause-level traceability for the clauses actually implemented:
  `artifacts/research_memo_clauses.json` (12 clauses, validated by a test for unique ids,
  allowed statuses and existing referenced paths). The 61-section registry remains
  section-level and is not presented as a decomposition of the whole specification.
* Sections 6, 39, 52, 54, 56, 59 and 60 were corrected to describe what now exists.
* ICB-02 was corrected: curve and bond pricing primitives **do** exist in
  `atlas/institutional/service.py`, so the entry no longer claims complete absence. Coverage
  is incomplete, and published-vector parity, derivative breadth and stress remain missing.
* ICB-39 and ICB-48 gain verified prerequisites. **Neither is promoted.** ICB-48 remains
  `vision_only` because it needs an independently produced analyst baseline, a licensed price
  feed and narrative retrieval.

## 9. Performance

The memo reuses the existing analysis, so it adds no new market-data query path and the bulk
overview is untouched (9 statements, 4.29 s at 1,000 securities). Claim verification issues
one batched evidence query per verification pass plus per-input batches; no query iterates the
evidence table. Benchmarks for memo generation, citation resolution, export, reopen and change
check were **not** run in this checkpoint and are not claimed.

## 10. Remaining blockers

1. **Narrative evidence retrieval is absent** (Section 49). The memo can cite structured XBRL
   facts and model output, not the filing's prose. This is now the smallest gap for an
   external user.
2. **Monitoring is on demand only.** No scheduler, background worker or notification delivery.
3. **No PDF export**; no spreadsheet or notebook import.
4. **Hosted CI unobserved**; browser and mobile journeys not re-executed at this revision.
5. Standing release restrictions unchanged: restricted historical vendor bytes in earlier
   commits, unauthenticated API with explicit non-loopback acknowledgement, unverified external
   beta, incomplete proprietary coverage.
