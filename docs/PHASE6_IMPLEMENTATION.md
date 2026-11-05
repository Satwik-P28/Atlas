# Phase 6 implementation — Atlas Learning Brain

Status: **implemented vertical slice on schema 8.** The real-data forecasting result is
negative. The architecture, evidence, UI and forecast-to-portfolio bridge are implemented;
point-in-time vendor vintages and a broad licensed universe are not.

## Delivered capabilities

| Capability | State | Evidence |
|---|---|---|
| Real five-security market panel | Implemented from EODHD demo | 5 names, 752 sessions, 3,760 bars |
| Dataset rights and coverage view | Implemented | `atlas.learning.dataset.v2`; hash, quality, vintage label |
| Point-in-time feature timing | Implemented | `date < target_date` for every row; 3,455 rows |
| Competing models | Implemented | climatology, ridge, logistic, 8-unit MLP |
| Chronological evaluation | Implemented | 60/20/20, 2-session embargo, frozen test |
| Calibration | Implemented | Platt on 680 validation rows; ECE/Brier/log loss |
| Attempt ledger | Implemented | four candidates retained |
| Model auditor | Implemented | six named findings; no overall score |
| Research memory | Implemented | run/attempt/model/forecast tables; API queries |
| Bounded discovery | Implemented | finite grid, budget cap, test never used |
| Monitoring | Implemented | drift observations and realized calibration |
| Typed forecast contract | Implemented for binary/continuous | `atlas.forecast.v1` |
| Forecast-to-portfolio | Implemented | frozen probabilities → Quant Lab → reconciled ledger |
| Research objects | Implemented | model and experiment UROs |
| Learning Lab | Implemented | `/lab/learning` |
| Benchmark | Implemented | `artifacts/phase6_benchmarks.json` |

## Architecture

```
immutable bars + source registry
        ↓
learning.data       dataset view, rights, coverage, quality
        ↓
learning.features   point-in-time price/volume/cross-section rows
        ↓
learning.models     JSON artifacts (climatology/ridge/logistic/MLP)
        ↓
learning.experiments  split → candidates → calibration → frozen test
        ↓
learning.metrics    independent Brier/log loss/AUC/ECE
        ↓
learning.audit      named findings with evidence + limitations
        ↓
learning.service    schema-8 persistence, memory, monitor, portfolio
        ↓
Learning Lab + typed API + existing Quant Lab
```

The Financial-Economic Compiler remains the typed execution foundation. Phase 6 adds three
probability operators: `probability_brier`, `probability_log_loss` and
`probability_calibration_error`. The Quant strategy contract adds a frozen
`learning_probability` signal. The portfolio ledger remains authoritative for strategy
economics.

## Schema 8

Migration 008 is additive:

* `learning_run` — canonical result/spec JSON, fingerprint, dataset, target, data class,
  status, duration, model/experiment object ids;
* `learning_attempt` — every model attempt, rank, selected flag and metrics;
* `learning_model` — immutable JSON artifact, feature schema, family, target, metadata;
* `learning_forecast` — security/date probability with horizon, bounds and eventual outcome.

`/api/health` reports `schema_version: 8`, `supported_schema: 8`, `integrity_check: ok`.

## Real run

`LRUN-5465504d8d6a287fade6`

| Item | Value |
|---|---|
| Window | 2023-01-03 → 2025-12-31 |
| Split | 2,070 train / 680 validation / 685 test rows |
| Selected model | ridge |
| Validation Brier | 0.249669 |
| Test Brier | 0.248493 |
| Brier skill | -0.001354 |
| AUC | 0.497647 |
| Log loss | 0.690132 |
| ECE, 10 bins | 0.019182 |
| Conclusion | `not_supported` |
| Audit | 0 errors, 4 warnings, 2 infos |
| Model object | `URO-MOD-68ac720cd414` |
| Experiment object | `URO-EXP-aaa1fbf7bd2f` |

The continuous companion reports RMSE 0.017966 and 90% interval coverage 0.919708. The
interval is a training-residual approximation, not a posterior.

## Forecast-to-portfolio

The frozen test forecasts are converted into a declared long-only rule. At a 0.50 threshold:

* return **14.3797%**;
* buy-and-hold **14.3797%**;
* excess **0.0**;
* turnover 0.9145;
* Sharpe 2.3212;
* max drawdown -5.273%;
* 137 sessions;
* transaction costs $69.83;
* application `URO-APP-03ab3363756d`;
* strategy `URO-STR-8c7cdbd4c67c`.

The rule is effectively always long and therefore duplicates buy-and-hold. At 0.55 no
forecast clears the threshold and the strategy holds cash (0% return). This is evidence
that the decision layer adds no value here; it is not evidence of alpha.

## Defects found and fixed

* The target definition object was bound to the SQL result column named `target`, which
  would have serialized the wrong value. It is now bound to the explicit target key.
* The auditor used `code`, which the research-object validator rejects; findings now use
  `finding_key`.
* `sqlite3.Row` has no `.pop`; run summaries were converted to a mutable dict.
* Forecast persistence truncated at 400 rows, silently shortening the test interval from
  685 to 400 and limiting the portfolio to 80 sessions. The cap was removed and a regression
  asserts forecast count equals test observations.
* The strategy and application names omitted the decision threshold, so changing it caused
  a legitimate immutable-object collision. Threshold is now part of both identities; a
  regression asserts distinct strategy objects.

## Verification

* Full backend suite green at schema 8: **363 passed**; Phase 6 adds nine independent tests.
* Frontend Vitest tests and production build pass.
* `web/e2e/phase6.mjs` passes and covers experiment, calibration, audit, portfolio, monitor,
  save/reopen and 390 px layout.
* Benchmark artifact records CPU timings.

## Deliberate boundaries

* Restricted vendor bytes are not committed.
* The panel is observed, not point-in-time verified.
* Five current securities are not a market universe or survivorship-free panel.
* No fundamental/macro features, categorical forecasts, event-market execution or GPU.
* No claim of persistent predictive skill or economic value.
* `ATLAS_MASTER_SPEC.md` is absent; this record and the Phase 5 contract are the in-repo
  authority.
