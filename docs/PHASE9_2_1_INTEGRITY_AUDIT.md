# Phase 9.2.1 integrity audit

**Scope:** correction of verified financial and evidentiary defects in the Phase 9.2
market-data importer and bank model. This is not a new product phase.

**Baseline commit:** `5955f8239229bd252419ff1f71329afccc323acd` on
`freebuff/41a4fd2abe41a6515dc8d5bb`.

## 1. Market imports destroyed other providers' observations

**Defect.** `import_price_series()` deleted every `bar` row for the selected security, MIC,
interval and timestamp before inserting the new observation. The delete was not scoped to
the incoming source. Importing provider B removed provider A's observation for the same
session.

**Root cause.** Market data was treated as one mutable canonical series rather than an
append-only set of source observations. The importer also reused the literal source id
`user-market-data` and mutated that source's name, licence and redistribution fields.

**Affected code.** `src/atlas/research/prices.py`; `bar`, `market_price_series`,
`ingestion_run` and `source` storage contracts.

**Consequences.** Evidence destruction, unreproducible research, silent source switching,
and retroactive rights changes. A restricted import could appear to inherit a later,
more permissive licence.

**Corrected invariant.**

- Every observation is keyed by security, source identity, adjustment semantics, session
  and revision. Provider observations coexist.
- Source identity is a stable hash of provider name, dataset, licence, redistribution,
  authorization basis and collection method.
- Existing source rights are immutable. A different licence creates a different source; it
  cannot rewrite or authorize earlier observations.
- Identical replay is idempotent. A changed value appends `revision_seq` and
  `supersedes_bar`; the superseded row is retained.
- Each batch has a content hash and an `ingestion_run` record. A replay updates the same
  run receipt rather than failing on a duplicate id.
- The batch is all-or-nothing: every row is parsed and validated before any write.
- Only `unadjusted` observations may be imported. Adjusted series are derived views.
- Canonical selection is explicit and versioned as
  `atlas.market_price.selection.v1`: requested source, otherwise latest session, latest
  ingestion, source id. The result includes conflicts and every alternative.
- Research accepts `market_source_id`; packages record the source/session selection while
  continuing to exclude restricted prices.

**Migration impact.** No schema migration was required: the existing immutable `bar`
revision key already supported the invariant. Existing databases are preserved. Source ids
created by the old importer remain readable but are not reused for new imports.

**Tests.** `tests/test_phase9_2_1_market_integrity.py` covers:

- A/B same-session provider conflict with both originals retained;
- identical replay idempotency and changed-value revision;
- reopening the original source after a newer import;
- explicit source change;
- malformed batch rollback;
- licence/rights isolation and non-promotion;
- ambiguous ticker, explicit security/MIC selection and venue mismatch;
- historical ticker reuse;
- rejection of adjusted series.

## 2. Ticker-only identity and hard-coded exchange

**Defect.** The importer took the first security matching a ticker and wrote `XNYS`
regardless of the actual listing.

**Corrected invariant.** The importer resolves exactly one active assignment as of the
import's `as_of` date. Multiple plausible securities reject as ambiguous and require an
explicit `security_id` and `mic`. The listing must be active, the currency must match the
security, and the selected MIC is stored on the bar and series. A later ticker reassignment
does not move earlier observations.

## 3. GAAP equity/assets mislabeled as Tier 1 leverage

**Defect.** Regulatory stress set
`tier_1_leverage_after_percent = equity_after / assets × 100` and compared it with a 4%
Tier 1 minimum. GAAP common equity is not Tier 1 capital, and reported total assets are not
the regulatory leverage exposure denominator.

**Corrected invariant.** The stress now reports
`gaap_equity_to_assets_after_percent`. It returns
`regulatory_leverage_after_percent: null` and
`regulatory_leverage_status: regulatory_leverage_not_verified`, lists the missing Tier 1
numerator and leverage exposure denominator, and does not apply a regulatory minimum to the
GAAP ratio. A `regulatory_leverage_not_verified` finding is emitted.

**Tests.** The institution suite asserts the absence of `tier_1_leverage_after_percent` and
`passes_minimum`, and the independent audit checks the same identity.

## 4. Bank `growth` was accepted but ignored

**Defect.** `BANK_DEFAULTS` exposed `growth`, and `_bank_arithmetic()` accepted it, but the
forecast did not use it. A user changing growth saw no change in value.

