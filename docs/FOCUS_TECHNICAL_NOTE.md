# FOCUS Technical Note

## The problem

A printed financial figure is not an answer. `34,229` is meaningless until you know which statement it
came from, which period it covers, whether it is in dollars, thousands or millions, whether it was public
at the moment the question is asked, and whether the arithmetic that consumes it was performed on the
same number the filing printed.

Atlas FOCUS is a narrow system with one question: **can a financial answer carry proof of its own inputs
and arithmetic, in a form a third party can re-check without trusting the program that produced it?**

Everything below was measured on real SEC filings. Nothing in this note claims trading performance,
institutional terminal parity, or profitability.

## Method

Six stages, each refusing rather than guessing:

1. **Ingest** — SEC HTML 10-K filings are stored with their exact bytes, a SHA-256 digest, and the
   document's acceptance timestamp (EDGAR `acceptance-datetime`), which becomes its availability time.
2. **Extract** — a flattened HTML row reader separates header rows from data rows and emits a cell only
   with period, scale and coordinates, preserving unknown currency when it cannot be inferred. A
   cell whose required scale cannot be read is `unresolved`, never silently assigned scale `0`.
3. **Resolve** — a concept (`revenue`, `gross_profit`, …) is mapped to exactly one cell, with statement
   family and entity scope checked. Two candidates with different values is a conflict, not a coin flip.
4. **Bind** — the selected evidence is frozen into a `ResolvedFinancialInput` carrying document id,
   table digest, row/column coordinates, label, raw text, period, scale, currency and availability time.
   Later stages cannot re-search by row label, so they cannot drift onto a different row.
5. **Compile and verify** — the Financial-Economic Compiler computes the answer; a second, independent
   `Fraction`-based implementation recomputes it from the same raw strings. Disagreement is an error.
6. **Certify** — the answer is written as canonical JSON (`atlas.research_certificate.v1`) with a
   fingerprint over the body.

## What the certificate binds

The artifact is a claim plus the evidence needed to falsify it: the research question, the normalized
requirement with its operator, the typed result (`value_exact`, `value`, `display_places`,
`economic_amount`), the input bindings (coordinates and raw text), the selected sources (document digest,
table digest, accession, form type, URL, availability time), the issuer identity, the cutoff, and the
fingerprint.

Canonical serialization matters: keys are sorted and the body is hashed, so any semantic edit changes the
fingerprint. A naive tamper therefore fails immediately — which is the uninteresting case. The
interesting case is a tamper that also recomputes the fingerprint, and that is what the adversarial matrix
attacks.

## Two independent verification passes

**Arithmetic.** The verifier does not call the answer engine. It re-parses the certificate's own `raw`
strings, applies the stated operator, and compares with the claimed exact value. It is the third
implementation of the same arithmetic (FEC, `financial_verification`, verifier) and the test suite pins
all three to shared reference vectors.

**Source.** The verifier takes a pinned manifest and the original document bytes, both supplied from
outside the certificate. For each binding it checks the document digest, the table digest, the coordinates,
the row label, the raw string, the period, the scale, the currency, the accession, the form type and the
issuer CIK against the manifest, and checks that the archived bytes still hash to the document digest. It
also re-derives the economic amount from the printed value and the scale.

The four levels follow from those two passes:

| Level | Condition |
|-------|-----------|
| `SOURCE_VERIFIED` | Both passes succeed and every binding is matched to pinned evidence |
| `ARITHMETIC_VERIFIED` | Arithmetic succeeds, no trusted evidence supplied |
| `SOURCE_UNVERIFIED` | Evidence offered but unusable (manifest without bytes; hashes copied from the certificate) |
| `INVALID` | Any fingerprint, structure, arithmetic or source check fails |

### The earlier trust model was circular

