# Learning runtime

Status: **implemented on a CPU-only NumPy/scikit-learn stack.** The runtime trains,
calibrates, persists and reloads small probability models. It is not a foundation-model
platform.

## Model library

`src/atlas/learning/models.py` exposes four probability models plus a continuous companion:

| Key | Family | Implementation | Purpose |
|---|---|---|---|
| `climatology` | baseline | Training prevalence assigned to every row | Honest naive benchmark |
| `ridge` | linear | Ridge regression on the 0/1 target, clipped to `[0,1]` | Regularized linear baseline |
| `logistic` | generalised linear | L2 logistic regression with training-only scaler | Standard classification baseline |
| `mlp` | neural network | One 8-unit ReLU hidden layer; deterministic seed; JSON weights | Tests whether a small nonlinear boundary helps |
| return ridge | continuous | Ridge on next-session return | Companion point forecast and interval |

The neural model is deliberately small. A more complex architecture is not presumed better;
the reported test result decides. No market foundation model, transformer or GPU training is
implemented.

## Artifact contract

Artifacts are JSON dictionaries with `artifact_version =
atlas.learning.model_artifact.v1`. They contain:

* model key and kind;
* feature count, training row count and training prevalence;
* scaler mean and scale;
* coefficients or MLP weight matrices and intercepts;
* seed and software versions;
* optional Platt calibrator fitted on validation rows;
* activation names for the MLP.

The runtime never uses pickle or joblib deserialization for model loading. A saved artifact
is inspectable and does not execute arbitrary code. This is a security property, not merely
a storage choice.

`predict_raw` reproduces the fitted transformation. `predict(..., calibrated=True)` applies
the stored logistic (Platt) map to the raw probability. Missing features are not imputed at
inference; the caller must supply the declared schema.

## Fitting protocol

1. Load the aligned panel and build features.
2. Split chronologically 60/20/20 with a two-session embargo.
3. Fit the scaler and every candidate model on train rows only.
4. Score candidates on validation Brier.
5. Select one candidate; fit Platt calibration on validation probabilities/outcomes.
6. Evaluate the frozen selection and calibrator on the test interval once.
7. Persist the model artifact, attempts, forecasts, audit and research objects.

A model version is the artifact/result version returned by the experiment. A retrain creates
a new run and a new research-object version; `learning_model` is insert-only in normal
operation. The deterministic run id makes an identical panel/spec/seed idempotent, but it
does not silently mutate an existing artifact.

## Selected real-data run

`LRUN-5465504d8d6a287fade6`:

| Item | Value |
|---|---|
| Dataset | `eodhd-demo:all`, observed, restricted |
| Features | `mom_5`, `mom_20`, `vol_20`, `sma_gap_20`, `cs_mom_20_rank` |
| Candidates | 4 |
| Selected | `ridge` |
| Validation Brier | 0.249669 |
| Test Brier | 0.248493 |
| Brier skill vs climatology | -0.001354 |
| AUC | 0.497647 |
| Log loss | 0.690132 |
| Calibration | Platt, 680 validation rows |
| Conclusion | `not_supported` |
| Model object | `URO-MOD-68ac720cd414` |
| Experiment object | `URO-EXP-aaa1fbf7bd2f` |

The test interval spans 2025-06-16 → 2025-12-30 and contains **685 forecast rows**. The
saved forecast table contains all 685, not a truncated sample.

## Dependencies and environment

| Package | Installed version |
|---|---|
| Python | 3.12.3 |
| NumPy | 2.5.4 |
| SciPy | 1.18.1 |
| scikit-learn | 1.9.1 |
| PyArrow | 26.0.1 |

The core terminal still runs without these optional packages for read-only/non-learning
work. Learning endpoints fail explicitly with an installation message if the `learning`
extra is unavailable; they do not silently return made-up values.

There is no GPU requirement. A GPU backend is an optional future adapter, not a Phase 6
capability.

## Inference boundary

The API persists forecasts as typed forecast documents. A forecast is not a trading signal.
The only conversion to a portfolio rule is the explicit `learning_probability` strategy
signal, which requires a threshold and a frozen date→probability mapping.

## Limitations

* One-day horizon only.
* No overlapping-label purge beyond the fixed embargo.
* No fundamental or macro features.
* MLP has no early stopping; it uses a fixed maximum iteration count.
* The demo panel has five current names, so cross-sectional ranks are coarse.
* Model selection has only four candidates; this is not a broad architecture search.
* Artifacts contain coefficients, not vendor data; exact inference requires the same feature
  schema and source panel.
