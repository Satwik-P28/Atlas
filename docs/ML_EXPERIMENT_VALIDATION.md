# ML experiment validation

Status: **implemented for one real demo panel.** The protocol is deliberately conservative
and the result is negative.

## Hypothesis

The recorded hypothesis is:

> Point-in-time price and volume features improve next-session probability forecasts over
> climatology.

This is a forecast-accuracy hypothesis. It does not claim a profitable strategy.

## Chronological split

The panel has 752 aligned sessions. Rows begin after 60 sessions of feature history.

| Partition | Start | End | Sessions | Rows |
|---|---|---|---:|---:|
| Train | 2023-03-30 | 2024-11-19 | 414 | 2,070 |
| Validation | 2024-11-22 | 2025-06-11 | 136 | 680 |
| Test | 2025-06-16 | 2025-12-30 | 137 | 685 |

There is a **two-session embargo** between partitions. The split is chronological, not
shuffled. The test interval was not used for feature choice, model choice, calibration or
threshold tuning.

The row count is larger than the session count because each session has one row per
security. Rows in a session are cross-sectionally dependent; the effective sample size for
market-wide claims is closer to the session count.

## Candidate protocol

Four candidates were trained on the same features:

1. climatology;
2. ridge;
3. logistic regression;
4. 8-unit MLP.

All candidates used the same train/validation/test dates and the same feature matrix. The
selection criterion was validation Brier score, lower is better. The selected model was
**ridge**, validation Brier **0.249669**.

The complete attempt ledger is persisted in `learning_attempt`: stage, model, rank, selected
flag and metrics. Failed candidates would be retained rather than deleted; this run had no
training failures.

## Final result

| Metric | Ridge | Climatology |
|---|---:|---:|
| Test Brier | 0.248493 | 0.248157 |
| Brier skill | -0.001354 | 0 |
| Log loss | 0.690132 | — |
| AUC | 0.497647 | — |
| Accuracy at 0.5 | 0.543066 | — |
| ECE, 10 bins | 0.019182 | — |

The test Brier is slightly worse than climatology. The AUC is effectively 0.5. The
conclusion is **`not_supported`**, not “validated” and not “profitable”.

The model is still persisted because the experiment, artifact and negative evidence are
useful research memory. A failed hypothesis is not deleted.

## Continuous companion

A ridge return model was fitted on the same protocol:

| Metric | Value |
|---|---:|
| RMSE | 0.017966 |
| MAE | 0.011938 |
| Mean error | -0.0000988 |
| 90% interval coverage | 0.919708 |
| Observations | 685 |

The interval is `point forecast ± 1.645 × training residual sigma`. It is not a calibrated
predictive distribution. Coverage close to 90% is a descriptive result.

## Uncertainty and multiple testing

The experiment includes a paired block-bootstrap diagnostic for the Brier difference and
records the interval. The test rows are not independent; the bootstrap is a warning tool,
not a significance guarantee. The auditor reports an improvement interval that includes
zero as a warning. It does not compute an aggregate credibility score.

## Exploratory vs confirmatory

* **Exploratory:** feature selection, model family choice, hyperparameter choice and
  threshold exploration may use train/validation.
* **Confirmatory:** the final test interval is evaluated once after selection.
* **Discovery:** the bounded loop uses an earlier discovery split and never sees the final
  test. Its recommendation must be confirmed by a fresh experiment.

The run records `test_used_for_selection: false`. If a future workflow evaluates the test
set repeatedly, it must label those results exploratory; Phase 6 does not.

## Reproduction

The run id is derived from the panel hash, requested models/features, target and seed. The
artifact stores scaler, coefficients, calibrator, seed and software versions. The panel hash
is `a092e1f6…`. Replaying requires the same local vendor panel; exact vendor bytes are not
committed because rights are restricted. This is a reproducibility limitation, not a claim
of byte-level archival reproduction.

## What would change the conclusion

A positive, stable test skill with a paired interval excluding zero, across more sessions
and more names, would be required before calling the feature family promising. Even then it
would not establish trading profit. This experiment does not meet that bar.