The first implementation built `trusted_sources` from the certificate's own `source_table_sha256` and then
compared the certificate's `source_table_sha256` against it. That always passes and proves nothing: the
trusted input was copied from the artifact under test. Verification now refuses that shape. A caller that
still passes `trusted_sources` receives `SOURCE_UNVERIFIED` with reason
`legacy_trusted_sources_insufficient`, rather than a false `valid`.

## The displayed answer is a signed claim too

Binding the inputs is not enough. An attacker who leaves every binding authentic can still relabel
what the answer says it is, because the result metadata sits inside the same signed body and the
fingerprint can be recomputed. Before either verification pass, the verifier therefore reconciles the
displayed result with the inputs:

- `result.period` must be the bound period, or `"<current> vs <prior>"` for a percentage change.
- `result.currency` must be the pinned input currency, including an explicit `null` when the statement
  prints no currency marker.
- `result.unit.scale` must be the binding's exponent for a scaled answer, and `0` for a dimensionless
  one; `result.unit.kind` must be the input currency or the answer type (`percent`, `ratio`).
- `value_exact` is mandatory. A certificate that omits it is asking to be believed on a rounded
  string.
- `economic_amount` is mandatory for scaled results and must follow from the exact value and the
  scale; a dimensionless result must declare `null` instead of inventing a currency amount.
- The normalized requirement, the compiled computation, `financial_concepts`, the reporting scope and
  the result must describe the same operation: the operator appears once, the concept and period match
  the first bound input, and the answer type maps to that operator.
- Every operand must carry the **same recorded scale**. A ratio, margin or percentage change over one
  cell printed in thousands and another printed in millions is refused with
  `binding_scale_consistent`, before any evidence is consulted. The production engine refuses that pair
  too, but the independent verifier derives the refusal from the pins instead of trusting the
  producer's unit check. Dimensionless answers still carry `economic_amount: null` and unit scale `0`;
  the cross-input rule constrains the operands, not the output shape.

These are consistency checks, not semantic proofs. Two fields agreeing with each other does not make
the concept economically correct, and the verifier says so in its own limitations.

The cross-input regression uses an authentic filing that prints its income statement in millions and
its cash-flow statement in thousands. Two real, independently pinned cells (scales `6` and `3`) are
spliced into otherwise genuine ratio, margin and percentage-change certificates; the answer is
recomputed over the printed values and the fingerprint re-signed. All three are refused at
`binding_scale_consistent` with no other failure, while the same-scale originals remain
`SOURCE_VERIFIED`.

## Period assignment is reported, not assumed

The verifier cannot see a header row's meaning from a printed cell alone. It records what the pinned
column header actually says, and reports one of three states: `header_confirmed` (the header prints the
bound period), `not_determined` (the header prints no period), or `unresolved` (the header prints a
different period). `unresolved` does not lower the verification level — the cell, coordinates and
arithmetic are still authenticated — but it is an explicit statement that Atlas is not certifying the
period's meaning.

The Coca-Cola FY2022 case is `unresolved`: the selected column's header prints `2021` while the value
is 2022's `43,004`. The cause is the flattener, which keeps `colspan` groups as ragged rows, so the
short header row is indexed one group off. Independent `colspan`-expanded geometry places `43,004` in
the 2022 group, and SEC XBRL for the same accession reports FY2022 revenues of `43,004,000,000`
against FY2021's `38,655,000,000`. The period is therefore corroborated externally, but it is not
certified from table geometry, and the certificate does not claim otherwise.

## What `SOURCE_VERIFIED` does not prove

This is the part that is easy to overclaim, so it is stated in the checker's own output as a limitation:

- **Not publication time.** The manifest records the availability time Atlas extracted. Byte identity
  proves the bytes match the snapshot; it does not prove when EDGAR first served them.
- **Not financial semantic correctness.** It proves the certificate uses the cell the filing printed at
  those coordinates. Whether that row is the economically right concept for the question is a modelling
  decision, checked separately by resolution and refused on ambiguity.
