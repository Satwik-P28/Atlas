# Phase 9.6.4 — Vintage Policy

## Implemented

- **Original-as-filed**: among candidates, the filing whose own `period_of_report` equals the
  requested year ranks first, then the earliest filed date.
- **Identical-value collapse**: two vintages reporting the same value for the same concept and
  period are treated as one underlying fact, not a restatement conflict.
- **Same-context conflict detection**: a different value counts as a conflict only when it comes
  from the same statement family and entity scope. A revenue row in a note or segment table is a
  different disclosure, not a restatement. Coca-Cola's 79,934 revenue-labelled note row no longer
  blocks the 2021 comparative.
- **Cutoff enforcement**: availability after the cutoff refuses the binding and the lookup.

## Not implemented

`latest-available-at-cutoff`, `explicit accession` selection and `restatement-compare` are not
exposed as selectable policies. A genuine same-statement disagreement still produces
`vintage_conflict` with both vintages listed rather than a policy-driven choice.

## Duplicate handling

Duplicates are collapsed only after value, concept, period, family and scope agree. Consolidated
and parent-only figures that differ are never merged; the resolver either identifies the correct
context from the statement title or abstains.
