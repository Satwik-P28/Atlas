# Phase 9.2 final acceptance

**Status: NOT FULLY ACCEPTED — two gates blocked.**

This record covers the Phase 9.2 final-acceptance pass on 2026-11-06. The verified
subset is committed locally on branch `freebuff/41a4fd2abe41a6515dc8d5bb`; nothing was
pushed or deployed.

Full acceptance is withheld for two substantive reasons:

1. The genuine `ATLAS_MASTER_SPEC.md` is absent, so the mandatory specification
   transfer and hash verification could not be performed.
2. The bank residual-income model opens on consolidated **total stockholders'
   equity**, not common equity. JPM's preferred stock is not in the retained SEC
   concept set, so the model cannot deduct the preferred claim. Its arithmetic is
   verified, but the requested common-book-value input is not implemented.

These are recorded as blockers, not converted into passes by changing labels.

## Gate matrix

| # | Gate | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Genuine master specification | **Blocked** | File absent; verifier exits 1. Expected 155,419 bytes and SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`. No substitute was generated. |
| 2 | Schema migration and fresh install | **Pass** | Schema 13; fresh migration 1→13; `tests/test_phase9_2_migrations.py` passes. |
| 3 | Official consolidated FR Y-9C evidence | **Pass for the current archive snapshot** | FFIEC NIC `BHCF20241231.ZIP`, 1,509,964 bytes, 3,806 rows; JPM top-tier RSSD 1039502; 17 observations written. |
| 4 | Parent/subsidiary separation | **Pass** | FR Y-9C parent and FDIC CERT 628 subsidiary are distinct, non-additive bases. Parent capital is `used_in_per_share=false`. |
| 5 | Consolidated valuation arithmetic | **Arithmetic pass; common-book gate blocked** | Independent Decimal audit 19/19. The model uses $344,758M total equity; consolidated common equity is $324,708M after $20,050M preferred. No common-equity claim is made. |
| 6 | SEC history and information cutoff | **Partial** | SEC facts retained from 2018; cutoff 2025-06-30 selects price 289.91 and accounting period 2024-12-31. Only one FR Y-9C period is stored. |
| 7 | Point-in-time regulatory reconstruction | **Prohibited, not claimed** | The bulk BHCF archive has no release timestamp or vintage; `published_at=NULL`, `availability_precision=unknown`, `historical_use=blocked_publication_timestamp_missing`. |
| 8 | Data rights and restricted-price containment | **Pass for the verified path** | FFIEC/FDIC data public domain; user price series restricted. Report and package contain no `289.91`; package `price_included=false`. Nasdaq automated access remains disabled. |
| 9 | Browser journeys A–J | **Pass** | Desktop 1440×1100 and mobile 390×844; parent/subsidiary labels, cutoff, method rejection, market semantics, save/reopen, export and regression routes. |
| 10 | 390 px mobile acceptance | **Pass** | Document width 390/390; no clipped key values; all 8 tested controls are 44 px high; tables scroll within their containers. |
| 11 | Save/reopen and portable export | **Pass** | Research object saved and reopened at 305.6980; package downloaded and reproduced with `differences={}`. |
| 12 | Clean-database reproduction | **Pass** | Fresh schema-13 database, install `AINS-66deed04176f25b08228`, execute status `reproduced`. |
| 13 | Backend, frontend and audit | **Pass** | 445 backend tests, 4 frontend tests, production build, independent audit 19/19. |
| 14 | Benchmarks and documentation | **Pass** | Phase 9.2 benchmark and this record added; hardware and source sizes recorded. |

## Specification identity (blocked)

`scripts/verify_master_spec.py` exits **1**:

```text
BLOCKED: ATLAS_MASTER_SPEC.md is not present; expected 155419 bytes,
sha256 e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9
```

The expected identity is recorded for a future transfer. It was not generated,
edited, approximated or replaced.

## Consolidated bank evidence

Official source: FFIEC National Information Center, bulk BHCF archive for period
2024-12-31.

- `fixtures/regulatory/BHCF20241231.ZIP` — 1,509,964 bytes, SHA-256
  `65b6479f0b0bc191e57cd2a446cbe31cbcaa3131bf6a1bbdbe4df259f6c89a4b`.
- `fixtures/regulatory/Financial_Download_Dictionary.xlsx` — SHA-256
  `26c40652a520826167108064db90e329f5cf4c725cb1017599152781ec62188a`.
- JPMorgan Chase & Co., legal name `JPMORGAN CHASE & CO.`, CIK `0000019617`,
  top-tier RSSD `1039502`; insured subsidiary CERT `628`.
- 3,806 rows in the archive; 17 declared FR Y-9C observations stored for JPM.
- `net_charge_offs` is missing and remains missing; it is not replaced with zero.

Reported parent consolidated values (USD thousands):