- **Not manifest authenticity.** The manifest is an unsigned JSON file produced by an explicit command.
  An attacker who can rewrite both the manifest and the snapshots can produce a consistent pair. The
  defence is provenance of the manifest, not cryptography inside it.

For the same reason, strict verification never generates a missing manifest. It reports the absence and
exits `2`; `make focus-manifest` is the only way to create one, and running it is a deliberate act.

## Measured example (3M FY2022 10-K)

| Field | Value |
|-------|-------|
| Accession | `0000066740-23-000014` |
| Row | `Net sales`, FY2022 column |
| Printed | `34,229` |
| Unit banner | `(Millions, except per share amounts)` |
| Scale | `6` |
| Currency | `USD`, from the `$` printed in the amount row |
| Economic amount | `34,229,000,000` |
| Independent arithmetic | agrees |
| Strict verification | `SOURCE_VERIFIED`, 67/67 checks (period assignment `not_determined`: the header prints no period) |
| Fingerprint | a pure function of the body (re-hashing a stored certificate reproduces it) |

The scale defect that produced `34229` (i.e. `34,229 × 10^0`) is fixed, and it was fixed twice over: the
unit banner is now taken from the header row rather than the data row, and an undetectable scale returns
`None` instead of `0`, so the answer abstains rather than stating a number that is off by six orders of
magnitude.

## Adversarial matrix

Twenty-nine mutations, each re-signed with a recomputed fingerprint so the artifact is internally consistent:

| Mutation | Result |
|----------|--------|
| changed result value | `INVALID` |
| changed raw input | `INVALID` |
| changed input **and** result **and** re-signed | `ARITHMETIC_VERIFIED` alone, `INVALID` with evidence |
| changed certificate fingerprint | `INVALID` |
| changed source digest | `INVALID` |
| changed issuer | `INVALID` |
| changed accession | `INVALID` |
| changed period | `INVALID` |
| changed currency | `INVALID` |
| changed scale (and economic amount) | `INVALID` |
| changed availability time | `INVALID` |
| changed row/column coordinates | `INVALID` |
| changed concept | `INVALID` |
| changed table digest | `INVALID` |
| changed operator | `INVALID` |
| changed row label | `INVALID` |
| changed displayed period | `INVALID` |
| changed displayed currency | `INVALID` |
| changed displayed unit scale | `INVALID` |
| changed displayed unit kind | `INVALID` |
| deleted `value_exact` | `INVALID` |
| deleted `economic_amount` | `INVALID` |
| changed economic amount | `INVALID` |
| changed requirement period | `INVALID` |
| changed requirement concept | `INVALID` |
| made requirement and computation operators disagree | `INVALID` |
| changed `financial_concepts` list | `INVALID` |
| changed reporting scope | `INVALID` |
| changed answer type | `INVALID` |

The headline row is the one that matters: **changing the printed value and the result together, then
re-signing, defeats arithmetic alone.** It is caught only because the pinned manifest still records what
the filing said at those coordinates. That is the entire argument for keeping the two verification passes
separate.

## Residual limitations

- No XBRL fact corroboration; the corpus is HTML only.
- Table geometry is inferred from flattened rows, so colspan/rowspan truth is incomplete.
- Currency detection is symbol-based (`$`, `€`, `£`). A filing printing `$` for a non-USD dollar would be
  read as USD.
- The 3M FY2018 consolidated figure (`32,765`) is not resolved by the current resolver. This is a
  capability gap and is recorded as a refusal, not an answer.
- Manifest authenticity depends on how the manifest is stored and distributed, not on the checker.

## Period interpretation boundary

Some Coca-Cola FY2022 selected values retain a flattened table `column_label` of `2021` although their normalized `period` is `2022`. Source verification authenticates the original text and pinned manifest, not the independent correctness of the normalized merged-header interpretation. Geometry-aware reconstruction and XBRL corroboration remain outstanding.