**Corrected invariant.** Growth is not a free assumption. Explicit-period book value grows
under clean surplus at `implied_growth = ROE × (1 − payout)`. Supplying `growth` is rejected
with a `growth_is_not_a_free_parameter` finding and `rejected_assumptions`; the computed
value is unchanged. Terminal clean surplus is kept coherent by deriving the implied terminal
payout `1 − terminal_growth / ROE`, rather than silently carrying the explicit payout into
perpetuity.

**Versioning.** `atlas.bank.residual_income.v3`. v2 package files still execute: the old
package was installed on a fresh schema-13 database after the change and reported
`reproduced=True`, `differences={}`. Old assumptions are not silently rewritten in place.

## 5. ROE was the ending-equity ratio

**Defect.** Net income available to common was divided by period-end common equity and
emitted as `reported_roe`, although that is not the company's defined annual ROE.

**Corrected invariant.** The model distinguishes:

- `ending_equity_roe_proxy` — net income to common / ending common equity;
- `average_common_roe` — net income to common / average of prior and current fiscal year-end
  common equity;
- `company_reported_roe` — `null` unless a company disclosure is mapped.

Beginning common equity is the prior fiscal-year SEC `StockholdersEquity` less preferred
stock. `roe_used` and `roe_basis` state which ratio drives the model. The beginning values
are exposed in outputs and packaged metrics with their evidence.

**Reference values at the 2025-06-30 cutoff; 2024 10-K facts.**

| Bank | Common equity | Prior common equity | Average common equity | Ending proxy | Average ROE |
| --- | ---: | ---: | ---: | ---: | ---: |
| JPM | $324.708B | $300.474B | $312.591B | 17.5136% | **18.1925%** |
| GS | $108.743B | $105.702B | $107.2225B | 12.4376% | **12.6139%** |

## 6. Revised bank reference results

| Case | Phase 9.2 (v2) | Phase 9.2.1 (v3) |
| --- | ---: | ---: |
| JPM default: CoE 10.0% | $278.0365 | **$295.4644** |
| JPM stated: ROE 17.0%, CoE 9.5% | $287.9196 | **$287.9196** |
| GS default: CoE 11.0% | $422.9237 | **$432.1964** |

The changed default is caused by using average rather than ending common equity. The 17%
scenario is unchanged because its ROE is supplied explicitly. Market-implied CoE is
**10.1193%** for JPM at $289.91 and **8.0781%** for GS at $707.75; these remain conditional
solutions, not estimates of the true cost of capital. No result is promoted to
`economically_reviewed` or `independently_benchmarked`.

## 7. Historical availability and replay

Observation, reporting period, retrieval, filing availability, information cutoff and
market session remain separate fields. A market session is not treated as proof that a
vendor's current dataset existed in that form. Source selection is stored on the package so
a later import cannot silently change the provider used by a saved analysis. Restricted
prices remain absent from report payloads and packages.

## 8. Verification

- Backend suite: **459 passed**; frontend **4 passed**, typecheck and production build pass.
- Frontend: unit tests, TypeScript typecheck and production build.
- Market integrity: provider A/B conflict, idempotency, revision, rollback, ambiguity,
  rights isolation and adjusted-series rejection.
- Bank audit: 29/29 independent Decimal checks, including average ROE, roll-forward,
  terminal value, per-share consistency, GAAP stress labeling and package reproduction.
- Migration suite: fresh 1→13, populated upgrade, interrupted rollback, concurrent startup.
- Package: 63,816 bytes, SHA-256
  `3bbaca5447ffbd3421dce48fb833fccbd16a2977fa875e15498aae7bc4d1cfe8`;
  clean install reproduces $295.4644 with `differences={}` and excludes `289.91`.

## 9. Remaining limitations and blockers

1. Genuine `ATLAS_MASTER_SPEC.md` v1.2.0 was not supplied. Expected 155,419 bytes and
   SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`. The gate
   remains blocked; no substitute was created.
2. No Tier 1 capital numerator or regulatory leverage exposure denominator is mapped, so
   regulatory leverage cannot be verified.
3. Parent goodwill/intangibles and dollar parent RWA remain unmapped.
4. Point-in-time FR Y-9C reconstruction is prohibited without a publication timestamp or
   vintage.
5. Nasdaq automated collection is not authorized; imports remain local CSV only.
6. Browser automation in this container has crashed after SPA startup in prior runs.
   Results are reported separately from API success and are not inferred.
