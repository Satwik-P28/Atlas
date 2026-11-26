# Financial answer semantics: development re-analysis, prospective cohort pre-registered

**Status:** research demonstration on a **development set**. The 24-question result below is a
re-analysis after integrity corrections; it is **not** an independent confirmation and not a
production accuracy estimate. §12 defines the untouched cohort that would provide one, and §11
lists what changed in this revision and why.

**Base:** `789d360` (PR #1 head) via `focus/answer-semantics`. **Scope:** source interpretation
only. The certificate verifier, its certificates, the evidence kernel and `main` are unchanged.

## 1. The question

Atlas answers a financial question by locating a printed cell in a filing and binding it to a
concept, a period and a unit. The FOCUS milestone hardened the answer *after* the cell was chosen.
It did not ask whether the chosen cell was the right one.

Two cases motivated this milestone:

- **3M FY2018 net sales.** The resolver returned `ambiguous: conflicting_row_values` because a
  segment banner row, `Net Sales (Millions)`, is flattened as a data row and competes with the
  consolidated `Net sales` of 32,765.
- **Coca-Cola FY2022 revenue.** The value (43,004) was right but the cited column was labelled
  `2021`: a header cell spanning three physical columns was flattened, so header and data indices
  no longer aligned.

Both are table-geometry defects. This milestone asks how much answer error they cause on filings
that were not used to design the fix — and, just as importantly, whether the *evaluation* can be
trusted.

## 2. What is measured

Each question is scored once per resolver. A response is `answered` or `abstained` (with a
reason). Correctness is reported at three levels that are easy to conflate:

| level | definition |
| --- | --- |
| **numerical** | amount, fiscal period and printed unit all equal gold |
| **citation** | the cited accession, row label and raw text are the reviewed ones |
| **fully source-correct** | numerical **and** citation **and** the cited accession is the filing the gold fact comes from |

The headline `exact_answer_rate` is the **combined** criterion. A correct amount attributed to the
wrong filing, row or raw text is a `citation_failure`, not a hit: the answer cannot be checked by a
reader against the evidence it names.

| class | meaning |
| --- | --- |
| `correct` | fully source-correct |
| `citation_failure` | numerically right, evidence wrong (counted as incorrect) |
| `false_answer` | numerically wrong on an answerable question |
| `resolution_failure` | abstained although the filing prints the answer |
| `evidence_missing` | abstained because the filing does not print the answer |
| `justified_abstention` | abstained on a conflict or a structurally absent concept |
| `unsupported_confident_answer` | answered where the evidence supports no unique value |

`period_header_confirmed` is reported separately from period accuracy: the Coca-Cola defect
asserts period 2022 while citing a header that says 2021, so period accuracy passes and header
confirmation fails. `period_header_confirmed` measures whether the cited header **affirms** the
period; it does not prove the other headers print a different period.

## 3. Corpus

Twelve 10-K documents from eleven issuers, chosen for layout and reporting diversity rather than
for difficulty: retail (January year end), technology (52/53-week September year), industrial,
energy, consumer staples, grocery (53-week year), distributor, and a fiscal label that disagrees
with the calendar label. Two are the motivating regressions; the other ten were not consulted
while writing the geometry code.

The table is **generated** from `fixtures/answer_semantics/corpus.json`, checked against the
manifest and the question set, and verified in CI by
`tests/test_answer_semantics_integrity.py::test_report_corpus_table_is_generated_from_the_canonical_corpus`.
It is not maintained by hand: an earlier revision of this report carried eight hand-typed
accessions that did not match the evaluated filings.

<!-- corpus-table:begin -->
| key | issuer | FY | accession | layout property exercised |
| --- | --- | --- | --- | --- |
| WMT-FY2023 | Walmart Inc. | 2023 | 0000104169-23-000020 | January fiscal year; `Net sales` and `Total revenues` both printed |
| AAPL-FY2023 | Apple Inc. | 2023 | 0000320193-23-000106 | "except number of shares" unit line; 52/53-week year |
| MSFT-FY2019 | Microsoft Corp | 2019 | 0001564590-19-027952 | three-year comparison; `Revenue` total with product and service subtotals |
| PEP-FY2019 | PepsiCo Inc. | 2019 | 0000077476-20-000015 | 52/53-week year; `Total revenue` |
| IBM-FY2018 | International Business Machines Corp | 2018 | 0001047469-19-000712 | `Consolidated Statement of Earnings`; `Total revenue` vs `Sales` |
| IBM-FY2017 | International Business Machines Corp | 2017 | 0001047469-18-001117 | prior-year restated gross profit (Item 8 exhibit 13) |
| SFM-FY2022 | Sprouts Farmers Market, Inc. | 2022 | 0000950170-22-001976 | column headers say "Fiscal 2021" over 2020/2021 numbers |
| UNFI-FY2022 | United Natural Foods Inc | 2022 | 0001020859-22-000054 | August fiscal year; `Net sales` |
| DE-FY2018 | Deere & Co | 2018 | 0001047469-18-007694 | decimal printed values (`2,368.4`); segment tables |
| CVX-FY2021 | Chevron Corp | 2021 | 0000093410-22-000019 | no gross-profit line at all |
| KO-FY2022 | Coca-Cola Co | 2022 | 0000021344-23-000011 | merged (`colspan`) header groups - regression case |
| MMM-FY2018 | 3M Co | 2018 | 0001558370-19-000470 | in-table segment banner - regression case |
<!-- corpus-table:end -->

`fixtures/answer_semantics/corpus.json` records each accession, its primary-document URL, the
filing's acceptance time, its sha256 and the printed figures used for review. The archived bytes
themselves live under `var/` and are never committed.

## 4. Ground truth

Gold is independent of both resolvers:

1. A **SEC XBRL fact from the same accession** (`companyfacts`), restricted to the concepts under
   test and to that filing.
2. The **printed cell**, located by hand with its geometry (row label, column, scale, period) and
   recorded with its raw text.
3. The two must agree after applying the printed scale, within half a printed unit. If they do not,
   the question is classed `gold_inconsistent` and excluded from every denominator — never
   repaired in either direction. None occurred in the final set.
4. Where the evidence cannot support one number the question is not forced:
   - `conflicting_evidence` — IBM FY2017 gross profit is 36,227 in the FY2018 filing and 36,943 in
     the FY2019 filing, both for the same period end. The correct behaviour is to report the
     disagreement.
   - `structurally_unanswerable` — Chevron prints no gross-profit subtotal, so abstention is the
     only truthful answer.

**Independence caveat.** When a tag has several dimensional facts for the same period, gold
selection uses the reviewed printed amount to choose among them. That is a reconciled annotation,
not a fully independent one: the printed cell and the XBRL fact corroborate each other's value.
It happened for **5 of 28** fact selectors (AS-06, AS-07, AS-08, AS-20 twice), and the harness
refuses to choose when no unique candidate matches. Dimension/entity disambiguation without the
answer value is future work.

Twenty-four questions: twenty-two `xbrl_verified`, one `conflicting_evidence`, one
`structurally_unanswerable`. Eight assert a non-latest period, so a resolver that always takes the
first numeric column fails rather than passes by accident. Every question is **accession-scoped**
to the filing it names, except AS-23, which is explicitly an **as-of** question that must search
several IBM filings up to its cutoff.

## 5. Two resolvers

**Baseline** is the shipped path, unchanged: the knowledge engine flattens tables into
`rows_json`, `FinancialAnswerEngine.cells()` verifies cells, `ConceptResolver` scores row labels
against the shared alias table, applies segment/document penalties, and refuses on a value tie. An
accession-scoped question is refused if the chosen cell comes from another accession.

**Geometry** re-parses the archived bytes into a `colspan`/`rowspan`-expanded grid, keeps header
blocks and unit banners, and resolves against that grid. Constraints keep the comparison
attributable: the same alias table and scoring function are reused, so a difference cannot come
from a bigger lexicon; the geometry path adds only cell geometry, statement vocabulary
(`Consolidated Statement of Earnings`), issuer scoping by CIK, accession pinning, and two
tie-breaks (max-score tier, then a printed `Total` preference).

**Multi-input safety.** Before any margin or percentage change, both operands must share the
printed scale, currency, accession, document digest, reporting scope and compatible periods.
Otherwise the resolver refuses with `unit_integrity:<reason>` instead of normalising silently —
the same fail-closed contract the certificate verifier enforces for certificates.

## 6. Results (development set)

Twelve filings, 24 questions, one run each; artifact `artifacts/answer_semantics/evaluation.json`,
version `10.0.2`.

| metric | baseline | geometry |
| --- | --- | --- |
| answerable questions | 22 | 22 |
| answered | 17 | **22** |
| fully source-correct | 17 | **22** |
| numerical accuracy | 0.7727 | **1.0000** |
| citation accuracy (of answered) | 1.0000 | 1.0000 |
| source accuracy (cited filing) | 1.0000 | 1.0000 |
| **exact-answer rate (combined)** | 0.7727 | **1.0000** |
| citation failures | 0 | 0 |
| period header confirmed | **0.0588** (1/17) | **1.0000** (22/22) |
| false answers | 0 | 0 |
| unsupported confident answers | 0 | 0 |
| resolution failures | 5 | 0 |
| justified abstentions | 2/2 | 2/2 |
| median / p95 latency | 72.1 / 349.8 ms | 30.3 / 64.2 ms |
| one-time build (cold start) | 2.31 s | 21.04 s |

Both resolvers produce **zero** false answers and **zero** unsupported answers, so the gain is not
a lower error rate among answered questions: it is five fewer refusals plus period attribution the
cited evidence actually supports (1 of 17 versus 22 of 22). The baseline's answer for Coca-Cola is
43,004 with `column_label = "2021"`; that is the defect class, and it is why header confirmation is
reported.

The baseline breakdown behind `0.0588` is not "all sixteen are wrong" and not "they merely lack a
label": of its 17 answered questions, **1** cites a header printing the asserted year, **6** cite a
header printing a *different* year (AS-09, AS-10, AS-11, AS-16, AS-17, AS-21), and **10** leave at
least one cited header with no year printed. Both failure modes make a citation unverifiable by a
reader; only the first six assert a wrong year outright.

Cost matters for interpretation. Geometry pays ~21 s once per document set (dominated by 6.9 MB
IBM exhibits); after that, resolution is cheaper per question (30.3 ms vs 72.1 ms). A user asking
one question pays the cold start; a user asking many amortises it.

## 7. Error analysis

The five baseline resolution failures and what geometry changed:

1. **AAPL FY2023 revenue** — `ambiguous: weak_alias_match`. The unit banner reads `(In millions,
   except number of shares which are reflected in thousands and per share amounts)`. The flattened
   parser sees two units, marks every consolidated-statement cell `unresolved: conflicting_units`,
   and the only surviving `Total net sales` cell is a product table, which the segment penalty
   scores at −5.0. Geometry reads the amount unit from the main clause before `except`.
2. **AAPL FY2023 total assets** — same cause plus a header defect: the surviving balance-sheet cell
   carries `column_label = "September 24, 2022"` for a **2023** column, i.e. the label is shifted
   by one physical column.
3. **AAPL FY2023 gross margin** — inherits (1); geometry computes 44.1% from two confirmed cells of
   one filing.
4. **IBM FY2018 revenue** — `Sales` (26,641, a component) and `Total revenue` (79,591) match at
   equal strength. Geometry takes the max-score tier and prefers the single printed `Total`.
5. **MMM FY2018 net sales** — the segment banner row again. Geometry emits no numeric cell for a
   row whose non-label cells are region names, so 32,765 is the only candidate.

Two further defects were found by building the corpus and are recorded because they were *not*
harmless:

- **Cross-issuer leakage.** Early geometry runs answered Deere's `total_assets` from another
  issuer's document. CIK scoping was added; the current harness also *checks* the cited accession
  against the question, so a leak is a `citation_failure` even if scoping regresses.
- **A crash in the baseline.** `Decimal(str(Fraction))` raises `InvalidOperation` for decimal
  printed values such as Deere's `2,368.4`. The fix converts through numerator/denominator; it is
  the only change to existing resolver code.

## 8. Negative results and limits of the claim

- **The baseline does not lie.** Every question it answered, it answered correctly. A corpus built
  only from questions the baseline answers would show no improvement at all.
- **The alias table is still a ceiling.** Walmart prints `Total revenues` (611,289); the vocabulary
  carries `total revenue`, so the plural total loses to the exact `Net sales` match (605,881). The
  question is recorded in the ledger and left unscored rather than fixed after the fact.
- **Reporting scope is unresolved.** Deere prints operating cash flow as 1,820.3 (consolidated) and
  3,278.9 (equipment operations); neither table carries a recognised statement title, so both
  candidates are equally strong and the resolver refuses. Refusing is right, but it is not a
  resolution. Recorded and left unscored.
- **Fiscal-label fallback is conservative.** Sprouts prints `Fiscal 2021` over columns that are
  fiscal 2022 and 2021 by the filing's own date; geometry succeeds because the statement prints the
  full date, and refuses where only a relative label is printed.
- **Selected questions, single reviewer.** The author chose the questions and one person reviewed
  the printed cells. The XBRL cross-check removes transcription error, not selection bias.
- **Small sample.** 24 questions, 11 issuers, US GAAP 10-Ks in English HTML only. No IFRS,
  XBRL-only filings, scanned exhibits, or foreign private issuers.

An exact ledger of every attempted question — including the two dropped and one replaced before
scoring — is `fixtures/answer_semantics/ledger.json`: 27 attempted, 24 scored, 2 dropped
(Walmart alias, Deere scope), 1 replaced (Deere net income tag ambiguity), 0 excluded at scoring.

## 9. Reproduction

```bash
make install
ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com' make semantics-corpus   # network, once
make semantics-eval                                                          # offline scoring
python -m pytest tests/test_answer_semantics.py tests/test_answer_semantics_integrity.py -q
python scripts/answer_semantics_report_table.py --check                      # report matches corpus
```

Integrity properties the harness enforces, each with a regression:

- **Source bytes.** `load_documents` recomputes SHA-256 of every archived file and refuses missing,
  altered, duplicated or undeclared filings before parsing. A digest passed as metadata is never
  trusted over the bytes (`test_load_documents_fails_closed_on_altered_snapshot` and friends).
- **Accession scope.** A pinned question resolves only against that accession; the resolver refuses
  rather than falling back, and the scorer rejects a citation from any other filing
  (`test_accession_pin_reads_only_the_named_filing`,
  `test_a_correct_amount_from_the_wrong_filing_is_not_correct`).
- **Operand compatibility.** Forged mixed-scale, mixed-currency, mixed-source, segment-scope and
  period-mismatch operands are refused before arithmetic
  (`test_margin_refuses_operands_from_different_unit_scales`,
  `test_percentage_change_refuses_operands_from_different_filings`).
- **Report provenance.** The published corpus table is generated from the fixture data and compared
  against it in CI.

## 10. Data rights

SEC EDGAR filings are **free to access and reuse** under the SEC's published web-access guidance.
That is a reuse policy, not a statement of authorship: EDGAR filings are prepared and filed by
issuers, not by federal employees, so 17 U.S.C. §105 (works of the US government) does not apply
and this project asserts **no** public-domain status for filing content.

Accordingly: the repository stores only accessions, URLs, digests, acceptance times, short printed
figures and derived measurements — no filing bodies. `var/` (archived bytes and the corpus
database) is gitignored, snapshots are retained uncommitted pending source-rights review, and no
third-party licensed corpus (for example FinanceBench) is used or copied. The `rights` field
recorded on parsed documents is `sec_edgar_public_access`, describing access, not ownership.

## 11. Corrections in this revision (review of PR #7)

| review finding | correction | regression |
| --- | --- | --- |
| Multi-input operations could mix scales/currencies/sources | `operand_integrity()` refuses before arithmetic; `unit_integrity:<reason>` reasons | forged operand tests (§9) |
| Accession-scoped questions resolved across filings | `GeometryResolver.resolve(accession=…)`, baseline post-bind check, explicit `scope: accession \| as_of` | pin tests, AS-23 as-of test |
| Citation correctness was measured but not scored | `correct` requires numerical **and** citation **and** source match; new `citation_failure` status; numerical/citation/combined reported separately | wrong-row and wrong-filing scoring tests |
| Archived bytes were not rehashed | `load_documents` verifies SHA-256 and corpus agreement, fails closed; `from_html` hashes what it parses | missing/altered/undeclared snapshot tests |
| Eight accession IDs wrong in the report | table generated from the corpus; `--check` in CI | report-table regression |
| Dropped questions undisclosed | `fixtures/answer_semantics/ledger.json` with evidence | ledger regression |
| Rights conflated access with federal authorship | §10 rewritten; corpus `rights` text corrected | — |
| 22/22 read as a holdout result | labelled development set throughout; §12 defines the untouched cohort | — |

The measured result did **not** change when the integrity checks were added (17/22 and 22/22). The
checks were not tuned to preserve it; they are prior conditions on what counts as an answer.

## 12. Untouched cohort (pre-registration)

Independent confirmation requires filings and questions the resolver has never been run on.
`fixtures/answer_semantics/holdout_plan.json` fixes, before any answer is produced:

- a committed universe of candidate issuers and a deterministic selection rule (`sha256(seed ||
  cik)` ordering) that excludes every development issuer;
- the selected accessions, resolved from EDGAR submissions for a stated fiscal year, with filing
  dates and URLs;
- the protocol: questions authored only from printed geometry plus XBRL company facts, no resolver
  output inspected during authoring, gold frozen and hashed before the first scoring run, one
  scoring run reported whatever it shows.

Until that run exists, every number in §6 is a **development-set** measurement. A future run may
be reported as independent confirmation only if it follows the frozen protocol; if the protocol is
changed after seeing resolver output, the cohort is no longer a holdout and must be labelled a
development set.
