# Phase 9.2 final acceptance

**Status: implementation complete; one external gate remains blocked.**

The common-equity valuation gate is closed. The genuine `ATLAS_MASTER_SPEC.md` is still
absent, so master-spec verification and the full desktop/mobile A–J rerun are not claimed
as passes. Nothing in this record is promoted to `economically_reviewed` or
`independently_benchmarked`.

## Gate matrix

| # | Gate | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Genuine master specification | **Blocked** | File absent; `scripts/verify_master_spec.py` exits 1. Expected 155,419 bytes and SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`. No substitute generated. |
| 2 | Schema migration and fresh install | **Pass** | Schema 13; fresh migration 1→13; migration tests pass. |
| 3 | Official consolidated FR Y-9C evidence | **Pass for the archive snapshot** | FFIEC NIC `BHCF20241231.ZIP`, 1,509,964 bytes, 3,806 rows; JPM RSSD 1039502; 17 observations. |
| 4 | Parent/subsidiary separation | **Pass** | Consolidated FR Y-9C and FDIC CERT 628 are distinct, non-additive bases. |
| 5 | Common-equity bank valuation | **Pass** | SEC total equity less same-period SEC preferred stock. JPM common book $324.708B; GS common book $108.743B. |
| 6 | SEC history and information cutoff | **Pass for 2025-06-30** | Cutoff selects price 289.91 and accounting period 2024-12-31; no later facts enter the model. |
| 7 | Point-in-time regulatory reconstruction | **Prohibited, not claimed** | Bulk archive has no publication timestamp or vintage; historical regulatory cutoff is blocked. |
| 8 | Data rights and restricted-price containment | **Pass** | FFIEC/FDIC and SEC data are public domain. Report and package contain no `289.91`; `price_included=false`. |
| 9 | Browser journeys A–J | **Partial — Cloud visual only** | Cloud browser rendered the rebuilt JPM workspace and reached the cutoff control. The local Playwright runner crashes in Chromium 156 after the SPA starts, so the full A–J suite is not claimed for this build. |
| 10 | 390 px mobile acceptance | **Not rerun for this build** | The prior 390×844 evidence predates the common-equity UI result. Layout code was not changed. |
| 11 | Save/reopen and portable export | **Pass — package path** | Exported package installed and executed on a fresh schema-13 database with `differences={}`. |
| 12 | Clean-database reproduction | **Pass** | `AINS-e99e6269ec47f7953177`, status `reproduced`. |
| 13 | Backend, frontend and audit | **Pass** | 446 backend tests, 4 frontend tests, production build, Phase 9.2 audit 28/28, Phase 9.1 audit 16/16. |
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
| Common ROE | common income / common equity | **17.5136%** |

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
| Common ROE | common income / common equity | **12.4376%** |

GS retains its capital-markets driver and 11% default cost of equity. No JPM-specific
assumption or adjustment is copied.

## Valuation evidence

At the 2025-06-30 cutoff:

| Case | JPM value/share | JPM equity value |
| --- | ---: | ---: |
| Default: reported common ROE 17.5136%, CoE 10.0% | **278.0365** | $777.835B |
| Stated scenario: ROE 17.0%, CoE 9.5% | **287.9196** | $805.484B |
| GS: reported common ROE 12.4376%, CoE 11.0% | **422.9237** | $131.383B |

Market-implied CoE: JPM **9.7424%** at $289.91; GS **7.9718%** at $707.75. These are
conditional solving outputs, not estimates of the true cost of capital.

The old total-equity JPM result (280.51 base, 305.6980 at 17%/9.5%) is superseded and must
not be used.

## Portable package

- `artifacts/phase9_2_application.atlas` — **61,281 bytes**.
- SHA-256 / package SHA-256: `e99e6269ec47f7953177281f5ee85b73ef3dfb144b4321c28cfc1ad606ed09ed`.
- Package reports `book_value_used=324708000000`, `preferred_equity=20050000000`,
  `book_value_basis=sec_total_stockholders_equity_less_preferred_stock`.
- Clean schema 13 install/execute: `reproduced`, `differences={}`.
- Restricted price `289.91`: absent; `price_included=false`.

## Verification

| Check | Result |
| --- | --- |
| Backend pytest | **446 passed** in 143.62 s |
| Frontend unit tests | **4 passed** |
| TypeScript + production build | **passes**; bundle 701.09 kB / 207.27 kB gzip |
| Independent Phase 9.2 audit | **28/28 passed** |
| Independent Phase 9.1 audit | **16/16 passed** |
| Clean package reproduction | **pass**, `differences={}` |
| Cloud browser render | **pass for JPM workspace and controls** |
| Local Playwright A–J | **blocked by Chromium 156 renderer crash** |
| 390×844 rerun | **not completed** |

## Rights

- SEC, FFIEC and FDIC observations: U.S. government public domain.
- JPM price 289.91 and GS price 707.75: restricted user-supplied series, excluded from
  reports, packages, exports and snapshots.
- Nasdaq automated collection remains disabled; local CSV import only.

## Remaining blockers

1. Genuine `ATLAS_MASTER_SPEC.md` absent and unverified.
2. Full local browser A–J and 390×844 rerun blocked by the container Chromium crash.
3. Point-in-time FR Y-9C reconstruction prohibited without a release timestamp/vintage.
4. Parent tangible book per share and dollar parent RWA remain unmapped.
5. Nasdaq automated data authorization absent.

No Phase 9.3 or Phase 10 work was started.
