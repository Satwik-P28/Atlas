# Phase 9.2 final acceptance

**Status: Phase 9.2.1 integrity corrections implemented; master-spec gate remains blocked.**

The market-data, rights, security-identity, ROE, growth and regulatory-stress corrections
are recorded in [`docs/PHASE9_2_1_INTEGRITY_AUDIT.md`](docs/PHASE9_2_1_INTEGRITY_AUDIT.md).
The genuine `ATLAS_MASTER_SPEC.md` is still absent, so master-spec verification is not
claimed. Browser coverage is reported separately from API success. Nothing in this record
is promoted to `economically_reviewed` or `independently_benchmarked`.

## Gate matrix

| # | Gate | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Genuine master specification | **Blocked** | File absent; `scripts/verify_master_spec.py` exits 1. Expected 155,419 bytes and SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`. No substitute generated. |
| 2 | Schema migration and fresh install | **Pass** | Schema 13; fresh migration 1→13; migration tests pass. |
| 3 | Official consolidated FR Y-9C evidence | **Pass for the archive snapshot** | FFIEC NIC `BHCF20241231.ZIP`, 1,509,964 bytes, 3,806 rows; JPM RSSD 1039502; 17 observations. |
| 4 | Parent/subsidiary separation | **Pass** | Consolidated FR Y-9C and FDIC CERT 628 are distinct, non-additive bases. |
| 5 | Common-equity bank valuation | **Pass** | SEC total equity less same-period SEC preferred stock. JPM common book $324.708B; GS common book $108.743B. Average common ROE is used (JPM 18.1925%, GS 12.6139%). |
| 5a | Append-only multi-source market evidence | **Pass** | Provider A/B same-session rows coexist; identical replay is idempotent; corrections append revisions; malformed batches roll back. |
| 5b | Source and licence isolation | **Pass** | Stable per-provider/per-licence source ids; rights are immutable; no promotion to public domain. |
| 5c | Security and exchange identity | **Pass** | Ambiguous tickers rejected; explicit security/MIC required; no hard-coded `XNYS`. |
| 5d | Regulatory stress identity | **Pass** | GAAP equity/assets labelled; Tier 1 leverage `regulatory_leverage_not_verified`; no Tier 1 minimum applied. |
| 5e | Bank growth contract | **Pass** | Growth implied by clean-surplus retention; supplied `growth` rejected with a finding. |
| 6 | SEC history and information cutoff | **Pass for 2025-06-30** | Cutoff selects price 289.91 and accounting period 2024-12-31; no later facts enter the model. |
| 7 | Point-in-time regulatory reconstruction | **Prohibited, not claimed** | Bulk archive has no publication timestamp or vintage; historical regulatory cutoff is blocked. |
| 8 | Data rights and restricted-price containment | **Pass** | FFIEC/FDIC and SEC data are public domain. Report and package contain no `289.91`; `price_included=false`. |
| 9 | Browser journeys A–J | **Partial — Cloud visual only** | Cloud browser rendered Markets and the JPM workspace with consolidated FR Y-9C evidence and no console errors. The local Playwright runner cannot load `libnspr4.so`; with the workspace sysroot it starts but the renderer closes. Full A–J is not claimed. |
| 10 | 390 px mobile acceptance | **Not rerun for this build** | The prior 390×844 evidence predates the common-equity UI result. Layout code was not changed. |
| 11 | Save/reopen and portable export | **Pass — package path** | Exported package installed and executed on a fresh schema-13 database with `differences={}`. |
| 12 | Clean-database reproduction | **Pass** | `AINS-3bbaca5447ffbd3421dc`, status `reproduced`. |
| 13 | Backend, frontend and audit | **Pass** | Full backend suite, 4 frontend tests, production build, Phase 9.2 audit 29/29, Phase 9.1 audit 16/16. |
| 14 | Benchmarks and documentation | **Pass** | This record, bank/model/entity/gate docs and `artifacts/phase9_2_benchmarks.json` updated. |

## JPMorgan common-equity reconciliation

Both figures are same-period SEC GAAP facts from the 2024 10-K, accession
`0000019617-25-000270`, filed 2025-02-14:

| Item | SEC concept | USD |
| --- | --- | ---: |
| Total stockholders' equity | `StockholdersEquity` | 344,758,000,000 |
| Preferred stock | `PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount` | 20,050,000,000 |
| Common equity | total − preferred | **324,708,000,000** |
| Common shares | `CommonStockSharesOutstanding` | 2,797,600,000 |
| Book value per common share | common equity / shares | **116.0666** |
| Net income to common | `NetIncomeLossAvailableToCommonStockholdersBasic` | 56,868,000,000 |
| Ending-equity ROE proxy | common income / ending common equity | **17.5136%** |
| Average common ROE | common income / average common equity | **18.1925%** |

