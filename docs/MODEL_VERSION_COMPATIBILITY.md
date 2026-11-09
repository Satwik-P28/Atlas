# Model and Operator Compatibility

Status: implemented in `src/atlas/fec/compatibility.py`, report schema
`atlas.model_compatibility.v1`.

## 1. The contract

A saved research object, run or application records the compiler version and the version
of every operator that produced it. Those records are only meaningful if a later run
resolves each operator to the implementation that produced the stored value. Reinterpreting
an old node with a newer implementation would change a saved result without changing its
fingerprint — the worst failure mode for a reproducibility system.

Resolution is therefore explicit and fails closed:

| Situation | Status | Outcome |
| --- | --- | --- |
| operator registered at the recorded version | `compatible` | reproduce |
| operator registered at a different version | `operator_version_mismatch` | refuse |
| operator not registered in this build | `unknown_operator` | refuse |
| operator deliberately removed | `retired_operator` | refuse, with the removal note |
| compiler version differs | `compiler_version_mismatch` | refuse |

`resolve_operator(name, version)` returns the registered implementation or raises
`IncompatibleModelVersion` carrying a report; `compatibility_report(...)` returns the same
verdict without raising; `assert_compatible(...)` raises on a failing report.

## 2. What exists today

The operator registry (`src/atlas/fec/operators.py`) contains 32 pure `Decimal` operators,
all at `atlas.fec.operators.v1`, and the compiler is `atlas.fec.compiler.v1`.
`REIMPLEMENTATIONS` and `RETIRED_OPERATORS` are empty: no operator has a second
implementation in this build and none has been removed. They exist as the only sanctioned
place to record a future re-implementation or removal; they are not a claim that such
changes have happened.

## 3. Deprecation and removal rules

1. **Never overwrite a version.** A behaviour change is a new operator version, not an edit
   to an existing one.
2. **Keep the old implementation** while any persisted model, package or application
   references it. `REIMPLEMENTATIONS[name][old] = new` records that the new implementation
   reproduces the old behaviour exactly; it requires a numerical equivalence test.
3. **Removal requires a published note.** Only then may the operator be deleted and listed
   in `RETIRED_OPERATORS` with the reason. A retired operator makes its models
   non-reproducible by design, and the report says so instead of guessing.
4. **Migration is explicit.** Re-running a saved analysis under a newer operator is a new
   computation with a new fingerprint, never an in-place upgrade of the saved result.
5. **Compiler changes are versioned** the same way; a package that names a different
   compiler version is `inspect_only`.

## 4. Where the policy is enforced

- `atlas.applications.contracts.dependency_diagnostics` — package import maps the verdict
  onto the codes saved applications already carry (`missing_operator`,
  `operator_version_conflict`, `compiler_version_mismatch`). The codes and messages are
  unchanged; resolution now goes through the compatibility module.
- `atlas.fec.compatibility.resolve_operator` — the single resolver for a recorded version.

Deliberately **not** added to the reproducibility export manifest: that document's bytes are
hashed by existing tests, and adding a field would change a published artefact for no
correctness benefit. Compatibility is queried on demand.

## 5. Tests

`tests/test_phase9_2_6_market_contract.py` covers: all current operators resolve; an unknown
operator fails closed; a version mismatch fails closed; a package declaring the current
versions produces no diagnostics; a package declaring a stale operator version is reported
as `operator_version_conflict`. Existing reproduction tests (including saved applications
and the Phase 9.1 institution package) continue to pass unchanged.

## 6. Not supported

- Automatic migration of a persisted analysis to a newer operator.
- Silent fallback when a recorded operator is missing.
- Guessing an operator's meaning from its name alone.
