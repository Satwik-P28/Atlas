# Prospective holdout: financial answer semantics (first run)

**Status:** one prospective, preregistered, out-of-sample run. The twelve filings and the 54
questions were frozen and committed **before** either resolver was executed on them; the run below
is the first and only scored run on this cohort, reported unfiltered. It is **not** a population
accuracy estimate, and the development set is **not** pooled with it.

**Cohort:** the twelve FY2022-period-end filings frozen in `fixtures/answer_semantics/holdout_plan.json`
(commitment `073f690d…`), selected from the 40-issuer universe by the committed rule and seed. The
selection was not changed, re-ranked or extended after any output was seen.

| item | value |
|---|---|
| branch | `holdout/answer-semantics-prospective` (from `4c1cf10`, not merged, PR #7 untouched) |
| protocol commit (rule, before any label) | `87cb10d` |
| gold commit | `8da2269` |
| preregistration commit (reissued) | `62d392b` |
| first-run commit | `7d3e509` |
| hosted CI | run [#64](https://github.com/Satwik-P28/Atlas/actions/runs/45270236799) — completed successfully on `5cf7726` |
| gold digest at freeze | `9a3695a9a5dc9494679cefa0ebfd5ef5c10de29a471176700e445081c77deba7` |
| evaluation version | `10.0.2`, protocol `holdout-1.1` |

## 1. What was measured

Two existing resolvers, unchanged, on identical inputs:

- **baseline** — `FinancialAnswerEngine` over cells flattened by the knowledge engine;
- **geometry** — `GeometryResolver` over `table_geometry` parses of the same bytes.

Both arms received the same accession, question text, cutoff and documents. Only the source of the
period, unit and statement identity differs between them. The question is whether a printed value
was read correctly — right amount, right period column, right unit, right filing, right row — and
whether the system refused where no single answer is supported.

## 2. Provenance and ordering (gold before execution)

1. `87cb10d` commits the selection-and-analysis protocol (`holdout_protocol.json`) **before any
   label exists**: slot order, eligibility limits, wording rules, cutoff rule, gold contract,
   metric denominators, paired/cluster analysis and reviewer limitations.
2. `8da2269` commits the authored gold: 54 questions, 59 printed-cell/XBRL pairs, the complete
   ledger and the source manifest with SHA-256 for all twelve documents. Every printed cell was
   located in the archived HTML by a dependency-free dumper and every `printed × 10⁶` value equals
   the same-accession SEC XBRL fact exactly. No resolver had run on these filings.
3. `62d392b` reissues the preregistration. The superseded `6753de7` record is retained inside it
   with its reason: the **first ingestion attempt aborted** because the document rights label was
   not in Atlas's closed redistribution vocabulary. No resolver ran, no question was scored and no
   artifact was written. The label was corrected to the existing `user_responsibility` class and
   the freeze reissued. The cohort, questions and labels were not touched.
4. `7d3e509` records the first scored run. `scripts/answer_semantics_holdout_evaluate.py` refuses to
   run unless the freeze verifies: frozen-input hashes, committed blobs at `HEAD`, resolution-code
   hashes and a clean tracked tree all had to match. It also refuses to overwrite an existing
   first-run artifact.

## 3. Cohort and gold construction

- **Selection audit** (`scripts/answer_semantics_holdout_audit.py`): zero errors. The twelve
  accessions, filing dates, acceptance times and primary documents match SEC submissions metadata;
  the commitment and per-issuer ranks recompute; no development issuer is present; no duplicate
  accession or issuer.
- **Fiscal-calendar caveat (warning, no reselection).** The frozen rule keys on the calendar year of
  the period of report, not the issuer's fiscal-year label. Lowe's period end `2022-01-28` is the
  issuer's **fiscal 2021**; Oracle, FedEx and Applied Materials have May/October year ends. Every
  question therefore states the period end date, and the report never calls the cohort "FY2022".
- **Question construction.** Three substantive slots per filing in a fixed concept order
  (revenue; net income with total assets as fallback; then gross profit / operating income / total
  assets), one arithmetic slot (revenue percentage change, both operands printed in the same table
  and tagged with the same accession), and one abstention probe per filing only where gross profit
  is genuinely absent from both statements and XBRL facts. Result: **54 scored questions**
  (35 lookups, 12 arithmetic, 7 abstention probes) over 12 issuers.
- **Attempted but not scored: 9.** These are recorded with their evidence in
  `fixtures/answer_semantics/holdout_ledger.json`, not silently dropped:
  Caterpillar net income (no `NetIncomeLoss` fact; filer uses `ProfitLoss`); Intel net income
  (8,017 consolidated vs 8,014 attributable — definitional ambiguity); Boeing and Amazon net income
  (parenthesised losses); Boeing's third slot (no printed gross-profit row and a loss-making
  operating result); Disney operating income (segment total only); Abbott operating income
  ("Operating Earnings", a vocabulary gap); Lowe's gross profit (tagged 32,056 but not printed);
  Amazon's gross-profit probe (a segment note prints a gross-profit row, so absence is not
  established).
