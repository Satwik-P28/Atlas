# Price-evidence integrity pass (Atlas v3.2, Appendix E follow-through)

Branch: `review/price-intelligence-v3.2-integrity`, based on
`review/price-intelligence-v3.2` at `747871b`. `main` was not changed and no history was
rewritten.

This pass does four things: it corrects publication-time handling to the Temporal
Evidence Kernel's own policy, adds the original-source document pathway for SEC filings,
makes the event explanation name the disclosed item (or say that it cannot), and persists
an investigation as an immutable research object with a change-impact report. It does not
declare any Appendix E benchmark passed.

## 1. Final integrity corrections

| # | Defect | Correction | Evidence |
| --- | --- | --- | --- |
| A1 | A filing with no `acceptance_datetime` used its `filed_date` as if it were available at the start of that day; the warning even said so. | Availability now goes through `availability_from_date`, which pins date-only evidence to `23:59:59Z`. Acceptance stays exact. The event carries `availability_time`, `availability_precision`, `availability_basis` and the policy id `atlas.temporal_evidence.availability.v1`; `filed_date` is retained separately. | `tests/test_price_evidence_integrity.py::test_date_only_filing_is_available_at_end_of_day_and_orders_last` |
| A2 | The timeline was ordered by SEC `filed_date`, not publication time. | Items are sorted by the evidenced availability instant, with the event id as a deterministic tie-break. `filed_date` and `publication_date` are both reported. | `::test_timeline_orders_by_publication_instant_not_sec_filing_date` |
| A3 | The one-candle warning said the return "is therefore reported as zero with this limitation". | The text now says the move is measured from the previous eligible close and refused with a reason when none exists; it never claims a flat 0%. | `::test_one_candle_warning_no_longer_claims_a_zero_return` |
| A4 | The test inventory presented a baseline of 699 as measured, though it was 720 minus 21 by subtraction. | The inventory is schema v2 and separates `observed` counts (collection at this revision) from `reconstructed_by_subtraction`. The verifier recomputes the residual and fails if a reconstructed number is labelled observed. | `scripts/verify_test_inventory.py` |
| A5 | Historical mode did not audit timezone, after-hours publication, corporate actions removed by the cutoff filter, or documents whose own timing was unknown. | Publications now carry local time, phase (`before_open` / `regular_session` / `after_close` / `non_session`) and the first tradable stored session. A UTC/local date difference is warned. Actions removed by `ActionStore`'s cutoff filter are counted, not reported as zero. A document with unknown availability is excluded with a status. | `::test_after_hours_publication_maps_to_the_next_tradable_session`, `::test_publication_local_date_and_timezone_shift_are_reported`, `::test_corporate_action_with_unknown_availability_is_never_placed_in_window`, `::test_unknown_document_availability_excludes_passages` |
| A6 | The window start boundary was end-of-day, which silently dropped publications earlier on the first session's day. | The window begins at `00:00:00Z` and ends at end-of-day. Found while writing the adversarial tests. | `::test_item_novelty_is_relative_to_archived_filings` (both same-day filings must appear) |

Price revisions are unchanged in substance but now audited in historical mode: a provider
revision raises the revision sequence, changes the reproducibility hash, and leaves
`selection.price_vintage` `unverified` with `price_vintage_unverified_at_cutoff`.
`::test_historical_provider_revision_changes_the_hash_and_stays_unverified`.

## 2. Original-source document pathway

`src/atlas/research/filing_evidence.py` resolves each filing to:

* its exact accession, primary document and filing version (`original` / `amendment`);
* a validated SEC archive locator built only from a numeric CIK, an accession in SEC form
  and a plain primary-document filename — otherwise `status: unavailable` and **no URL**;
* the archived document's SHA-256, byte size, parser version and ingestion time when the
  bytes were ingested by the existing Financial Knowledge Engine;
* the 8-K item codes and headings that the document itself contains;
* narrative passages with `unit_id`, section path, character span and span SHA-256, taken
  only from stored `knowledge_unit` rows.

Availability is enforced per document, not per filing: an archived document published
after the information cutoff is `not_available_at_cutoff`, its passages are empty and no
citation is emitted. Text is withheld (`excerpt: null`, `excerpt_withheld: ...`) when the
document's redistribution class is not redistributable.

Amendments never replace originals: the amendment keeps `amends_accession`, is linked to
the original event through `supersedes_event_id`, is marked
`original_evidence_retained: true`, and in retrospective mode is `relation: subsequent`
(shown, excluded from the ranking). Identical primary-document bytes are reported through
`duplicate_document_of` and counted in `duplicates_suppressed`, not silently merged.

In this deployment **no filing primary documents are archived** (the repository has SEC
submission fixtures, not filing HTML). The engine therefore reports
`document.status: not_ingested`, returns the locator, and refuses to produce an excerpt or
an item claim. The pathway itself is exercised against offline fixture bytes in
`tests/test_price_evidence_integrity.py`.

## 3. Company-event explanation

The explanation layer is deterministic and template-based; `analysis.ai_used` is `false`,
and `analysis.epistemic_classes` separates observed facts, inferred mechanism and
unresolved causation. Every hypothesis keeps `causal_status: not_identified`.

* **An 8-K is not an explanation by itself.** When the archived document names item 2.02
  (Results of Operations and Financial Condition), the hypothesis names that item, quotes
  the stored passage with its span, and says the expectations revision is unmeasured.
  When the document is not archived, the hypothesis says Atlas cannot identify the
  disclosed event and gives no item claim.