| Field | MDRM | Value |
| --- | --- | ---: |
| Total assets | BHCK2170 | 4,002,814,000 |
| Total equity capital | BHCK3210 | 344,758,000 |
| Perpetual preferred stock | BHCK3283 | 20,050,000 |
| Derived common equity | BHCK3210 − BHCK3283 | 324,708,000 |
| Goodwill | BHCK3163 | 52,565,000 |
| Risk-weighted assets | BHCAA223 | 1,757,460,260 |
| CET1 ratio | — | 15.6768% |
| Tier 1 ratio | — | 16.7788% |
| Tier 1 leverage ratio | — | 7.2443% |

Tangible common equity is `not_available`: other intangible assets are unmapped, and
goodwill is not substituted for all intangibles. Parent consolidated capital is
displayed separately from the FDIC subsidiary and is not used in per-share outputs.

### Common-equity blocker

The bank model's opening input is the SEC `StockholdersEquity` value,
**$344,758M**. The FR Y-9C consolidated common equity is **$324,708M** after the
**$20,050M** preferred claim. The retained SEC concept set has no preferred-stock
fact, and the model does not subtract the FR Y-9C regulatory preferred amount from
GAAP equity because those are different reporting bases.

The model now emits:

```json
{
  "book_value_common_equity": 344758000000.0,
  "book_value_basis": "consolidated_total_stockholders_equity",
  "common_equity_status": "not_derived_preferred_stock_unmapped"
}
```

The legacy key is retained for contract compatibility but is not a common-equity
measure. Its per-share output is diagnostic arithmetic, not an accepted common-share
valuation. This gate remains open until a genuine SEC preferred-stock fact is
ingested and reconciled.

## Valuation and export evidence

- Base value per share: **280.51**.
- With ROE 17.0% and cost of equity 9.5%: **305.6980**.
- Report SHA-256: `595133961e843ef41401dc884022ecd3d033b0c84bfe6e723cd310a8a8a7e80f`.
- Exported `artifacts/phase9_2_application.atlas`: **61,109 bytes**, SHA-256
  `66deed04176f25b08228a75569917c6c0834e646742d8c05b7cd2ad183c80ce8`.
- Package install/execute on a clean schema-13 database: `reproduced`, `differences={}`.
- The package contains no restricted price `289.91`; `price_included=false`.
- Reproduction evidence: `artifacts/phase9_2_reproduction.json`.

## Browser evidence

- `artifacts/phase9_2_browser.json` — all A–J assertions.
- `artifacts/phase9_2_e2e_final.log` — `PHASE9_2_EXIT=0`.
- Desktop: `artifacts/phase9_2_final_desktop_jpm.png`.
- Saved: `artifacts/phase9_2_final_saved.png`.
- Reopened: `artifacts/phase9_2_final_reopened.png`.
- Mobile 390×844: `artifacts/phase9_2_final_mobile.png`.
- Saved object: `URO-APP-fa8186f1b037`; reopen value 305.7000.
- Full workflow measured at **46,597 ms**.

The Economic Lab returns HTTP 422 for `mode=public_available` because the database
contains zero economic observations. It is recorded as a known data gap; every other
HTTP or console error fails the run.

## Rights

- FR Y-9C and FDIC observations: U.S. government public domain.
- SEC EDGAR facts: U.S. government public domain.
- JPM market price 289.91 on 2025-06-30: user-supplied restricted series, excluded
  from reports, packages, exports and snapshots.
- Nasdaq automated collection remains disabled: no provider authorization record.
  Local CSV import is the only supported market-price path.

## Verification

| Check | Result |
| --- | --- |
| Backend pytest | **445 passed** in 146.20 s |
| Frontend unit tests | **4 passed** |
| Production frontend build | **passes** |
| Independent model audit | **19/19 passed**, `artifacts/phase9_2_final_audit.txt` |
| Browser A–J | **pass**, exit 0 |
| Clean package reproduction | **pass**, `differences={}` |

Hardware: 2 vCPU, 3.8 GiB RAM. Benchmarks are single-run observations, not service
guarantees; see `docs/PHASE9_2_BENCHMARKS.md`.

## Reproduce

```bash
ATLAS_DB=var/phase9.db .venv/bin/python -m uvicorn atlas.terminal.api:create_app \
  --factory --host 0.0.0.0 --port 3000
.venv/bin/python -m pytest -o addopts='' -q -p no:warnings
.venv/bin/python scripts/audit_phase9_2_models.py
.venv/bin/python scripts/reproduce_phase9_2.py
.venv/bin/python scripts/benchmark_phase9_2.py
cd web && node e2e/phase9_2.mjs
```

The browser runner needs a usable local Chromium and fonts; those local libraries are
not committed. The package reproduction needs only the committed artifact and a fresh
schema-13 database.

## Not accepted / not claimed

- No claim that the bank model values **common** equity.
- No point-in-time FR Y-9C reconstruction or historical regulatory cutoff.
- No parent tangible book value per share.
- No dollar parent capital headroom; only reported percentage ratios.
- No external analyst or market valuation benchmark.
- No Nasdaq automated data rights.
- No macOS or Windows verification.
- No Phase 9.3 or Phase 10 work.

The verified subset is suitable for local review only. Full Phase 9.2 acceptance
requires the genuine master specification and a defensible common-equity input.