- **Excluded at scoring: 0.** No question reached `gold_inconsistent`; all 47 answerable labels
  survived the printed/XBRL agreement check.

## 4. Results (first run, unfiltered)

<!-- HOLDOUT-GENERATED:BEGIN -->
### Headline metrics (generated from the artifact)

| metric | baseline | geometry | denominator |
|---|---|---|---|
| answered | 32/47 (68.1%) | 38/47 (80.9%) | answerable |
| combined exact-answer rate | 48.94% | 70.21% | answerable |
| numerical accuracy | 53.19% | 72.34% | answerable |
| citation accuracy | 71.88% | 86.84% | answered |
| source (accession) accuracy | 100.00% | 100.00% | answered |
| period accuracy | 100.00% | 100.00% | answered |
| unit accuracy | 100.00% | 100.00% | answered |
| answer precision | 71.88% | 86.84% | answered |
| period-header confirmation | 12.50% | 100.00% | answered |

| outcome counts | baseline | geometry | denominator |
|---|---|---|---|
| correct | 23 | 33 | answerable |
| false confident answers | 7 | 4 | answered |
| citation failures | 2 | 1 | answered |
| resolution failures | 15 | 4 | answerable |
| unsupported answers on abstention questions | 0 | 0 | abstention |
| justified abstentions | 7 | 7 | abstention |
| runner errors | 0 | 0 | all results |

### Cohort counts (generated)

- attempted: **63**
- scored: **54** (47 answerable, 7 abstention)
- recorded but not scored: **9**
- excluded at scoring time (gold_inconsistent): **0**
- issuers: **12**, accessions: **12**

### Issuer-level results (generated)

| issuer | questions | answerable | abstention | baseline correct | geometry correct | baseline false | geometry false |
|---|---|---|---|---|---|---|---|
| Abbott Laboratories | 5 | 4 | 1 | 0 | 3 | 1 | 0 |
| Applied Materials Inc | 4 | 4 | 0 | 4 | 4 | 0 | 0 |
| Boeing Co | 3 | 3 | 0 | 0 | 0 | 1 | 0 |
| Caterpillar Inc | 5 | 4 | 1 | 1 | 1 | 0 | 0 |
| JPMorgan Chase & Co | 5 | 4 | 1 | 3 | 3 | 0 | 0 |
| Intel Corp | 4 | 4 | 0 | 4 | 3 | 0 | 1 |
| Lowe's Companies Inc | 4 | 4 | 0 | 0 | 4 | 0 | 0 |
| Amazon.com Inc | 4 | 4 | 0 | 4 | 4 | 0 | 0 |
| FedEx Corp | 5 | 4 | 1 | 2 | 4 | 1 | 0 |
| United Parcel Service Inc | 5 | 4 | 1 | 2 | 4 | 1 | 0 |
| Oracle Corp | 5 | 4 | 1 | 2 | 2 | 2 | 2 |
| Walt Disney Co | 5 | 4 | 1 | 1 | 1 | 1 | 1 |

