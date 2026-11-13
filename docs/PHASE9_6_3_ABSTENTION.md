# Phase 9.6.3 — Abstention on real evidence

## Structured policy

A number is asserted only when: one concept resolves, one verified cell carries it, the cell's
period matches, units/scales agree, the table is the consolidated statement, the vintage is
unambiguous, FEC executes, and the independent `Fraction` verifier agrees.

## Constructed hard negatives (real corpus)

For twelve issuers: wrong fiscal year (2017), undisclosed metric (`ebitda`), and a cutoff before
the filing existed.

* negatives: 36
* correctly abstained: 33
* false assertions: 3 → rate 0.0833
* precision: 0.9167; recall on answerable positives: 1.0 in the evaluation sample

The three false assertions come from wrong-year lookups where another filing in the issuer's
history happens to contain a cell with that year column. The engine answers with **that** vintage,
which is exactly why every answer states the supplying document and why a vintaged-evidence
contract is required.

## Case-study abstention

All 12 real case studies abstained, each with a machine-readable reason. No LLM confidence score is
used anywhere in the decision.

## Limitation

The negatives are deterministic constructions, not a human-reviewed holdout. No untouched mixed
holdout was established; this is stated in the artifact rather than optimised away.
