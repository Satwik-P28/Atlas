# Phase 9.6.4 — Financial Case Studies

Thirteen tasks, executed by `scripts/phase9_6_4_case_studies.py`, artifact
`artifacts/phase9_6_4_case_studies.json` (schema `atlas.phase9_6_4.case_studies.v1`). The 9.6.3
artifact is unchanged.

## Answered (10)

| Issuer | Question | Result | Evidence |
|---|---|---|---|
| Coca-Cola | FY2022 net operating revenues | 43,004 (USD millions) | Consolidated Statements of Income, 2022 column |
| Coca-Cola | FY2022 consolidated net income | 9,571 | same statement, "Consolidated Net Income" |
| Coca-Cola | FY2022 vs FY2021 revenue growth | +11.25% | 43,004 vs 38,655, FEC `percentage_change` |
| Coca-Cola | FY2022 operating margin | 25.37% | 10,909 / 43,004 |
| Coca-Cola | FY2022 total assets / revenue | 2.16 | 92,763 / 43,004 |
| JPMorgan | FY2022 total assets | 3,665,743 | year-end balance sheet, not the average-balance note |
| JPMorgan | FY2022 net income | 37,676 | Consolidated statements of income |
| JPMorgan | FY2022 net income / total assets | 0.01 (0.010277 unrounded) | 37,676 / 3,665,743 — a year-end ratio, **not** ROA |
| 3M | FY2022 net sales | 34,229 | Consolidated Statement of Income, consolidated scope |
| 3M | FY2022 vs FY2021 net sales | −3.18% | 34,229 vs 35,355 |

Each answered packet carries accession, statement title, scope, original row/column, raw value,
period, currency/scale, binding, FEC plan/trace, independent Fraction verification and fingerprint.

## Abstentions (3)

| Issuer | Question | Reason | Classification |
|---|---|---|---|
| JPMorgan | FY2022 gross profit | `not_found` | justified refusal — banks do not report gross profit |
| 3M | FY2018 revenue | `ambiguous` | capability gap — competing historical disclosures |
| 3M | FY2022 revenue at a 2017 cutoff | `not_found` | justified refusal — evidence postdates cutoff |

## Concept distinctions

Coca-Cola's consolidated net income (9,571) is kept distinct from net income attributable to
shareowners (9,542); the resolver reports the row label it bound, and the case text names it.