### Paired comparison and cluster uncertainty (generated)

- paired questions: **54** (all scored questions, including 7 abstention questions)
- both correct: 28; geometry only: 12; baseline only: 2; neither: 12
- paired difference (geometry − baseline, denominator 54): **+0.1852**
- exact sign test on discordant pairs: p = 0.0129
- issuer-cluster bootstrap 95% interval (2000 resamples, seed 20261123): **[+0.0185, +0.3750]**

### Timing and cost (generated)

| measurement | baseline | geometry |
|---|---|---|
| warm mean per question | 67.628 ms | 46.836 ms |
| warm median / p95 | 14.769 / 198.863 ms | 28.324 / 123.401 ms |
| cold preprocessing | 9089.823 ms | 36783.261 ms |
| amortised per question | 235.958 ms | 728.007 ms |

Ingestion of the twelve filings (shared by both arms): 6744.491 ms. Whole run: 45820.946 ms. Process peak RSS: 752.2 MB (from 28.6 MB before ingestion; both arms share the process, so this is not a per-arm figure).

### Refusal reasons (generated)

- baseline: `concept_resolution` ×22
- geometry: `geometry` ×16

### Every failure, with evidence (generated)

| question | arm | status | gold | response | evidence |
|---|---|---|---|---|---|
| H-8230-01 | baseline | `resolution_failure` | 59,427 | — | Caterpillar prints the same sales row in four column groups (consolidated, ME&T, Financial Products, adjustments); both arms see several amounts for 2022. |
| H-8230-01 | geometry | `unjustified_abstention` | 59,427 | — | Caterpillar prints the same sales row in four column groups (consolidated, ME&T, Financial Products, adjustments); both arms see several amounts for 2022. |
| H-8230-02 | baseline | `resolution_failure` | 59,427 | — | Same consolidating layout; the prior-year operand is equally ambiguous. |
| H-8230-02 | geometry | `unjustified_abstention` | 59,427 | — | Same consolidating layout; the prior-year operand is equally ambiguous. |
| H-8230-03 | geometry | `unjustified_abstention` | 81,943 | — | 'Total assets' repeats across the same four column groups. |
| H-8230-04 | baseline | `resolution_failure` | 7,904 | — | 'Operating profit' repeats across the consolidating column groups. |
| H-9617-04 | baseline | `citation_failure` | 3,665,743 | 3665743000000 | Printed row label is 'Total assets(a)' with a footnote marker; both arms returned 3,665,743 with a faithful citation, but the gold label list held only 'Total assets'. Gold transcription, not an answer error. |
| H-9617-04 | geometry | `citation_failure` | 3,665,743 | 3665743000000 | Printed row label is 'Total assets(a)' with a footnote marker; both arms returned 3,665,743 with a faithful citation, but the gold label list held only 'Total assets'. Gold transcription, not an answer error. |
| H-0863-03 | geometry | `false_answer` | 182,103 | 2932000000 | Geometry bound 'Total assets' 2,932 from a segment/geography table instead of the 182,103 consolidated total; the table was not recognised as a segment note. |
| H-1439-01 | baseline | `false_answer` | 42,440 | 8047000000 | Baseline read 'Sales and marketing (1)' 8,047 as revenue (alias 'sales'); geometry read 'Differences in timing of revenue recognition' 623 from a deferred-revenue rollforward whose column header also names 2022. |
| H-1439-01 | geometry | `false_answer` | 42,440 | 623000000 | Baseline read 'Sales and marketing (1)' 8,047 as revenue (alias 'sales'); geometry read 'Differences in timing of revenue recognition' 623 from a deferred-revenue rollforward whose column header also names 2022. |
| H-1439-02 | baseline | `false_answer` | 42,440 | 4.75 | Both arms inherited the wrong revenue operand (8,047/7,682 and 623/547), so the percentage change is computed correctly from the wrong rows. |
| H-1439-02 | geometry | `false_answer` | 42,440 | 13.89 | Both arms inherited the wrong revenue operand (8,047/7,682 and 623/547), so the percentage change is computed correctly from the wrong rows. |
| H-0727-01 | baseline | `false_answer` | 100,338 | -1651000000 | Baseline read 'Net (purchases), sales and maturities of marketable securities' (1,651) from the 2021 column as revenue (alias 'sales' inside a cash-flow row). |
| H-0727-02 | baseline | `resolution_failure` | 100,338 | — | Prior-year revenue resolved ambiguously, so the change question cannot run. |
| H-4489-01 | baseline | `resolution_failure` | 82,722 | — | Baseline is ambiguous across Disney's revenue tables; geometry finds no candidate row at all, i.e. the consolidated 'Total revenues' row is missed, not misread. |
| H-4489-01 | geometry | `resolution_failure` | 82,722 | — | Baseline is ambiguous across Disney's revenue tables; geometry finds no candidate row at all, i.e. the consolidated 'Total revenues' row is missed, not misread. |
| H-4489-02 | baseline | `resolution_failure` | 82,722 | — | Same missing row for both period ends. |
| H-4489-02 | geometry | `resolution_failure` | 82,722 | — | Same missing row for both period ends. |
| H-4489-03 | baseline | `false_answer` | 3,145 | 3505000000 | Both arms returned the 3,505 consolidated net income; gold records the 3,145 NetIncomeLoss (attributable to Disney). Contested label: see §7. |
| H-4489-03 | geometry | `false_answer` | 3,145 | 3505000000 | Both arms returned the 3,505 consolidated net income; gold records the 3,145 NetIncomeLoss (attributable to Disney). Contested label: see §7. |
| H-2927-01 | baseline | `resolution_failure` | 66,608 | — | Boeing's '(Dollars in millions, except per share data)' banner is not in the geometry scale vocabulary, so the matching rows carry no usable unit. |
| H-2927-01 | geometry | `resolution_failure` | 66,608 | — | Boeing's '(Dollars in millions, except per share data)' banner is not in the geometry scale vocabulary, so the matching rows carry no usable unit. |
| H-2927-02 | baseline | `resolution_failure` | 66,608 | — | Same unit gap for both revenue columns. |
| H-2927-02 | geometry | `resolution_failure` | 66,608 | — | Same unit gap for both revenue columns. |
| H-2927-03 | baseline | `false_answer` | 137,100 | 1954000000 | Baseline read a subsidiary balance sheet ('Total assets $1,954'); geometry refuses because nested tables produce conflicting 'Total assets' rows. |
| H-2927-03 | geometry | `unjustified_abstention` | 137,100 | — | Baseline read a subsidiary balance sheet ('Total assets $1,954'); geometry refuses because nested tables produce conflicting 'Total assets' rows. |
| H-1800-01 | baseline | `resolution_failure` | 43,653 | — | Abbott's segment net-sales tables repeat the row label; baseline is ambiguous. |
| H-1800-02 | baseline | `resolution_failure` | 43,653 | — | Same ambiguity for both period ends. |
| H-1800-03 | baseline | `resolution_failure` | 6,933 | — | Abbott's 'Net Earnings' appears in several tables with different amounts; baseline is ambiguous and geometry refuses. |
| H-1800-03 | geometry | `unjustified_abstention` | 6,933 | — | Abbott's 'Net Earnings' appears in several tables with different amounts; baseline is ambiguous and geometry refuses. |
| H-1800-04 | baseline | `false_answer` | 74,438 | 25224000000 | Baseline read 'Total current assets' 25,224 as total assets. |
| H-8911-02 | baseline | `false_answer` | 93,512 | 0.00 | Baseline resolved both operands to the 2022 revenue 93,512 (column labels '2021' and '2021 (1)'), producing a 0.00% change. |
| H-8911-03 | baseline | `citation_failure` | 3,826 | 3826000000 | Value 3,826 is right; the citation names the '2021 (1)' column for a 2022 figure, so the period attribution fails. |
| H-0667-01 | baseline | `resolution_failure` | 96,250 | — | Lowe's prints net sales in its earnings statement and again in percentage and segment tables; baseline is ambiguous. |
| H-0667-02 | baseline | `resolution_failure` | 96,250 | — | Same ambiguity for both period ends. |
| H-0667-03 | baseline | `resolution_failure` | 8,442 | — | 'Net earnings' is repeated in the earnings statement, the cash-flow statement and the equity statement. |
| H-0667-04 | baseline | `resolution_failure` | 12,093 | — | 'Operating income' row is not located by the baseline at all. |