The FR Y-9C consolidated snapshot reports the same total equity (BHCK3210, $344,758M) and
perpetual preferred stock (BHCK3283, $20,050M). The model does **not** cross-subtract those
regulatory fields from GAAP equity; it derives common equity entirely from same-basis SEC
facts, then uses the FR Y-9C values only as an independent reconciliation check.

## Goldman Sachs

GS is audited separately and uses its own SEC fact, not JPM's tag or adjustments:

| Item | SEC concept | USD |
| --- | --- | ---: |
| Total stockholders' equity | `StockholdersEquity` | 121,996,000,000 |
| Preferred stock | `PreferredStockValue` | 13,253,000,000 |
| Common equity | total − preferred | **108,743,000,000** |
| Common shares | `CommonStockSharesOutstanding` | 310,653,708 |
| Book value per common share | common equity / shares | **350.0457** |
| Ending-equity ROE proxy | common income / ending common equity | **12.4376%** |
| Average common ROE | common income / average common equity | **12.6139%** |

GS retains its capital-markets driver and 11% default cost of equity. No JPM-specific
assumption or adjustment is copied.

## Valuation evidence

At the 2025-06-30 cutoff:

| Case | JPM value/share | JPM equity value |
| --- | ---: | ---: |
| Default: average common ROE 18.1925%, CoE 10.0% | **295.4644** | $826.591B |
| Stated scenario: ROE 17.0%, CoE 9.5% | **287.9196** | $805.484B |
| GS: average common ROE 12.6139%, CoE 11.0% | **432.1964** | $134.263B |

Market-implied CoE: JPM **10.1193%** at $289.91; GS **8.0781%** at $707.75. These are
conditional solving outputs, not estimates of the true cost of capital.

The old Phase 9.2 v2 defaults (JPM $278.0365, GS $422.9237) used ending common equity and
are superseded. The v2 17%/9.5% scenario remains $287.9196 because its ROE is explicit.
The older total-equity JPM result (280.51 base, 305.6980 at 17%/9.5%) must not be used.

## Portable package

- `artifacts/phase9_2_application.atlas` — **63,816 bytes** (version 1.1.0).
- SHA-256 / package SHA-256: `3bbaca5447ffbd3421dce48fb833fccbd16a2977fa875e15498aae7bc4d1cfe8`.
- Package state records `market_price_selection` (`atlas.market_price.selection.v1`) while
  `price_included` remains false.
- Package reports `book_value_used=324708000000`, `preferred_equity=20050000000`,
  `book_value_basis=sec_total_stockholders_equity_less_preferred_stock`.
- Clean schema 13 install/execute: `reproduced`, `differences={}`.
- The previous v2 package also reproduces unchanged on a fresh database (arithmetic did
  not change; the model version label is v3).
- Restricted price `289.91`: absent; `price_included=false`.

## Verification

| Check | Result |
| --- | --- |
| Backend pytest | **459 passed** |
| Frontend unit tests | **4 passed** |
| TypeScript + production build | **passes**; bundle 701.09 kB / 207.27 kB gzip |
| Independent Phase 9.2 audit | **29/29 passed** |
| Independent Phase 9.1 audit | **16/16 passed** |
| GitHub Actions | workflow added; remote status not yet observed |
| Clean package reproduction | **pass**, `differences={}` |
| Cloud browser render | **pass** — Markets, Equity research, JPM workspace and FR Y-9C evidence rendered with no console errors |
| Local Playwright A–J | **blocked** — bundled Chromium cannot load `libnspr4.so` in this container; adding the workspace sysroot gets past launch but the renderer still closes |
| 390×844 rerun | **not completed** — no mobile evidence is claimed for this build |

## Rights

- SEC, FFIEC and FDIC observations: U.S. government public domain.
- JPM price 289.91 and GS price 707.75: restricted user-supplied series, excluded from
  reports, packages, exports and snapshots.
- Nasdaq automated collection remains disabled; local CSV import only.

## Remaining blockers

1. Genuine `ATLAS_MASTER_SPEC.md` absent and unverified.
2. Full local browser A–J and 390×844 rerun blocked by missing Chromium libraries/renderer closure.
3. Regulatory Tier 1 leverage cannot be computed: the Tier 1 numerator and exposure denominator are unmapped.
3. Point-in-time FR Y-9C reconstruction prohibited without a release timestamp/vintage.
4. Parent tangible book per share and dollar parent RWA remain unmapped.
5. Nasdaq automated data authorization absent.

No Phase 9.3 or Phase 10 work was started.
