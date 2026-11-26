# Atlas Feature Engine v2

Status: **implemented for price, volume and cross-sectional features.** Fundamental,
macro, valuation and custom compiler-backed features remain extension points; they are not
claimed as implemented.

## Contract

`src/atlas/learning/features.py` defines `atlas.learning.feature.v2`.

Every feature declares a key, label, family, window and formula. The current catalogue is:

| Key | Family | Window | Formula at session `t` |
|---|---|---:|---|
| `mom_5` | momentum | 5 | `close[t] / close[t-5] - 1` |
| `mom_20` | momentum | 20 | `close[t] / close[t-20] - 1` |
| `mom_60` | momentum | 60 | `close[t] / close[t-60] - 1` |
| `vol_20` | risk | 20 | sample standard deviation of the last 20 daily returns |
| `sma_gap_20` | trend | 20 | `close[t] / mean(close[t-19..t]) - 1` |
| `volume_z_20` | liquidity | 20 | `(volume[t] - mean20) / stdev20` |
| `cs_mom_20_rank` | cross-section | 20 | percentile rank of `mom_20` among securities available at `t` |

The default set is `mom_5`, `mom_20`, `vol_20`, `sma_gap_20`, `cs_mom_20_rank`.
At least one and at most eight features may be selected.

## Timing and missing data

* Features use data at or before `t` only.
* The row carries `date`, `available_at` (`t` end) and `target_date` (`t+1`).
* The default target is next-session direction: `1` if `close[t+1] > close[t]`, otherwise
  `0`. A continuous next-session return target is also available for the companion ridge.
* `min_history` defaults to 60 and is raised to at least the largest feature window plus one.
* A row is omitted if any selected feature is unavailable. The engine does not
  forward-fill a price to manufacture a row.
* Cross-sectional rank uses only names present on that date. A missing name is not treated
  as the worst performer.
* Normalization is fitted later on training rows only. The artifact stores the exact mean
  and scale used at inference.

Every row is a `(security, date)` observation. Rows from the same session are
cross-sectionally dependent; the auditor warns that bootstrap intervals over rows do not
create independent observations.

## Real-data result

With all five default features and 60-session minimum history, the demo panel produces
**3,455 feature rows** across five securities. The first row is 2023-03-30. The last
target date is 2025-12-30. These rows are split chronologically, not shuffled.

## Leakage defenses

Implemented and covered by tests:

1. Feature construction reads index `i` and earlier only.
2. Target construction reads `i+1` and records `target_date`.
3. Chronological train/validation/test selection; the test dates are excluded from
   hyperparameter selection.
4. A two-session embargo between partitions.
5. Scaling fitted on training rows and stored in the model artifact.
6. Platt calibration fitted on validation rows, never on test.
7. Cross-sectional ranks recomputed per date, not from a future universe.
8. The final test result is evaluated once and marked `test_used_for_selection: false`.
9. The discovery loop never receives the final test split.

Adversarial tests include constant targets (model is not identifiable and fails), random
noise (no stable edge), missing observations, one-class validation, and target/date
alignment. The suite does not claim that passing these tests proves the absence of all
leakage.

## Fundamental and macro features

The Phase 6 UI and catalogue do not expose fundamental or macro features. The data fabric
records the prerequisites:

* accounting values must be keyed by `available_at`, not fiscal-period end;
* revised statements need a vintage or the feature must be labeled reconstructed;
* ALFRED vintages are required for point-in-time macro observations;
* currency and units must be declared before a ratio is formed.

Creating a “revenue growth” feature from a modern bulk fundamental download without a
vintage would violate the same timing rule the price features enforce. It is intentionally
not included as a checkbox.

## Custom compiler features

The Financial-Economic Compiler and Model Forge remain the typed execution path. A future
feature adapter must register an operator with declared inputs, units and availability, and
must pass the same compiler validation as a hand-authored model. React does not compute
features or model probabilities.

## Extension checklist

A new feature must declare:

* inputs and source class;
* observation frequency and window;
* minimum history;
* missing-value policy;
* unit/currency;
* historical availability;
* transform implementation and version;
* whether it is fitted (and on which partition).

Until those are present, the feature belongs in a research note, not the default catalogue.