_Generated from `artifacts/answer_semantics/holdout_evaluation.json` (sha256 06556b83ae5a6f68…), first run at 2026-11-23T21:17:04Z against gold freeze commit `62d392b`._
<!-- HOLDOUT-GENERATED:END -->

## 5. Reading the result

Over the same 47 answerable questions, geometry answered 38 and the baseline 32; geometry's
combined exact-answer rate is **70.2%** against **48.9%**, and it produced **4** false confident
answers against **7**. Every answer either arm did give cited the correct accession (source accuracy
100%), no answer was unsupported on an abstention question, and all seven abstention probes were
refused by both arms for the right reason.

The paired analysis counts all 54 scored questions (abstention questions count as correct when
refused): both arms correct on 28, geometry only on 12, baseline only on 2, neither on 12. The
paired difference of +18.5 points has an issuer-cluster bootstrap interval of roughly +2 to +37
points; the exact sign test on the 14 discordant pairs gives p ≈ 0.013. With twelve clusters and
unequal question counts per issuer, the interval is coarse — it is evidence that the improvement is
not a coincidence of one filing, not a precise effect size.

Two differences from the development set are worth stating plainly and are **not** pooled with it:
geometry was 22/22 there and 33/47 here, and baseline 17/22 here-to-there. The holdout is harder:
consolidating column groups, segment tables that repeat consolidated labels, a filer whose scale
banner is not in the geometry vocabulary, and a bank. The drop is the expected consequence of
scoring a cohort that was not used to design the resolver.

