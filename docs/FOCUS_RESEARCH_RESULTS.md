# FOCUS Research Results

All figures below were produced by `make focus-demo` on the integrated candidate, from the archived
corpus described in `artifacts/focus_corpus_manifest.json`. The report is
`artifacts/focus_demo/report.json`; it is regenerated on every run and its `status` field is `passed`
with `failures: []`.

## Corpus

| Filing | Accession |
|--------|-----------|
| Coca-Cola FY2022 10-K | `0000021344-23-000011` |
| JPMorgan FY2022 10-K | `0000019617-23-000231` |
| 3M FY2022 10-K | `0000066740-23-000014` |
| 3M FY2018 10-K | `0001558370-19-000470` |

Four filings, three documents in the pinned manifest (the FY2018 and FY2022 3M filings are distinct
documents; one filing contributes no answered cell), nine pinned cells, ten answered cases.

## Thirteen cases: 10 answered, 3 refused

| Case | Issuer | Question | Answer | Level |
|------|--------|----------|--------|-------|
| FOCUS-01 | Coca-Cola | Net operating revenues FY2022 | `43,004.00` (→ 43,004,000,000 USD) | `SOURCE_VERIFIED` |
| FOCUS-02 | Coca-Cola | Gross profit FY2022 | `9,571.00` | `SOURCE_VERIFIED` |
| FOCUS-03 | Coca-Cola | Revenue change FY2022 vs FY2021 | `11.25` % | `SOURCE_VERIFIED` |
| FOCUS-04 | Coca-Cola | Gross margin FY2022 | `25.37` % | `SOURCE_VERIFIED` |
| FOCUS-05 | Coca-Cola | Operating expense ratio | `2.1571` | `SOURCE_VERIFIED` |
| FOCUS-06 | JPMorgan | Total net revenue FY2022 | `3,665,743.00` (→ 3,665,743,000,000 USD) | `SOURCE_VERIFIED` |
| FOCUS-07 | JPMorgan | Net income FY2022 | `37,676.00` | `SOURCE_VERIFIED` |
| FOCUS-08 | JPMorgan | Net income / revenue | `0.0103` | `SOURCE_VERIFIED` |
| FOCUS-10 | 3M | Net sales FY2022 | `34,229.00` (→ 34,229,000,000 USD) | `SOURCE_VERIFIED` |
| FOCUS-11 | 3M | Net sales change FY2022 vs FY2021 | `-3.18` % | `SOURCE_VERIFIED` |
| FOCUS-09 | JPMorgan | Gross profit | refused | justified unanswerability |
| FOCUS-12 | 3M | Net sales FY2018 | refused | resolver capability gap |
| FOCUS-13 | 3M | Net sales at a 2017 cutoff | refused | historical information refusal |

Rates and ratios carry `economic_amount: null` on purpose: a percentage or a ratio has no currency
amount, and inventing one would be a scaling error dressed as precision.

## The three refusals are not equivalent

- **FOCUS-09 (justified unanswerability).** JPMorgan's income statement as filed does not present a
  `gross profit` line that the resolver can bind. Refusing is the correct behaviour and is a success of
  the policy, not of the answer.
- **FOCUS-12 (capability gap).** The 3M FY2018 filing *does* print consolidated net sales of `32,765`.
  Atlas fails to resolve it. This is a defect in the resolver, recorded as a refusal with the observed
  value attached so it cannot be mistaken for a successfully answered question.
- **FOCUS-13 (historical information refusal).** The question is asked at a cutoff before the filing was
  public, so the evidence is genuinely unavailable at that time. The refusal is temporally correct.

Counting these three as "questions answered" would inflate the result by thirty percent and hide the
one real gap among two policy successes.

## Certificate matrix

Ten answered cases produce ten certificates. Every one verifies at `SOURCE_VERIFIED` when checked with
the pinned manifest and archived bytes; the flagship certificate passes 34/34 individual checks.

| Property | Value |
|----------|-------|
| Schema | `atlas.research_certificate.v1` |
| Flagship | 3M FY2022 net sales |
| Printed | `34,229` |
| Scale | `6` |
| Currency | `USD` (from the `$` printed in the amount row) |
| Economic amount | `34,229,000,000` |
| Arithmetic pass | agrees with FEC and with `financial_verification` |
| Source pass | document digest, table digest, coordinates, label, raw, period, scale, currency, accession, form type, issuer CIK all match |
| Fingerprint | stable across runs |

The scale correction is the substantive repair: the unit banner `(Millions, except per share amounts)`
belongs to the header row, not the data row. Reading it from the data row yielded scale `0` and an
economic amount of `34,229` — a number six orders of magnitude wrong that still looked precise.

## Sixteen-mutation matrix

Every mutation is re-signed, so the fingerprint check passes and the artifact is internally consistent.
Sixteen of sixteen are refused.

| Mutation | Verification result |
|----------|--------------------|
| changed result value | `INVALID` (arithmetic) |
| changed raw input | `INVALID` (arithmetic/source) |
| changed input + result + fingerprint | `ARITHMETIC_VERIFIED` without evidence, `INVALID` with it |
| changed certificate fingerprint | `INVALID` |
| changed source document digest | `INVALID` |
| changed issuer | `INVALID` |
| changed accession | `INVALID` |
| changed period | `INVALID` |
| changed currency | `INVALID` |
| changed scale + economic amount | `INVALID` |
| changed availability time | `INVALID` |
| changed row/column coordinates | `INVALID` |
| changed concept | `INVALID` |
| changed table digest | `INVALID` |
| changed operator | `INVALID` |
| changed row label | `INVALID` |

The third row is the load-bearing one. A forger who changes both the printed value and the result and
then recomputes the fingerprint produces a certificate that is *arithmetically self-consistent*. Only the
independent comparison against the pinned manifest and archived bytes catches it. This is why the
demonstration keeps the two passes separate and refuses to call arithmetic-only verification "verified".

## Regression and environment checks

| Check | Result |
|-------|--------|
| Backend suite | 812 passed (158.10 s) |
| Frontend unit tests | 50 passed, 4 files |
| TypeScript project build | clean |
| Production web build | built in 3.33 s |
| Certificate/mutation tests | 40 passed |
| `scripts/reproduce_phase9_2.py` | `exit: 0`, package sha256 `3bbaca54…`, value per share `295.464…`, no differences |
| `scripts/verify_clean_install.py` | `status: pass`, `reproduced: true`, value per share `101.2157…` |
| Distributable fixtures | 10,580 rows, project-authored synthetic market fixture |
| Database/migration tests | passed; no `*.egg-info` tracked |
| Restricted-fixture scan | no licensed vendor fixtures present |

## Threats to validity

- **Single-source provenance.** A pinned manifest plus archived bytes proves consistency with a
  snapshot. It cannot prove that snapshot was what EDGAR served at a given time, and the manifest is
  unsigned. Verifying manifest provenance is an operational problem, not one this code solves.
- **Four filings, three issuers.** Ten answers is a demonstration that the mechanism works, not a
  measurement of accuracy across a corpus.
- **HTML-only.** No XBRL facts, so period and scale come from rendered text rather than structured data.
- **Geometry inference.** Flattened rows lose colspan/rowspan, so merged cells are the main source of
  unresolved cells.
- **Symbol-based currency.** `$` is read as USD. A filing using `$` for a non-USD dollar would be wrong.
- **One known gap.** 3M FY2018 remains unresolved (`32,765` printed).
- **Browser acceptance** could not be executed in the integration environment (Chromium requires system
  libraries that need root). The frontend unit suite, typecheck and production build pass; the
  Playwright journeys are left for CI, which installs browser dependencies.
