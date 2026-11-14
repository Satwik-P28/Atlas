# FOCUS technical note

## Problem

A financial figure copied from a filing is not automatically a correct research answer. The same row label appears in consolidated statements, segment notes, MD&A bridges, and parent-only schedules. Filings print scales (“millions”) in captions, neighbouring paragraphs, or inside the table. Comparative columns, currency symbols, and restatements further complicate identity. Historical research also requires knowing whether a document was available at the information cutoff.

## Motivation

Atlas treats source identity and historical availability as first-class inputs to computation. The FOCUS milestone demonstrates one complete chain: real SEC HTML → concept resolution → evidence binding → typed FEC execution → independent recomputation → research certificate → independent verification → adversarial rejection → cutoff refusal.

## Why source identity is difficult

Lexical aliases are candidates, not proof. “Sales” matches segment tables, organic-sales bridges, and percent-of-sales schedules. Atlas scores labels against registered concepts, requires companion rows for primary statements, prefers consolidated income/balance/cash-flow families, and refuses when multiple incompatible values remain.

## Historical-information correctness

Every ingested document carries an availability time (SEC acceptance plus a publication lag). Bindings and lookups that would use evidence after the cutoff abstain with `future_evidence`. The FOCUS demo refuses 3M FY2022 net sales under a 2017 cutoff.

## Typed computation

Bound cells become FEC inputs with financial types (`Money[USD]`, `Scalar`, …). Operators currently demonstrated: lookup, percentage change, ratio, margin, and component total. Scales and currencies must agree across operands; unknown scale abstains.

## Independent verification

`atlas.research.financial_verification` parses raw printed text with its own regex and `Fraction` arithmetic. It shares no code with the FEC runtime. The answer engine refuses when the two disagree. Display rounding is applied only after exact agreement; `value_exact` is retained separately from the displayed `value`.

## Research certificates

Schema `atlas.research_certificate.v1` canonicalizes the research question, cutoff, vintage policy, selected accessions, cell coordinates, printed values, units/scales, computation graph metadata, execution fingerprint, result, assumptions, and limitations. The certificate fingerprint is SHA-256 over canonical JSON excluding the fingerprint field. `atlas verify-certificate` recomputes the fingerprint and arithmetic without calling `FinancialAnswerEngine` or FEC.

## Real filing example

Issuer: 3M Co. Accession: `0000066740-23-000014`. Concept: consolidated net sales, FY2022. Printed value `34,229` with scale exponent `6` (USD millions). Displayed answer `34229.00`; economic amount `34229000000`. Certificate verification status `valid` on the unmodified artifact; a resigned value mutation fails with `result_mismatch`.

## Adversarial tests

`tests/test_focus_certificate.py` mutates issuer, accession, period, currency, scale, value, formula, operator version, source hash, availability time, scope, and coordinates. Unchanged certificates verify; material mutations fail fingerprint and/or arithmetic checks.

## Performance

FOCUS work prioritizes correctness. No new latency claims are made beyond the measured corpus build times recorded in `artifacts/focus_corpus_manifest.json` for the four demo filings.

## Limitations

- No XBRL corroboration.
- HTML geometry remains inferred; colspan/rowspan truth is incomplete.
- Vintage policies beyond original-as-filed + conflict refusal are incomplete.
- FinanceBench population metrics require licensed rows that are not in the repository.

## Future work

Temporal evidence compilation, richer vintage policies, XBRL reconciliation, content-addressed dependency graphs, and expanded evaluation belong to later priorities. They are out of scope for the FOCUS application-ready checkpoint.