## 6. Failure analysis

**Baseline (flattened cells).** Most baseline failures are vocabulary or scope errors in the
flattened representation, not arithmetic:

- *Alias overreach into unrelated rows.* Oracle revenue was read from `Sales and marketing` (8,047),
  UPS revenue from `Net (purchases), sales and maturities of marketable securities` (−1,651), and
  Abbott total assets from `Total current assets` (25,224). The word "sales" or "total … assets"
  is enough to win the label score once table structure is gone.
- *Subsidiary and segment scope.* Boeing total assets came from a Boeing Capital balance sheet
  (`$1,954`) rather than the consolidated 137,100.
- *Column misassignment.* FedEx's percentage-change question resolved both operands to the 2022
  figure (column labels `2021` and `2021 (1)`), producing a 0.00% change; its net-income answer was
  right but attributed to the wrong column.
- *Repeated labels.* Caterpillar, Disney, Boeing, Abbott and Lowe's refused as `ambiguous` because
  the same label appears in several tables or column groups with different amounts. Refusing is
  defensible; it is still a resolution failure on questions the statement answers.

**Geometry.**

- *Correct refusals on genuinely ambiguous layouts.* Caterpillar's consolidating statement prints
  consolidated, ME&T, Financial Products and adjustment column groups side by side; the same row
  label therefore has several 2022 cells with different values, and geometry refuses instead of
  choosing. Abbott's net income and Boeing's assets are the same shape (nested tables).
