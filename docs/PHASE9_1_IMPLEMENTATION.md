# Phase 9.1 — Valuation integrity and financial institutions

Phase 9.1 strengthens the equity research service from *reproducible* to *methodologically
appropriate*. It does not replace the existing architecture: the SEC evidence store, FEC
runtime, Financial X-Ray, Research Applications and terminal navigation are unchanged.

## What changed

| Workstream | Implementation | Evidence |
| --- | --- | --- |
| Master specification | Gate remains blocked: `ATLAS_MASTER_SPEC.md` v1.2.0 was not present in the repository or workspace. `scripts/verify_master_spec.py` checks size 155,419 bytes and SHA-256 `e54c59…a5c9` when supplied. | `docs/MASTER_SPEC_GATE.md` |
| Eligibility contract | Six-state versioned contract `atlas.valuation_eligibility.v2` with identity, business model, supported/prohibited methods, required/available/missing inputs, share basis, normalization, cutoff, assumptions, arithmetic validation, limitations and audit status. | `src/atlas/research/eligibility.py` |
| Residual equity and shares | Negative residual values are preserved, labelled, and separated from a realizable common-stock price. Share denominators are reported with period-end vs weighted-average sensitivity. | `src/atlas/research/institutions.py` |
| Bank laboratory | Residual income for JPMorgan and Goldman Sachs, with book value, reported ROE, cost of equity, payout, terminal growth, ROE/CoE sensitivity and an explicit absence of tangible-book, credit-loss, NIM and Call Report data. | `institutions.build_bank_valuation` |
| Insurance laboratory | Justified earnings with a residual-income cross-check for UnitedHealth, explicitly partial because consolidated statements mix insurance and services; medical loss ratio and reserves are `not_available_in_fixture`, not estimated. | `institutions.build_insurer_valuation` |
| Market prices | Rights-aware CSV/row importer with source, licence, redistribution, adjustment semantics and retrieval time; price-vs-model multiples only when a real price exists. No prices are bundled. | `src/atlas/research/prices.py` |
| Independent audit | Decimal reference implementations for residual income, justified earnings, DCF rejection and negative-value preservation, plus clean-database package replay. | `scripts/audit_phase9_1_models.py` |
| Workspace | Method, contract state and model-appropriate value are exposed by the existing API and shown in the Equity Research page. | `web/src/pages/EquityResearch.tsx` |
| Portability | Institution packages use the `report_bundle` runtime and recompute the model from the packaged snapshot on replay. | `applications/service.py` |
| Benchmarks | Coverage, workspace, bank/insurer valuation, report, package, install and replay timings. | `artifacts/phase9_1_benchmarks.json` |

## Results (20-issuer Phase 9 fixture)

- Valid financial coverage: **16 / 20**.
- Industrial DCF eligibility: **17**, executing: **17**.
- Financial institutions with a valid alternative method: **3** (JPM, GS, UNH), all executing.
- Total executing valuations: **20**; economically supported under the DCF audit: **17**.
- Contracts at `arithmetically_verified`: **13**; contracts blocked at
  `insufficient_source_coverage`: **7**. No contract has been promoted to
  `economically_reviewed` or `independently_benchmarked`, because no external economic
  review or third-party benchmark has been recorded.

## Deliberate limitations

- No master specification was imported; the gate is blocked, not satisfied.
- No FDIC BankFind, Call Report, FFIEC or CMS data is joined. Consolidated SEC facts are
  the only inputs.
- Tangible book value is not computed: goodwill and intangibles are not mapped in this
  fixture. Book value is not silently substituted for tangible book.
- No market prices are bundled. Price multiples, reverse DCF and price-vs-model analysis
  work only after an authorised import.
- JPM/GS/UNH assumptions (cost of equity, payout, growth) are explicit analyst inputs and
  are not economically validated by the model executing.
- macOS and Windows were not exercised; no external usability results exist.
