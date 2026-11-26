# Phase 10I: financial answer reliability hardening

**Branch:** `focus/financial-answer-hardening-v1` (from `0090573`, not merged, PR #7 untouched)
**Commits:** `36cff3e` implementation, archive, adjudication, experiments and this report;
`bfbf3b1` hosted-CI branch registration; `7d34472` full-history checkout for the archive audit.
**Hosted CI:** run #67 (`45284314381`) succeeded on `7d34472`. Run #66 (`45283530352`) failed on
`bfbf3b1` because the archive audit reads frozen blobs at named commits and the default depth-1
checkout has no history; it was fixed by fetching full history, not by weakening the audit.
**Scope:** the geometry-aware resolver, the baseline resolver it is compared with, and the
statement/concept vocabulary both use.
**Primary objective:** stop producing *confidently wrong* financial answers. Coverage is secondary.

This report is deliberately split between claims that are measured and claims that are not. The
first prospective holdout (23/47 and 33/47, 7 and 4 false answers) remains the historical record;
it is preserved, archived and never overwritten. Every number below that re-scores those twelve
issuers is labelled **post-holdout development**.

## 1. What changed, in one page

| area | before | after |
|---|---|---|
| statement identity | regex on a title line; a note naming "consolidated balance sheets" was the balance sheet | shared classifier: title, note, section-heading, segment and consolidating forms; notes cannot outrank statements |
| reporting scope | "consolidated" preferred by a score bonus | hard exclusion of parent/segment/subsidiary/consolidating members; column groups inside a consolidating table are modelled |
| concept matching | substring scoring with a 2.0 floor | closed-vocabulary matching: every word of a label must belong to the concept |
| net income | one concept | consolidated vs attributable, with a definitional-ambiguity refusal |
| arithmetic | scale/period/currency checks | plus same-accession, consolidated-scope, explicit-period and zero-denominator checks with typed refusals |
| answer packet | citation list | full evidence contract and four separate verification stages |
| preprocessing | re-parsed every time | geometry cached by document SHA-256 |
| audit | replay of the frozen run against live code | archive verification at the named commits + explicit live-drift reporting |

## 2. Root causes (each one observed, not hypothesised)

1. **A note was classified as the statement.** Intel's consolidated balance sheet (182,103) was
   untitled — the page above it was audit-report boilerplate — so it entered the "unknown family"
   tier. The table that won was headed *"Amounts Offset in the Consolidated Balance Sheets"*: the
   phrase "balance sheets" satisfied the title regex, so a note about the balance sheet became a
   strong candidate and the 2,932 fair-value total was returned as Intel's total assets.
2. **A row label inside a note satisfied a consolidated concept.** Oracle's revenue resolved to
   `Differences in timing of revenue recognition` (623) because the word "revenue" appeared in the
   label and the table carried a 2022 column. The same defect, in the flattened path, read
   `Sales and marketing` (8,047) as revenue, `Net (purchases), sales and maturities of marketable
   securities` (−1,651) as UPS revenue, and `Total current assets` (25,224) as Abbott's total
   assets.
3. **Statement titles were not recognised in the forms filers actually print.** Boeing's
   `Consolidated Statements of Financial Position` (plural) did not match `statement of financial
   position`, so the real balance sheet was untitled while a *"Selected financial data for BCC"*
   page headed `Financial Position` (1,954) was classified as a balance sheet. Caterpillar prints
   `Consolidated Financial Position` and `Consolidated Results of Operations`; neither matched.
4. **Consolidating column groups were invisible.** Caterpillar prints the same balance sheet four
   times side by side (Consolidated, Machinery Energy & Transportation, Financial Products,
   Consolidating Adjustments). Without a group model, four `Total assets` values competed and the
   question was refused; with a group model, only the consolidated column is eligible.
5. **Two net-income definitions were one concept.** Disney prints `Net income (loss)` 3,505 and
   `Net income attributable to Disney` 3,145. The old resolver returned whichever matched first.
6. **Smaller mechanical defects:** footnote markers (`Total assets(a)`) broke literal citation
   matching; a `$` inside the printed cell broke raw-text citation matching; and period columns
   were chosen without preferring the candidate whose own header names the year.

## 3. Architecture

New module `src/atlas/research/statement_scope.py`:

- `classify(text) -> StatementClass(family, scope, title, evidence)` with families
  `income | balance_sheet | cash_flow | equity | segment | note | unknown` and scopes
  `consolidated | consolidating_member | parent | segment | subsidiary | unknown`.
- Note markers ("amounts offset", "fair value", "supplemental", "reconciliation", "rollforward",
  "selected financial data", "disaggregat", …) are checked before title patterns, so a table
  *about* a statement is a note. Section headings (`Item 8 …`) are explicitly not titles.
- `group_scope(label)` classifies column groups; a banner pair (`STATEMENT 1` / registrant name)
  is not a group.
- `title_from_text(text)` extracts the last title-shaped line and ignores page numbers and prose.

`financial_concepts.py` now has a closed vocabulary per alias (`ALIAS_VOCABULARY`), plural folding
for matching only (`_stem`), footnote-aware canonicalisation (`canonical_label`), and an explicit
`component_sum_supports_total` rule: a `Total …` row beats its components **only when the
components add up to it**. New concepts: `net_sales`, `total_revenue`, `net_income_attributable`.
`net_income` refuses with `definitional_ambiguity` when the same statement prints a differing
attributable row.

`table_geometry.py` records `column_groups`, inherits statement identity from in-table header
lines, demotes tables whose immediate context is a note, and caches parsed geometry by document
digest.

`geometry_resolution.py` applies a strict candidate hierarchy: strong (family matches, scope
compatible, consolidated column), weak (unidentified table that prints companions or enough
statement line items), and note-only (all note candidates agree on one value). Every tier
produces a typed status: `resolved`, `ambiguous` (`conflicting_row_values`,
`conflicting_note_values`, `definitional_ambiguity`), `scope_mismatch`, `period_not_located`,
`unit_unresolved`, `statement_scope_unresolved`, `not_found`.

`financial_answers.py` refuses arithmetic on mixed accessions, mixed or non-consolidated scopes,
missing periods, unknown scale and zero denominators; answers now carry an `evidence` block
(requested concept, resolved concept, displayed and economic value, unit, period, accession,
statement, row, printed value, column header, scale, currency, document digest, operands) and four
`verification_stages`, with `final_validity` fixed at `verified_but_not_proven_correct`.

## 4. Development results (not pooled with anything)

Development corpus, 22 answerable questions:

| arm | before | after | false | citation failures | answerable abstentions |
|---|---|---|---|---|---|
| baseline | 17/22 (77.3%) | **20/22 (90.9%)** | 0 | 0 | 2 |
| geometry | 22/22 (100%) | **22/22 (100%)** | 0 | 0 | 0 |

Twelve-issuer cohort, now a **post-holdout development** set (47 answerable, 7 abstention probes):

| metric | baseline first run | baseline now | geometry first run | geometry now |
|---|---|---|---|---|
| fully correct | 23/47 (48.9%) | **36/47 (76.6%)** | 33/47 (70.2%) | **41/47 (87.2%)** |
| answered | 32 | 37 | 38 | 42 |
| false confident answers | **7** | **0** | **4** | **0** |
| citation failures | 2 | 1 | 1 | 1 |
| answerable abstentions (new field) | 15 | 10 | 9 | 5 |
| unjustified abstentions | n/a | 0 | n/a | 3 |
| justified abstentions (probes) | 7/7 | 7/7 | 7/7 | 7/7 |
| unsupported confident answers | 0 | 0 | 0 | 0 |

The single remaining citation failure in each arm is question H-9617-04, where the printed row is
`Total assets(a)` and the gold records `Total assets`. The amount and accession are correct; this
is the known gold imprecision, quantified in the preserved adjudication record
(`fixtures/answer_semantics/holdout_adjudications.json`,
`artifacts/answer_semantics/holdout_adjudication_sensitivity.json`).

## 5. False confident answers remaining

**Zero in both arms** on the development corpus and on the twelve-issuer development set, where
the first run had seven and four. Three wrong numbers became refusals (Oracle revenue, Intel
assets, Disney net income), and three became correct (Oracle and Disney revenue, Intel assets).
This is the objective the phase was for.

## 6. Correct answers lost to stricter verification

Stricter rules cost three previously correct geometry answers and one baseline answer:

- **H-9617-01, H-9617-02 (JPMorgan revenue).** The consolidated income statement is a "managed
  basis" reconciliation with no recognised title; three untitled tables print different
  `Total net revenue` values and none carries enough statement shape to break the tie. Atlas now
  refuses instead of choosing. Closing this needs better untitled-table identification, not a
  looser rule.
- **H-1800-04 (Abbott total assets).** The only tables that print the row are notes; the note
  fallback requires unanimous note values and Abbott's do not agree. Refusal is the safe outcome.
- **H-8230-03 (Caterpillar total assets, baseline).** The geometry path now answers it (81,943);
  the flattened path correctly sees the consolidating schedule as ambiguous.

Everything else that changed direction was a false answer becoming correct or a refusal.

## 7. Coverage and refusal breakdown (twelve-issuer development set)

- Geometry, 47 answerable: 41 correct, 3 unjustified abstentions (2 JPM revenue, 1 Abbott assets),
  2 resolution failures (Disney net income — intended definitional refusal; Abbott assets —
  note-only evidence), 1 citation failure (gold label).
- Baseline, 47 answerable: 36 correct, 10 resolution failures (Caterpillar ×4 — the income
  statement title lives in the table header, which the flattened path only partially reads;
  Disney ×3 — revenue ambiguity and the attributable-income refusal; Abbott ×1; Applied Materials
  ×2 — unit and period gaps), 1 citation failure.
- Abstention probes: 7/7 justified in both arms; 0 unsupported confident answers.

## 8. Performance (measured on this VM, `scripts/answer_semantics_profile.py`)

| stage | measured |
|---|---|
| HTML parse + table geometry, cold, 12 filings | 24.3 s (first run: 30.0 s) |
| same, warm, cached by document digest | **45 ms** |
| statement classification (all table titles) | 10.8 ms |
| baseline flattened-cell extraction | 2.39 s (first run: 2.35 s) |
| geometry resolution, mean per question | 111 ms |
| independent verification, 12 arithmetic cases | 0.43 ms total |
| repeated identical query, mean | 166 ms |
| traced peak memory, 12 documents | 706 MB |

The cold-parse reduction (≈19%) is measured but within session-to-session variance; it is not
claimed as an architectural speed-up. The cache is keyed by SHA-256 of the document bytes, so
evidence can never be reused across different accessions or versions. Peak memory here is
`tracemalloc`, not RSS, and the first run reported RSS; the two are not comparable.

## 9. Tests

- Full backend suite: **952 passed** (20 new hardening tests), 0 failed.
- New adversarial coverage: note-vs-statement identity, plural titles, section headings, column
  groups, scope refusal, note-only unanimity, definitional ambiguity, parenthesised losses,
  substring false friends, footnote/plural canonicalisation, total-vs-component sum rule, mixed
  accession/scope/period arithmetic refusals, and the answer evidence contract.
- Historical audit: `semantics-holdout-archive --check` (22 hash checks at the named commits),
  `semantics-holdout-adjudicate --check`, `semantics-holdout-report --check`.
- Compile check and documentation consistency checks pass.
- Hosted CI run #67 (`45284314381`) passed every job — backend suite, financial audits, frontend,
  migration integrity, research integrity, clean-checkout reproducibility and browser acceptance —
  on `7d34472`. Run #66's single failure was the archive audit's missing git history (above).

## 10. Reproducibility and source integrity

- `artifacts/answer_semantics/holdout_archive_manifest.json` records SHA-256 of the first-run
  artifact, the gold files, the freeze record and the source manifest, and verifies inputs and
  resolution code **at the commits they name** (`git cat-file`), so later source changes cannot
  invalidate the experiment's provenance. It also reports how many live files have drifted.
- `artifacts/answer_semantics/holdout_development_iter{1..5}.json` carry
  `evaluation_label: post_holdout_development`, the code commit, and the digest of the preserved
  first run. They are development measurements and are never presented as a new evaluation.
- The two post-run gold imperfections are in an append-only adjudication file with a recomputable
  sensitivity table (as scored 33/47 vs 23/47; Disney as ambiguous 33/46 vs 23/46; JPM citation
  accepted 34/47 vs 24/47; both 34/46 vs 24/46 — first-run geometry vs baseline).
- Filing bodies remain gitignored; byte digests are re-verified before parsing, and ingestion
  fails closed on mismatch.

## 11. Proposed next independent evaluation

`docs/ANSWER_SEMANTICS_COHORT_V2_PROTOCOL.md` specifies a 16-issuer, 20-accession cohort split
into three separately scored benchmarks — source interpretation, temporal accuracy and analyst
workflows — with amendments, vintage conflicts, consolidated-vs-segment questions, attributable
income, negative earnings, arithmetic with zero denominators, structural absence and definitional
ambiguity. It requires two independent annotators with adjudication, frozen gold before scoring, a
single run, and issuer-cluster uncertainty. Nothing in it has been scored.

## 12. Next recommended milestone

1. **Independent human annotation** for cohort v2 (the single largest threat to any accuracy claim
   here is that all gold so far is single-author).
2. **Untitled-table identification** for table layouts like JPMorgan's managed-basis reconciliation
   — the specific gap that keeps two correct answers as refusals.
3. **A `10-K/A` and vintage cohort** to exercise `as_of` on genuine restatements; the accession
   cohorts cannot.
4. **Per-issuer statement index** so resolution stops scanning all tables of all documents for a
   single-fact question (the remaining warm-latency cost).
5. Replace the placeholder SEC contact identity before any further collection.
