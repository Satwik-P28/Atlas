# Phase 9.6.3 — FEC integration

## Before

`FinancialAnswerEngine` performed its own `Decimal` arithmetic and labelled results
`fec-table-9.6.2`. The FEC compiler and runtime were never executed, so the label was misleading.

## After

Each supported operation now compiles a typed FEC model and runs it with
`atlas.fec.ExecutionEngine` (no cache, no persistence):

| Operation | FEC plan |
| --- | --- |
| lookup | single typed input, no nodes |
| percentage change | `sub → div → mul(×100)` |
| ratio | `div` |
| margin | `div → mul(×100)` |
| total | chained `add` |

Answers carry `fec.compiler_version`, `fec.model_fingerprint`, `fec.run_id`, operator versions,
the compiled plan and the execution trace. `operator_version` is the real compiler version.

## Independent verification

`financial_verification.py` shares no code with FEC: its own parser, `Fraction` arithmetic and
`round_half_up`. The engine refuses with `verification_disagreement` when the two disagree. A
tampered cell (`raw` and `value` inconsistent) is refused, as is a scale mismatch between inputs.

## Remaining boundary

Cell selection (which row/column is the concept) is *not* FEC: it is the resolver described in
`PHASE9_6_3_FINANCIAL_CONCEPT_RESOLUTION.md`. FEC is authoritative for arithmetic only; there is
one arithmetic system, not two.
