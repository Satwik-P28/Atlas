# ADR 0027 — JSON learning artifacts and CPU stack

Status: accepted, Phase 6.

## Context

The environment could install NumPy, SciPy, scikit-learn and PyArrow. Pickle/joblib model
loading executes code and hides the fitted parameters. GPU frameworks add a large, optional
dependency for a five-security tabular problem.

## Decision

Use NumPy/scikit-learn on CPU and store every fitted model as inspectable JSON:

* scaler means/scales;
* ridge/logistic coefficients and intercepts;
* MLP weight matrices, intercepts and activation names;
* calibration coefficients;
* seed, row count, feature count and software versions.

Do not use pickle for model loading. The MLP is one 8-unit ReLU layer, not a foundation
model. A continuous companion ridge stores its residual sigma and interval convention.

## Consequences

Positive:

* model files are reviewable and portable;
* no arbitrary code execution on load;
* CPU-only reproducibility;
* the same artifact works for API replay and research objects.

Negative:

* JSON is not a universal serialization for arbitrary model families;
* larger networks would bloat the artifact;
* no GPU acceleration;
* scikit-learn version drift must be recorded and checked.

## Rejected alternatives

* pickle: rejected for execution safety and opacity;
* a custom neural framework: unnecessary at this scale;
* GPU-first design: no measured bottleneck justified it;
* claiming the MLP is “AI” without an honest baseline comparison: rejected.

## Follow-up

Add adapter-based serialization only when a model family cannot be represented safely, with
a versioned schema and a loader allowlist.
