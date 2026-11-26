# ADR 0005 — XBRL normalisation: explicit mappings, no inference

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

XBRL gives every issuer a large, inconsistent vocabulary. Apple's `companyfacts` payload
contains **505 elements**; the same economic quantity may appear under several tags
depending on the issuer, the filing year and the accounting standard. Aggressive
normalisation (fuzzy tag matching, "closest name" heuristics, silent unit conversion)
produces a tidy-looking dataset that is quietly wrong — the exact failure mode the
specification forbids.

## Decision

1. **A hand-curated registry of 32 canonical concepts**, each listing acceptable source
   tags **in priority order**, with an expected unit kind, a period type, a sign policy
   and a note recording semantic caveats.
2. **Resolution is exact and auditable**: highest-priority tag present for the issuer
   wins; no substring matching; no fallback to a semantically different element. If none
   is present the concept is *missing*, which is a legitimate answer.
3. **Issuer overrides** are supported but must name a tag the issuer actually reports; an
   override that is absent does not silently fall back.
4. **The original element is always preserved** (`taxonomy`, `source_concept`), along with
   the raw document. A normalised value is never detached from the element it came from.
5. **Units are typed.** A unit of the wrong kind (e.g. revenue in `shares`) is rejected and
   counted. A different currency is kept as a separate fact and reported in
   `multi_currency_concepts`; values are never converted or summed across currencies.
6. **Sign policy is declared, not assumed.** `capex` is defined as a positive outflow
   magnitude. XBRL's `Payments*` elements are positive, so no arithmetic is applied; a
   negative source value is preserved and flagged `suspect` rather than flipped.
7. **Unmapped elements are counted and listed**, never dropped silently.
8. **Derivations are declared** with rule ids (`atlas.derived.gross_profit.v1`,
   `total_debt.v1`, `free_cash_flow.v1`), recorded inputs and a `derived_calculation`
   basis tier so they can never outrank an observed value.

## Consequences

* Coverage is honest and measurable: 31 of 32 registry concepts are populated for Apple,
  from 31 of 505 available elements; the other 474 are reported as unmapped.
* Users comparing two issuers can always see which element produced each number, so a
  semantic mismatch is visible instead of hidden.
* Adding coverage is a reviewable code change with tests, not a heuristic tuning exercise.
* Cost: coverage grows slowly, and some issuers will have missing concepts where a looser
  mapper would have produced a number. That is the intended trade.

## Known gaps (deliberate)

* **Dimensional facts** (segment/geography/product breakdowns) are not ingested. The
  `companyfacts` API returns consolidated values; segment data requires the XBRL
  instance or `frames`/`companyconcept` handling with dimensions.
* **IFRS taxonomy** (`ifrs-full`) is not mapped; Phase 1 targets US GAAP registrants.
* `dei:EntityCommonStockSharesOutstanding` is a cover-page figure dated at the filing
  date, not a balance-sheet share count; the concept's note states this and downstream
  code must not treat it as a period-end count.
* Restatement detection is inferred from form type (`/A`) plus value change, not from
  parsing the amendment's explanatory text.

## Alternatives considered

* Fuzzy/embedding matching of tag names: rejected — unauditable and prone to silent
  semantic drift.
* Using a third-party XBRL normalisation library: attractive, but the mapping tables are
  the domain contract here; outsourcing them would hide exactly the assumptions the brief
  requires to be explicit. Revisit if a well-maintained, auditable mapping set exists.
* Storing only normalised facts: rejected — destroys the ability to re-derive with a
  corrected mapping, and it is why raw documents are retained.
