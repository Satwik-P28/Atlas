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
   when period, scale, currency and coordinates are all established. A cell whose scale cannot be read is
   `unresolved` with the scale recorded as unknown, never as `0`.
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
| Strict verification | `SOURCE_VERIFIED`, checks 34/34 |
| Fingerprint | stable across runs |

The scale defect that produced `34229` (i.e. `34,229 × 10^0`) is fixed, and it was fixed twice over: the
unit banner is now taken from the header row rather than the data row, and an undetectable scale returns
`None` instead of `0`, so the answer abstains rather than stating a number that is off by six orders of
magnitude.

## Adversarial matrix

Sixteen mutations, each re-signed with a recomputed fingerprint so the artifact is internally consistent:

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
