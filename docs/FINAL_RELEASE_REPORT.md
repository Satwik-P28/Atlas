# Final Release Report — FOCUS Semantic-Integrity Correction

## Candidate

| Field | Value |
|-------|-------|
| Pull request | #1 `cursor/focus-priority0-827f` → `main` |
| Cross-input scale commit | `4beef9b908018e28597545bf0f0054ebd5f9b5ba` |
| Semantic-integrity commit | `eedff7cf9d048e5e629578659e68a7efd96eccaf` |
| Prior head (reviewed) | `46a138d99de3c11ba46f82c943e08f9fa902da3d` |
| This report | documentation-only commit on top of `4beef9b` |
| Base | `main` at `644448d4fbb3414c9c8045f5a86030ef34bfe2df` (unchanged) |
| `focus/application-ready` | preserved at `bf5f6ade…` as a reference branch |

## Hosted CI

| Run | Commit | Result |
|-----|--------|--------|
| [45103084258](https://github.com/Satwik-P28/Atlas/actions/runs/45103084258) | `4beef9b` | **success**, six jobs |
| [45097933862](https://github.com/Satwik-P28/Atlas/actions/runs/45097933862) | `eedff7c` | success, six jobs |
| 43678481311 | `8808f4c` | success, six jobs |

Job conclusions for `45103084258`, all `success`: Backend tests and audits · Frontend test, typecheck
and build · Database migration integrity · Research, market-evidence and rights integrity ·
Clean-checkout reproducibility (committed fixtures only) · Browser acceptance (Playwright, Ubuntu
runner), including Scenario A (JPM research from distributable evidence) and Scenario B (synthetic ATLS
market data, provenance and pin replay) plus artifact upload.

Local checks at `4beef9b`: **868** backend tests passed; **80** certificate and mutation tests;
frontend **50** tests, typecheck and production build (the frontend is unchanged); `make focus-demo`
**66/66** contract checks with **29/29** mutations refused.

## What this correction changed

The review found that verification compared every source binding against the pinned manifest but never
reconciled the **displayed** result with those bindings. An attacker could keep authentic evidence and
relabel the answer — change `result.period` or `result.currency`, change `unit.scale`, or delete
`value_exact` / `economic_amount` — re-sign, and still reach `SOURCE_VERIFIED`.

1. **Result metadata must agree with the inputs.** `result.period` is the bound period (or
   `"<current> vs <prior>"` for a percentage change); `result.currency` is the pinned input currency;
   `result.unit.scale` is the binding exponent, or `0` for a dimensionless answer; `result.unit.kind` is
   the input currency or the answer type.
2. **Internal consistency across requirement, computation, concept, scope and result.** The operator
   must appear identically in the requirement and the computation, the concept and period must match the
   first bound input, `financial_concepts` must equal the bound concepts, the answer type must map to the
   operator, and the reporting scope must agree across the certificate, the issuer identity and every
   binding. The report states explicitly that agreement between these fields is consistency, not proof
   that the concept is economically correct.
3. **Mandatory fields.** `value_exact` is required and compared with the recomputed exact value.
   `economic_amount` is required for scaled results and must follow from the exact value and the scale;
   a dimensionless result must declare `null`. A null `currency` remains legitimate when the statement
   prints no currency marker.
4. **Adversarial matrix extended from 16 to 29.** Thirteen new mutations touch only the displayed result
   or the normalized requirement, each re-signed with a recomputed fingerprint. All 29 are refused, and
   the thirteen new ones fail on internal consistency before any evidence is consulted.
5. **Period assignment reported, not assumed.** The verifier records `header_confirmed`,
   `not_determined` or `unresolved` per certificate from the pinned column header.

## Cross-input scale correction (second review round)

The follow-up review found a narrower hole in the *independent* verifier. It collected the input scales
but demanded a single value only in the branch that also required a scaled `economic_amount`. For
`ratio`, `margin` and `percentage_change` the branch was skipped, so a certificate could divide a cell
printed in thousands by one printed in millions, recompute that ratio over the printed numbers, re-sign,
and still reach `SOURCE_VERIFIED`. The production `FinancialAnswerEngine` refuses the same pair, but the
verifier must not rely on producer behaviour.

- **One shared operand scale, checked before any operator branch.** `binding_scale_consistent` requires
exactly one recorded exponent across all bindings. It runs before arithmetic, so it covers dimensionless
answers and `total` alike and no longer depends on whether an economic amount is present.
- **Dimensionless semantics are unchanged.** Same-scale ratio, margin and percentage-change
certificates still verify with `economic_amount: null`, unit scale `0` and `unit.kind` `ratio`/`percent`.
A null currency remains legitimate.
- **Regression with authentic cells at two scales.** The fixture filing prints its income statement
`(In millions)` (scale `6`) and its cash-flow statement `(In thousands)` (scale `3`) in one accession.
Two real, independently pinned cells are spliced into otherwise genuine ratio, margin and
percentage-change certificates; the answer is recomputed over the printed values and the fingerprint
re-signed. All three are refused at `binding_scale_consistent` with no other failure, while the
same-scale originals remain `SOURCE_VERIFIED`. Against the pre-fix verifier these three forgeries reach
`SOURCE_VERIFIED` with an empty reason list, so the regression is load-bearing.
- **Producer agreement is demonstrated, not assumed.** A separate test asserts that the engine refuses
the same mixed-scale operand pairs with `unit_mismatch`.

Period semantics were deliberately not touched: the four Coca-Cola assignments remain `unresolved`
because no new table-geometry or XBRL evidence was gathered in this round.

## Demo results at this candidate

Thirteen cases: **10 answered, 3 refused** (justified unanswerability, resolver capability gap for 3M
FY2018, historical information refusal). All ten certificates `SOURCE_VERIFIED`; flagship 3M FY2022
net sales printed `34,229`, scale `6`, economic amount `34,229,000,000` USD, all 67 checks passing.

| Case | Period assignment |
|------|-------------------|
| FOCUS-02 | `header_confirmed` |
| FOCUS-01, 03, 04, 05 | `unresolved` (Coca-Cola header prints `2021` at the selected column) |
| FOCUS-06, 07, 08, 10, 11 | `not_determined` (selected header prints no period) |

## Coca-Cola period audit

The FY2022 net-sales cell binds column 2 with `column_label = '2021'` while the value `43,004` is 2022's.
The cause is the flattener: the header row is stored with four cells
(`Year Ended December 31, | 2022 | 2021 | 2020`) and the data row with ten, because the filing groups
columns with `colspan` and empty cells are kept inconsistently. Indexing the short header at the data
column lands one group off.

Two independent checks place the value in FY2022: re-parsing the same bytes with `colspan` expansion
(three three-column year groups), and SEC XBRL for the same accession `0000021344-23-000011`
(FY2022 `43,004,000,000`; FY2021 `38,655,000,000`; FY2020 `33,014,000,000`).

The certificate therefore reports the period as **unresolved**. The cell, its coordinates, the document
digest and the arithmetic remain source-verified; the *meaning* of the period is not certified by Atlas.
Repairing header alignment in the extractor would let these cases certify the period from geometry, but
that is a parser change beyond this correction and was not made.

## Remaining limitations

1. **Period semantics are unresolved for four Coca-Cola cases.** External XBRL corroboration is recorded
   in the docs, not asserted by the certificate.
2. **The trust anchor is unsigned.** `artifacts/focus_source_manifest.json` proves consistency with that
   snapshot only — not publication time, not financial semantic correctness, not manifest authenticity.
3. **`main` still contains historical licensed FinanceBench material** (`d8ae4f1`). A normal merge does
   not remove it, no history rewrite is authorized, and promotion therefore requires an explicit
   owner-authorized resolution.
4. **Artifacts are timestamped.** `issued_at` and `run_id` are inside the fingerprint body, so a fresh
   demo run produces identical results but new fingerprints.
5. **Semantic consistency is not economic correctness.** Nothing in this correction claims that the
   concept chosen for a question is the right one; that remains a modelling judgement, refused on
   ambiguity but not proven.

## Status

- `FOCUS_READY`: the candidate passes every required check, locally and in hosted CI for `4beef9b`.
- `MAIN_PROMOTED_AND_VERIFIED`: **not attempted**. Promotion stays blocked until the historical
  licensed-content issue has an explicitly authorized resolution.