* **Publication-time matching.** Each disclosure carries its phase and first tradable
  session, so an after-close acceptance on 31 October is attributed to 1 November rather
  than to the session it post-dates.
* **Deduplication** by event identity and by identical document bytes.
* **Issuer relevance** is explicit (`level: direct`, registered to this issuer).
* **Novelty** compares the item against the issuer's earlier *archived* filings and says
  so; "first in the archived record" is never "first in the world".
* **Alternatives and counterevidence** accompany each hypothesis: market co-movement,
  routine filings, unobserved information; counterevidence includes repeat disclosure and
  a market-model expectation that already explains most of the move.

### Source-licence assessment

| Source class | Status in Atlas | Assessment |
| --- | --- | --- |
| SEC filings and 8-K exhibits | `public_domain`, archived metadata; documents archived only when ingested | Legally usable; a filing's own exhibits may carry third-party rights, so exhibit-level rights are needed before quoting them |
| Earnings releases furnished with filings | inside the 8-K / 6-K document, not a separate licensed feed | Usable only through the filing text; no separate release archive is licensed |
| Newswires, press-release aggregators, consensus/estimate history | not present | Not licensed; Atlas reports `unavailable` and abstains. Scraping prohibited archives was not attempted |
| Macro releases with authentic vintages | not present | Needs a vintage-aware licensed source; not simulated |
| Market prices | synthetic project-authored demo series, labelled synthetic | No vendor bytes are redistributed |

No new third-party dependency, archive or scraping path was added. Other news providers
were evaluated only by category above; none is integrated.

## 4. Persisted investigations

`src/atlas/research/investigations.py` stores a `price_investigation` research object
through the existing UROS store (`atlas.research_object.v1`, new kind and spec fields).
The document contains the request, interval, statistics, market model, events with
document spans, hypotheses, rights, calculations and the full reproduction manifest, with
`as_of` set to the cutoff (historical) or the end session (retrospective).

* Saving recomputes the report server-side and refuses an existing name+version.
* `GET /api/research/price-investigations/{id}/reproduce` recomputes and compares hashes.
* `GET /api/research/price-investigations/{id}/impact` returns a change-impact report
  (market observations, company events, amended filings, calculation version, source
  rights, hypothesis ranking) and never modifies the stored object.
* `GET /api/research/price-investigations/{id}/export` refuses when any cited source is
  restricted or unlicensed; otherwise it returns the UROS manifest plus the rights record.

## 5. What was demonstrated

Run on 2026-11-17 in this environment.

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `.venv/bin/python -m pytest -o addopts='' -q` | **752 passed, 0 failed, 0 skipped** (752 collected), 149 s |
| Integrity tests | `.venv/bin/python -m pytest -o addopts='' -q tests/test_price_evidence_integrity.py` | 18 passed |
| Feature tests | `.venv/bin/python -m pytest -o addopts='' -q tests/test_price_explanations.py` | 35 passed |
| Inventory | `.venv/bin/python scripts/verify_test_inventory.py` | observed 752 / 35 / 18; baseline 699 labelled reconstructed; verified |
| TypeScript | `cd web && npx tsc -b --noEmit` | exit 0 |
| Frontend unit | `cd web && npx vitest run` | 5 files, 50 passed |
| Production build | `cd web && npm run build` | exit 0 |
| Specification | `.venv/bin/python scripts/verify_master_spec.py` | v3.2, 357970 bytes, SHA-256 verified |
| End-to-end acceptance | `.venv/bin/python scripts/accept_price_integrity.py` | **32 checks passed, 0 failed** (`artifacts/price_integrity_acceptance.json`) |

The end-to-end run uses the offline demo database: Apple Inc. (`SEC-e5a386bfda8e5d8f951b`),
interval 2024-10-28 … 2024-11-01, real archived 8-K accession `0000320193-24-000120`
accepted `2024-10-31T20:30:25Z`. It verifies the interval selection, the return and three
bases, the after-hours phase and first tradable session, the exact SEC locator, the honest
`not_ingested` document status, the absence of a fabricated excerpt or citation, the
abstention statement, the unlicensed-news warning, historical cutoff admission and
unverified price vintage, then saves, reproduces, change-checks and exports the
investigation. The price series in that database is the project's synthetic demo series,
labelled synthetic; the filing metadata is real and archived.

Not demonstrated in this pass:

* **No live EDGAR retrieval.** EDGAR answers `403` from this environment and the suite is
  offline by design, so the run resolves locators but does not download documents.
* **No browser run.** No browser is installed here. The 19-check Chromium acceptance in
  `web/e2e/price-explanation.mjs` was **not rerun**; its last result is history at
  `747871b`, and the new document/save controls have not been exercised visually.
* **No archived document in the demo database**, so the quoted-passage path is tested with
  offline fixture bytes only.
* No macro-release vintage, licensed news or consensus history exists.

## 6. Appendix E benchmark status

ICB-65 … ICB-75 remain **proposed**. This pass supplies evidence relevant to several of
them — ICB-66 (historical knowledge protection), ICB-67 (event grounding and
uncertainty), ICB-75 (complete price-to-thesis research, partly) — but no independent
criterion has been executed to the standard the specification sets, so no benchmark status
was changed and no registry was regenerated as "passed".

## 7. API surface change

The engine contract is now `atlas.price_explanation.v3` (engine 3.0.0). Five additive
operations on four new paths were added for saved investigations; no existing path,
operation id, parameter, request body or response changed. The OpenAPI fixture was
regenerated after a programmatic diff confirmed four added paths, five added operations,
no removed path and no changed existing path; the test now asserts 162 operations across
147 paths.