- *Correct refusals for a missing unit.* Boeing's statement banner reads
  "(Dollars in millions, except per share data)", which the geometry scale vocabulary does not
  recognise, so the matching revenue rows are unusable (`unit_unresolved`).
- *Two false positives.* Intel total assets was bound to 2,932 from a segment/geography table
  (consolidated 182,103); Oracle revenue was bound to `Differences in timing of revenue
  recognition` (623) from a deferred-revenue rollforward whose column header also names 2022.
- *One miss.* Disney's consolidated `Total revenues` row produced no candidate at all
  (`no_candidate_row`) for either period, i.e. a statement table was excluded or its family
  misread. The same question is ambiguous for the baseline, so neither arm answered it.

**Citations.** Geometry's period-header confirmation is 100% against the baseline's 12.5%: every
geometry citation names the column it used. The single geometry citation failure is a gold-label
transcription issue, discussed next.

## 7. Gold imperfections found after the run (labels unchanged)

Two of the 47 answerable labels are contested on post-run review. They were **not** edited; the
sensitivity below quantifies their effect, and both are reported as authoring limitations.

1. **H-4489-03 (Disney net income).** Gold records 3,145 (`NetIncomeLoss`, printed as
   "Net income attributable to Disney"); both arms returned 3,505, the consolidated
   "Net income (loss)" row. By the eligibility rule applied to Intel's two-row case, this slot
   should have fallen through as a definitional ambiguity. The label stands; the question is
   contested.
2. **H-9617-04 (JPMorgan total assets).** The printed row label is `Total assets(a)` with a footnote
   marker. Both arms returned 3,665,743 with a citation naming that row; gold listed only
   `Total assets`, so the citation was scored as a failure. The value and the accession were right.

Sensitivity (post-hoc arithmetic, not the headline):

| variant | geometry exact | baseline exact | geometry false | baseline false |
|---|---|---|---|---|
| as scored | 33/47 = 70.2% | 23/47 = 48.9% | 4 | 7 |
| Disney label treated as ambiguous | 33/46 = 71.7% | 23/46 = 50.0% | 3 | 6 |
| JPM citation accepted as faithful | 34/47 = 72.3% | 24/47 = 51.1% | 4 | 7 |
| both adjustments | 34/46 = 73.9% | 24/46 = 52.2% | 3 | 6 |

Neither adjustment changes the direction or the practical size of the difference.

## 8. Timing and cost

Geometry pays a large one-off parse cost (about 30 s for twelve filings, against 2.3 s for flattened
cells; both arms also share 6.7 s of ingestion) and is cheaper per question once warm (46.8 ms mean
against 67.6 ms; median 28.3 ms against 14.8 ms, so the distributions differ in shape). Amortised
over 54 questions geometry costs about 0.73 s per question against 0.24 s. Process peak RSS during
the run was about 750 MB for both arms together; this is not a per-arm measurement. All timings are
environment-specific and are not part of the correctness claim.

## 9. Integrity and reproducibility

- **Bytes.** The source manifest records SHA-256 and byte counts for all twelve filings, archived
  under `var/` (gitignored; no filing body is committed). Ingestion re-hashes every file against
  the manifest and `load_documents` re-hashes again before parsing; any mismatch raises
  `SourceIntegrityError` and the run stops. All twelve digests matched on every execution.
- **Freeze.** `scripts/answer_semantics_holdout_freeze.py --check` recomputes the hashes of the
  protocol, plan, universe, corpus, questions, facts, ledger, source manifest and authoring script,
  compares each against its committed blob at `HEAD`, recomputes the resolution-code hashes and
  requires a clean tracked tree. It passed immediately before the scored run, and
  `tests/test_answer_semantics_holdout.py` fails if any of it drifts.
