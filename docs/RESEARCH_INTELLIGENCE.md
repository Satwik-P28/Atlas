# Research intelligence

How a financial question becomes an answer that can be checked, or a refusal that can be understood.

## The pipeline

```text
question
  -> concept and definition resolution      (closed vocabulary, definitional ambiguity)
  -> period and entity scope resolution      (period labels, headers, consolidated vs segment)
  -> evidence selection                      (statement family, column groups, availability cutoff)
  -> operand binding                         (ResolvedFinancialInput: exact cell identities)
  -> compilation                             (Financial-Economic Compiler)
  -> independent verification                (exact-fraction recomputation)
  -> certificate or typed refusal
```

Every stage is inspectable. A stage that cannot resolve refuses with a code; it does not pass a guess
forward.

There is **no language model in this path**. The resolver is deterministic, closed-vocabulary and
auditable. An LLM may sit in front of it later to translate a request into a constrained plan, and may
sit behind it to explain a verified result — it may not supply a fact, a citation or a calculation.

## Concept resolution

Each concept has a canonical label vocabulary, and a candidate row label must satisfy it in full: every
content word of the concept must appear, plurals fold, footnote markers are stripped. This is stricter
than fuzzy matching on purpose. Observed consequences:

- "Total revenues" does not satisfy `operating_revenue`.
- A segment total does not satisfy a consolidated concept.
- `net_income` and `net_income_attributable_to_parent` are separate concepts; asking for the former when
  the statement only distinguishes the latter produces `definitional_ambiguity`, not a guess.

A total is preferred over its components only when the components sum to it.

## Statement and scope identity

Statement identity comes from statement titles, section headings and table shape, with the rule that a
note can never outrank a statement and a section heading is not a title. Column groups are used when a
table reports several scopes side by side: a group requires an explicit "Consolidated" label, only that
group is selected, and cells report scope `consolidated`.

Untitled tables are admitted only with corroborating structure (companion tables or at least three
statement-shaped rows). Note-only evidence is accepted only when all notes agree and the table has at
least two statement-shaped rows or an explicitly consolidated column group.

## Availability

Facts carry availability semantics, not just dates:

| Stored precision | Meaning | Consequence |
|---|---|---|
| observed instant | an exact public instant is known | usable at any precision |
| `date` | only a filing date is known | pinned to end of that UTC day; intraday ordering unknown |
| `unknown` + model | a derived bound (EDGAR acceptance + modelled lag) | usable as an upper bound at session precision; intraday claims refused; reported as `modeled_bound` |

Historical mode filters by availability, so a fact restated later resolves to what was available then,
and revision lineage stays inspectable.

## Verification and refusal

An accepted answer is compiled and then recomputed by an independent exact-arithmetic verifier; a
disagreement is a failure, not a rounding note. Evidence certificates are verified against pinned
manifests and archived bytes, producing one of four levels (`SOURCE_VERIFIED`, `ARITHMETIC_VERIFIED`,
`SOURCE_UNVERIFIED`, `INVALID`).

Refusal codes you will see, and what each means:

| Code | Meaning |
|---|---|
| `definitional_ambiguity` | two definitions fit; the question does not say which |
| `scope_mismatch` | operands come from incompatible statement scopes |
| `mixed_reporting_scope` | consolidated and segment figures would be combined |
| `availability_unknown` | no evidenced publication time; a date is not invented |
| `document_not_available_at_cutoff` | the document existed later than the cutoff |
| `original_document_not_ingested` | the locator is known but the bytes are not stored |
| `structural_absence` | the statement does not contain the requested concept |

## Measured behaviour

| Corpus | Baseline | Geometry-aware | False confident answers | Citation failures |
|---|---|---|---|---|
| Development corpus (22 questions) | 20/22 | 22/22 | 0 / 0 | 0 / 0 |
| Post-holdout development cohort (47 questions) | 36/47 | 41/47 | 0 / 0 | 1 / 1 |

Remaining geometry failures: two unjustified abstentions on untitled managed-basis reconciliation
tables, one note-only evidence limitation, one definitional ambiguity. They are documented with root
causes in [FINANCIAL_ANSWER_HARDENING.md](FINANCIAL_ANSWER_HARDENING.md) rather than smoothed over.

These numbers are development measurements on frozen corpora. The 47-question cohort was scored once and
is now post-holdout development data; no independent human annotators have validated the next cohort.
The protocol for that evaluation is in
[ANSWER_SEMANTICS_COHORT_V2_PROTOCOL.md](ANSWER_SEMANTICS_COHORT_V2_PROTOCOL.md).

## What an answer is not

`SOURCE_VERIFIED` means: this number came from this cell in this document version, the arithmetic
checks out, and the source bytes match the pinned manifest. It does **not** mean the economic
interpretation is right, the period is the one you wanted, or the comparison you are about to make is
meaningful. Those judgements stay with the analyst, and Atlas keeps the limitations field visible so they
can be made deliberately.

## Reproducing a result

```bash
make semantics-corpus        # build the development corpus
make semantics-eval          # evaluate both resolvers
make semantics-holdout-archive   # verify frozen artifacts at the commits they name
make semantics-postholdout-dev   # record a new post-holdout development iteration
```

Every recorded iteration names its commit and writes an artifact that later runs can be compared against.
Historical results are append-only; corrections are recorded as adjudications with a sensitivity table.
