# Phase 9.6.4 — Evidence Binding

## Contract

`ResolvedFinancialInput` (frozen, slotted dataclass) carries issuer, concept, document, accession,
table, unit, cell id, row/column, period, currency, scale, value, raw text, table hash, statement
title/family/scope, availability, rights, resolver version and the selection rationale. `bind()`
returns `None` for ambiguous or unresolved resolutions, so an ambiguous fact can never be compiled.

## Execution

`FinancialAnswerEngine.lookup_bound / percentage_change_bound / ratio_bound / margin_bound` consume
bindings and never search the corpus again. The public `lookup(...)` API is unchanged for backward
compatibility.

## Revalidation before execution

`validate_binding(binding, cutoff)` checks: document exists, issuer matches, accession matches,
availability is not after the cutoff, table exists, table hash matches, unit id matches, the bound
period appears in the stored table, the stored cell at (row, column) equals the bound raw text, the
unit hash exists and the bound value equals the parse of the raw text. Any problem yields
`input_unverified` with the problem list in `context.problems`.

## Fault injection

`tests/test_phase9_6_4_binding_and_geometry.py` tampers value/raw, table hash, period, issuer and
table id, and moves the cutoff before availability. All six produce `abstained` /
`input_unverified`; the untampered binding answers 34,229 with the same table and cell ids.
