# Phase 6 readiness

Status: **implemented vertical slice; real-data result is negative; browser-verified on
schema 8.** The single deliberately incomplete gate is a licensed, point-in-time,
survivorship-aware market universe. Five real demo histories are present, but they are not
that universe.

## Acceptance gates

| # | Gate | Status | Evidence / limitation |
|---:|---|---|---|
| 1 | Existing functionality intact | **Pass** | 363 backend tests; 4 frontend tests; production build |
| 2 | Master specification imported or absence documented | **Pass, absent** | `ATLAS_MASTER_SPEC.md` is not in the checkout |
| 3 | Real-data ingestion and quality pipeline | **Pass for demo entitlement** | 5 EODHD demo symbols; 3,760 bars; 0 errors, 1 warning |
| 4 | Real vs synthetic and observed vs point-in-time distinguishable | **Pass** | `data_class`, `point_in_time_verified`, rights and vintage labels |
| 5 | Multiple genuine market histories | **Partial** | 5 real histories, 752 sessions; current-name selection, no licensed/PIT universe |
| 6 | Feature engine enforces historical timing | **Pass** | every row has `date < target_date`; 2-session embargo |
| 7 | Baseline forecasting models | **Pass** | climatology, ridge, logistic |
| 8 | More sophisticated model trained and compared fairly | **Pass** | 8-unit MLP trained; worse validation Brier, not selected |
| 9 | Probability scoring and calibration verified | **Pass** | independent Brier/log-loss/ECE identities; Platt on validation |
| 10 | Chronological validation and attempts preserved | **Pass** | 2,070 / 680 / 685 rows; 4 attempts; frozen test |
| 11 | Auditor catches a demonstrated defect | **Pass** | deliberate test contamination produces an error finding |
| 12 | Research memory retains success/failure | **Pass** | run/attempt/model/forecast ledger; negative run retained |
| 13 | Forecasts use typed interfaces | **Pass** | `atlas.forecast.v1`; FEC probability operators |
| 14 | Complete forecast-to-portfolio experiment | **Pass** | frozen probabilities → Quant Lab → reconciled ledger |
| 15 | Saved artifacts support reproducible inference | **Pass for local panel** | JSON artifact, fingerprint, 685 persisted forecasts; vendor bytes restricted |
| 16 | Learning Lab works | **Pass** | `/lab/learning`; desktop and 390 px browser journey |
| 17 | Required regressions pass | **Pass** | Phase 1–5 plus Phase 6; frontend build |
| 18 | Performance measured and documented | **Pass** | `PHASE6_BENCHMARKS.md`; JSON artifact |
| 19 | Missing data and poor results reported | **Pass** | `not_supported`, 4 warnings, rights/vintage limitations |

Gate 5 is marked **partial rather than substituted with synthetic names**. A broader licensed
universe is a Phase 7 prerequisite.

## Real-data result

| Item | Value |
|---|---|
| Run | `LRUN-5465504d8d6a287fade6` |
| Securities | AAPL, MSFT, TSLA, VTI, AMZN |
| Window | 2023-01-03 → 2025-12-31 |
| Feature rows | 3,455 |
| Test rows / forecasts | 685 / 685 |
| Selected model | ridge |
| Test Brier | 0.248493 |
| Climatology Brier | 0.248830 |
| Brier skill | -0.001354 |
| AUC | 0.497647 |
| Conclusion | `not_supported` |
| Audit | 0 error / 4 warning / 2 info |
| Model object | `URO-MOD-68ac720cd414` |
| Experiment object | `URO-EXP-aaa1fbf7bd2f` |

The continuous companion has RMSE 0.017966 and 90% interval coverage 0.919708. The interval
is a training-residual approximation.

## Forecast-to-portfolio result

At threshold 0.50: return **14.3797%**, buy-and-hold **14.3797%**, excess **0.0%**, Sharpe
2.3212, max drawdown -5.273%, 137 sessions, $69.83 transaction costs. At 0.55: no positions
and 0% return. The rule adds no observed decision value. This is not an alpha claim.

## Verification

* Backend: **363 passed**.
* Frontend: **4 passed**; production build 630.28 kB (189.28 kB gzip).
* Browser: `web/e2e/phase6.mjs` exits 0; screenshots `artifacts/34-learning-lab.png` and
  `artifacts/35-learning-mobile.png`.
* Browser coverage: experiment, Brier/calibration/audit, portfolio, monitor, save/reopen,
  no horizontal overflow at 390 px.
* Benchmark: dataset load 67.0 ms; features 47.0 ms; four candidates 800.6 ms; inference
  1.48 ms; audit 0.009 ms; peak RSS 158.9 MB.

## Implemented

Real-data adapter and local cache; dataset rights/coverage/vintage contract; data-quality
checks; point-in-time feature rows; four probability models and a continuous companion;
chronological selection; Platt calibration; proper scoring; persistent attempts and
forecasts; model auditor; research memory; bounded discovery; monitoring; typed forecast
contract; three FEC probability operators; `learning_probability` strategy signal;
forecast-to-portfolio application; Learning Lab; benchmark.

## Partial

* **Market universe:** five current US demo names, not a broad or survivorship-free panel.
* **Historical availability:** observed retrieval, not display-vintage verified.
* **Reproduction:** exact local database/artifact replay; vendor bytes are restricted.
* **Monitoring:** observations with sample sizes; no scheduled policy engine.
* **Decision layer:** one long-only threshold rule; no sizing/portfolio optimization.

## Unsupported

Licensed point-in-time vendor archive; delisting returns; fundamental/macro feature timing;
categorical probability forecasts; isotonic calibration; walk-forward learning loops;
cross-run multiple-testing correction; event-market settlement or live orders; GPU training;
LLM-required workflows; multi-user authentication; production execution.

## Master specification

`ATLAS_MASTER_SPEC.md` v1.1 is absent from the repository. No replacement was invented.
This record, the implementation, `PHASE5_CONTRACT.md` and the ADRs are the in-repo authority
until the supplied master is added.

## Phase 7 readiness

The typed pipeline, immutable artifacts, research memory and decision boundary are ready to
extend. The blocking prerequisite is data: a licensed point-in-time panel with corrections,
membership and delisting coverage. Without it, Phase 7 should not make stronger market-wide
or persistent-alpha claims.
