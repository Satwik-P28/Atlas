# Model auditor

Status: **implemented.** `src/atlas/learning/audit.py` emits named findings with evidence
and limitations. It intentionally does not emit an overall credibility score.

## Why no score

An aggregate score hides which assumption failed and invites comparison of incomparable
studies. A model with a good Brier score can still use a restricted dataset, have no
economic value, or be evaluated on dependent rows. The auditor returns those facts
separately.

## Findings in the real run

`LRUN-5465504d8d6a287fade6` produced **6 findings: 0 error, 4 warning, 2 info**.

| Finding | Severity | Evidence |
|---|---|---|
| `chronological_partitions` | info | Test not used for selection; 2-session embargo |
| `test_skill_not_supported` | warning | Brier skill -0.001354; test Brier 0.248493 vs baseline 0.248830 |
| `data_vintage` | warning | `observed`, not `point_in_time_verified` |
| `redistribution_restricted` | warning | EODHD demo rights are restricted |
| `economic_value_not_established` | warning | Forecast accuracy is not portfolio profit |
| `reproducibility_scope` | info | Artifact fingerprint and panel hash retained; vendor bytes not committed |

The auditor did not find a small test sample (685 rows), severe class imbalance (54.3%
prevalence), or collinearity above 0.95. Those checks are present but did not fire.

## Audit domains

### Data

Coverage, missing sessions, source rights, historical vintage, and whether the panel is
synthetic. The auditor cannot verify cross-provider discrepancies without reference data, so
it does not claim to.

### Statistical

Test sample size, class prevalence, maximum absolute feature correlation, chronological
separation, evidence of test-set selection, and a block-bootstrap improvement interval.
Warnings are descriptive; crossing a threshold does not automatically invalidate a model.

### Mathematical

The implementation enforces probability bounds, finite values, aligned rows, and model
identifiability (at least two outcome classes). Numerical stability of the MLP is not proven
by these checks; the small architecture and fixed seed are the extent of the control.

### Forecast

Brier score, log loss, AUC, calibration table/ECE, raw-versus-calibrated comparison, and
uncertainty interval. A low ECE in one populated bin is not treated as proof of calibration.

### Economic and trading

The audit explicitly records that predictive accuracy is not economic value. The separate
portfolio experiment reports return, benchmark, turnover, costs, Sharpe and drawdown. The
auditor does not convert a forecast into a trading claim.

### Reproduction

The artifact fingerprint, scaler/coefficients, feature schema, split, seed, source hash and
software versions are retained. The run can be replayed from the local database. Exact
vendor bytes remain restricted, so byte-level archive reproduction is not claimed.

## API

`GET /api/learning/runs/{run_id}/audit` returns:

```json
{
  "schema": "atlas.learning.audit.v1",
  "findings": [{"finding_key": "...", "severity": "warning", "summary": "...",
                "evidence": {}, "limitation": "..."}],
  "counts": {"error": 0, "warning": 4, "info": 2},
  "overall_score": null,
  "note": "No aggregate credibility score is produced; read each finding and its limitation."
}
```

The UI renders the findings, including the limitation. It does not reduce them to a badge
such as “82% reliable”.

## Adversarial coverage

Tests and fixtures exercise:

* a constant target (model not identifiable);
* random/no-information outcomes;
* one-class validation (calibration not fitted);
* missing features (row omitted);
* a deliberately misaligned label (timing test);
* tiny samples (warning);
* correlated predictors (correlation diagnostic);
* restricted rights and non-point-in-time data.

The auditor is a rule-based reviewer, not a proof of correctness. A clean audit means the
implemented checks did not fire; it does not mean the research is true.

## Limitations

* No automatic leakage detector for arbitrary user code.
* No multiple-testing correction across many saved runs.
* No economic significance threshold; the portfolio experiment must be read separately.
* No causal identification.
* No aggregate score by design.
