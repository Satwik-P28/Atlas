# Probability calibration

Status: **implemented and independently tested.** The metric arithmetic is local Python, not
delegated to a library whose version could silently change a reported score.

## Definitions

For aligned probabilities `p_i` and binary outcomes `y_i ∈ {0,1}`:

**Brier score**

```
BS = (1/N) Σ (p_i - y_i)^2
```

**Log loss** with `ε = 1e-12` clipping:

```
LL = -(1/N) Σ [ y_i log(p_i) + (1-y_i) log(1-p_i) ]
```

**Expected calibration error** over `B` bins:

```
ECE = Σ_b (n_b / N) |mean(p in b) - mean(y in b)|
```

The implementation uses fixed-width bins `[b/B, (b+1)/B)`, with probability `1.0` included
in the final bin. Empty bins report `null` rather than zero.

## Independent checks

The test fixture `p = [0.9, 0.1, 0.8]`, `y = [1, 0, 1]` produces:

| Metric | Expected | Observed |
|---|---:|---:|
| Brier | 0.02 | 0.02 |
| Log loss | 0.14462152754328744 | same |
| ECE (2 bins) | 0.13333333333333333 | same |

The Brier test recomputes the definition independently. Log-loss boundary behavior is tested
with clipping. A probability outside `[0,1]` or a non-binary outcome raises an error.

## Calibration protocol

1. Train the raw model on the training partition.
2. Generate raw probabilities on the validation partition.
3. Fit Platt scaling — a one-dimensional logistic map on the logit — on validation rows.
4. Freeze the calibrator in the model artifact.
5. Evaluate on the untouched test partition.

The test partition is never used to fit the calibrator or select the model. If validation
contains only one outcome class, the calibrator is not fitted and the artifact records that
fact; the raw probability is retained.

## Real-data result

Selected model: ridge. Validation rows for calibration: **680**. Test rows: **685**.

| Metric | Value |
|---|---:|
| Raw Brier | 0.248114 |
| Calibrated Brier | 0.248493 |
| Climatology Brier | 0.248830 |
| Brier skill vs climatology | -0.001354 |
| Log loss | 0.690132 |
| AUC | 0.497647 |
| Accuracy at 0.5 | 0.543066 |
| Test prevalence | 0.543066 |
| ECE, 10 bins | 0.019182 |
| Calibration rows | 680 (validation only) |

The calibrated Brier is slightly worse than the raw Brier and the skill is negative. This is
reported as a negative result. A low ECE on 685 correlated rows does not establish a
well-calibrated conditional distribution.

The populated test bin is 0.5–0.6: 685 observations, mean probability **0.523883**, observed
rate **0.543066**, gap **-0.019182**. All other bins are empty. A reliability diagram with
one populated bin is not strong evidence of calibration.

## Uncertainty and sample size

The experiment computes a paired block-bootstrap diagnostic for the Brier improvement. Its
interval and the fact that rows from one session are dependent are reported in the audit.
The auditor does not declare the model superior merely because a point estimate is positive.

## Anti-patterns rejected

* Selecting a model on test Brier and reporting the same number as out-of-sample.
* Fitting a calibrator on the final test set.
* Calling accuracy “calibration”.
* Treating a single populated bin as a reliability curve.
* Reporting a lower Brier on a small sample as definitive superiority.
* Converting a calibrated probability directly into a position without a declared rule.

## API and compiler integration

The API returns `calibration`, `calibration_error`, `brier`, `log_loss`, `auc`, prevalence
and observation count. The FEC exposes:

* `probability_brier`;
* `probability_log_loss`;
* `probability_calibration_error`.

Compiler execution of `p=[0.9,0.1,0.8]`, `y=[1,0,1]` returns the same 0.02, 0.144621…,
0.133333… values. React renders results; it does not calculate them.

## Limitations

* No isotonic regression.
* No beta calibration or continuous ranked probability score.
* No horizon grouping beyond one session.
* No missing-outcome imputation; unresolved outcomes are omitted.
* No guarantee of calibration under regime shift.