- **Replay.** `scripts/answer_semantics_holdout_replay.py` re-parsed the archived bytes and re-ran
  both arms: 108/108 result classifications identical, all non-latency metrics identical; latency
  differs by machine and is reported separately. Artifact:
  `artifacts/answer_semantics/holdout_replay.json`.
- **Report.** The tables in §4 are generated from the artifact; `--check` fails if they drift.

## 10. Limitations

- **Single-author gold.** Each cell is corroborated by two independent authorities (printed text and
  same-accession XBRL), but there is no second human annotator. This is not independent human
  annotation and must not be described as such. Two labels are contested (§7).
- **Small, clustered cohort.** Twelve issuers, 47 answerable questions, unequal counts per issuer
  (Boeing contributes two answerable questions). The cluster bootstrap is coarse and treats issuers,
  not questions, as exchangeable.
- **Concept coverage.** Net income could not be scored for four issuers (tag gap, definitional
  ambiguity, losses); operating cash flow, cash, liabilities and share counts were not probed. The
  cohort does not support a claim about those concepts.
- **Abstention class.** All seven probes are structural absence. No conflicting-vintage case exists
  in an accession-scoped cohort, so the `as_of` mode remains untested prospectively.
- **Cohort period.** All twelve filings have a 2022 calendar-year period end. Nothing here generalises
  to other years or to amended filings (`10-K/A`), which were excluded by the frozen rule.
- **Fair-access identity.** Collection used the repository's documented placeholder contact
  (`AtlasQuant/0.1 you@example.com`). SEC requires a working contact; a real one must be configured
  before any further collection. Filing bytes are archived locally only.
- **Timing.** Cold and warm numbers depend on this VM and are not comparable across machines.
- **One aborted attempt.** The first ingestion aborted on a rights-label validation error before any
  resolver ran; the superseded preregistration and its reason are preserved in the reissued freeze.

## 11. Does this support independent confirmation?

For **this frozen cohort**, yes: on questions authored without either resolver's output, geometry
answered more of the answerable questions correctly (33/47 against 23/47), produced fewer wrong
numbers (4 against 7), and never cited the wrong filing. The paired difference is positive with a
cluster interval that excludes zero on the low end, while remaining too wide for a precise effect
size. That is prospective confirmation of the *direction* on twelve untouched issuers.

It is **not** a production accuracy claim, not an estimate for the population of filers, and not a
template for other years or concepts. The development result (22/22 geometry, 17/22 baseline) stays
development-only evidence and is not averaged with this cohort.

## 12. Recommended next milestone

1. **Independent human annotation** of a new cohort by a second reviewer, with disagreement
   recorded rather than reconciled — the single largest threat to the claim.
2. **A vintage/as-of cohort** to test the `as_of` mode on genuinely conflicting restatements, which
   this accession-scoped cohort cannot exercise.
3. **Fix the two exposed geometry gaps as new work, evaluated on a fresh untouched cohort**: the
   scale-banner vocabulary (Boeing) and consolidating/segment column-group scope (Caterpillar,
   Intel, Oracle). Adding them here would turn this cohort into a development set.
4. **Widen concept coverage** (cash flow, liabilities, share counts) and include `10-K/A` filings.
5. Replace the placeholder SEC contact with a real one before any further collection, and keep
   filing bodies out of version control.

## 13. Reproduction

```bash
# network, once: archive the frozen twelve filings and their XBRL facts (never parsed here)
ATLAS_SEC_USER_AGENT='…' make semantics-holdout-corpus

# offline: audit the selection, verify the preregistration, replay or (on a fresh clone) score
make semantics-holdout-audit
make semantics-holdout-freeze
make semantics-holdout-replay
make semantics-holdout-run        # refuses if a first-run artifact already exists

make semantics-holdout-report     # report tables match the artifact
```

PR #7 remains a draft on `focus/answer-semantics`; `main`, PR #1 and the certificate core are
untouched by this branch.
