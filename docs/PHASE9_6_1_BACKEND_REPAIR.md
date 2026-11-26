# Phase 9.6.1 — Backend Repair

## The Phase 6 failures were not "dependency drift"

Phase 9.6 reported four failures in `tests/test_phase6_learning.py` and attributed them to
newly resolved dependencies. That diagnosis was wrong.

Reproduction with the same interpreter and a fresh `pip install -e ".[dev,terminal]"`:

```
FAILED tests/test_phase6_learning.py::test_experiment_selection_calibration_and_audit_are_reproducible
FAILED tests/test_phase6_learning.py::test_auditor_flags_deliberate_contamination_and_small_sample
FAILED tests/test_phase6_learning.py::test_bounded_discovery_never_uses_final_test
FAILED tests/test_phase6_learning.py::test_api_persists_learning_run_forecast_audit_monitor_and_portfolio
```

Cause: the `learning` extra (`scipy`, `scikit-learn`, `pyarrow`) was never installed.
`discover()` therefore returned no recommendations, and the API answered the learning request with
422. Nothing was wrong with the application logic or the assertions.

Repair:

```
.venv/bin/pip install -r requirements-learning.lock
```

The lock pins `numpy==2.5.4`, `scipy==1.18.1`, `scikit-learn==1.9.1`, `pyarrow==26.0.1`,
`joblib==1.6.0`, `threadpoolctl==3.8.0`. All nine Phase 6 tests pass. No assertion was weakened.

Contributing factor: `pyproject.toml` documents that numpy moved out of the learning extra into
core dependencies, which made `.[dev,terminal]` look sufficient. It is not; the correct install for
the full suite is `.[dev,terminal,learning]`.

## Schema migration 015

Added `availability_model` and `public_availability_time`, relabelled 64 documents' availability
precision, and left timestamps untouched. Tests that pinned the schema version, the migration chain
and the upgrade-from-v9 target were updated from 14 to 15 — a version bump, not a relaxed
assertion.

## Full suite

`pytest -q` → all tests pass, exit 0, on the final environment (schema 15, learning lock installed).

## Residual

The environment is not reproducible from `pyproject.toml` alone: `requirements-learning.lock` must
be installed explicitly. A CI job that runs only `.[dev]` will fail for the same reason unless the
lock is included; this is documented rather than silently patched into a test skip.
