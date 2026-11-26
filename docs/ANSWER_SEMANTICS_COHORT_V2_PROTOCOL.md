# Answer-semantics cohort v2: protocol (designed, not scored)

**Status:** design only. No question has been authored, no filing fetched for this cohort, and no
resolver has been run. This document exists so that the next evaluation is specified *before* the
first score, and so that the three claims it measures are not conflated.

The first prospective cohort (twelve FY2022 10-Ks, 54 questions) is finished and its labels are
frozen. Its issuers have since been used for development (§ the hardening report), so they can
never serve as an untouched sample again. Cohort v2 must be a disjoint issuer set, and it must
test three different things that the first cohort could not separate.

## 1. Three benchmarks, scored separately

| id | claim | question shape | what a failure means |
|---|---|---|---|
| **A. Source interpretation** | Atlas finds and cites the right printed cells | "What did the FY2023 statement print for X, in accession Y?" | retrieval or semantic selection failed, given the filing |
| **B. Temporal accuracy** | Atlas answers only from evidence available at the cutoff | "As of 2024-06-30, what is the latest reported X?" where a later filing exists | look-ahead bias, vintage handling, or restatement confusion |
| **C. Analyst workflow** | Atlas answers a realistic research question from statements | "How did gross margin change year over year, and what drove it?" (multi-operand, cited) | composition, arithmetic or explanation failure |

A and B are diagnostic and single-fact. C is composite and scored on the answer *and* the
evidence, never on prose fluency. Results for A, B and C are reported in separate tables with
separate denominators; they are never pooled into one "accuracy".

## 2. Cohort composition

Target **16 issuers / 20 accessions**, disjoint from every issuer used in development
(`fixtures/answer_semantics/corpus.json` and the twelve holdout CIKs).

Minimum composition, by declared strata (filled by a committed selection script and seed, not by
hand):

- **Fiscal years:** at least three distinct periods of report, including one pre-2022 year.
- **Amendments:** at least two `10-K/A` accessions, at least one that restates a previously filed
  number used by a question.
- **Vintage conflicts:** at least two issuers with two overlapping filings where the same concept
  and period differ between them (a genuine restatement or a changed segment presentation).
- **Reporting scope:** at least three questions whose answer must come from a segment table, and
  three where a segment value is the *wrong* answer (consolidated is required).
- **Attribution:** at least three issuers that print both consolidated net income and income
  attributable to the parent, with different values.
- **Losses:** at least three questions whose gold value is negative (parenthesised or minus).
- **Arithmetic:** at least six multi-period or ratio questions, including one zero or unavailable
  denominator that must be refused.
- **Absence:** at least four structurally unanswerable probes (concept not printed anywhere in the
  accession) and two definitional-ambiguity probes (two legitimate rows, no unique answer).
- **Banks and insurers:** at least two financial-sector issuers, because their companion-row
  vocabulary differs from industrial filers.

## 3. Gold authoring and independent review

1. **Two independent annotators**, neither of whom has seen any resolver output on the cohort.
   Each records, per question: accessions, periods, printed label and raw cell, unit, scale,
   statement identity, scope, the expected value (by lookup or arithmetic), and an eligibility
   note. Annotator B does not see A's values.
2. **Adjudication** of every disagreement by a third pass that records both readings and a
   decision with a reason. Disagreements are preserved in an append-only adjudication file, not
   silently reconciled.
3. **Machine cross-check only as corroboration:** each printed cell must equal its same-accession
   XBRL fact within one printed unit. A mismatch marks the item `gold_inconsistent` and excludes
   it from every denominator; it is never repaired by preferring one authority.
4. **Negative values are eligible.** Parenthesised losses and minus-signed amounts are
   economically meaningful and must be labelled, not excluded. A parser that cannot represent
   them is a defect to fix, not a reason to drop the question.
5. **Definitional ambiguity is an answer class.** If a statement prints two legitimate rows for
   the requested concept (consolidated vs attributable, two revenue definitions), the correct gold
   is "ambiguous, must clarify", and a confident single answer is scored as an error.

## 4. Freezing and the one-run rule

- Commit order: `protocol` → `gold` (questions + facts + ledger + adjudications) → `freeze`
  (SHA-256 of every gold file, the corpus manifest and the resolution code) → `run`.
- The run script refuses to execute unless every frozen hash matches its committed blob and the
  tracked tree is clean; it refuses to overwrite an existing first-run artifact.
- One scored run. After it, labels are frozen forever. Any defect found later is reported with a
  sensitivity analysis; it does not change the headline.
- Cohort v2 gets its own paths (`fixtures/answer_semantics/v2_*`, `artifacts/answer_semantics/v2_*`,
  `var/answer_semantics/v2/`). Nothing is shared with the development or v1 cohorts.

## 5. Metrics and analysis

Per benchmark (A, B, C) and per arm (baseline, geometry):

- answered / answerable, exact-answer rate, numerical accuracy, citation accuracy, source
  accuracy, answer precision;
- **answerable abstentions** and **unjustified abstentions** (reported separately from
  `resolution_failures`, so an abstention can never be hidden by reading one field);
- false confident answers, split into wrong amount, wrong period, wrong unit, wrong filing;
- for B: look-ahead violations (any citation unavailable at the cutoff), vintage conflicts
  correctly refused, and stale answers;
- for C: operand integrity failures, arithmetic refusals, and citation completeness per operand;
- latency: cold preprocessing, warm per-question, amortised per question, peak memory.

Uncertainty: issuer-cluster bootstrap (10,000 resamples) for every rate difference, plus an exact
paired test on discordant questions. With 16 issuers the interval will still be wide; the report
must say so rather than quote a point estimate as if it were precise.

## 6. Explicit non-goals

- No tuning between freeze and run.
- No question removed because it is hard.
- No pooling with development or v1 results.
- No claim of independent confirmation from data any resolver has already seen.
- No use of v1 issuers, even as "extra" questions.

## 7. Preconditions before authoring starts

1. A real SEC contact identity is configured (the v1 collection used the repository's documented
   placeholder, which is a fair-access limitation).
2. The statement-scope and concept vocabularies in `statement_scope.py` and `financial_concepts.py`
   are treated as frozen for the cohort: if they change after authoring begins, the cohort is a
   development set.
3. Two annotators are available and have not read this repository's failure analyses.
