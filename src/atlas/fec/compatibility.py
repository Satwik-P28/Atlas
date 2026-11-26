"""Operator and model-version compatibility for persisted analyses.

A saved research object records the compiler and operator versions that produced it. Those
records are meaningful only if a later run resolves every operator to the *same* meaning.
Reinterpreting an old node with a newer implementation would silently change a stored
result, so resolution is explicit and fails closed:

* an operator that is no longer registered is ``retired_operator``;
* a registered operator whose implementation version differs is
  ``operator_version_mismatch``;
* a compiler version mismatch is ``compiler_version_mismatch``.

The current cipher space has one implementation version per operator
(``OPERATOR_VERSION``); the mapping below exists so a future re-implementation adds a
compatibility entry instead of overwriting behaviour. Nothing here reinterprets a
historical model: a mismatch is reported, never repaired.
"""

from __future__ import annotations

from typing import Any, Mapping

from .compiler import COMPILER_VERSION
from .operators import OPERATOR_VERSION, REGISTRY, operator_versions

COMPATIBILITY_SCHEMA = "atlas.model_compatibility.v1"

#: Operators whose behaviour was reimplemented under the same name. Each entry maps the
#: historical version to the version that reproduces it. Empty today: no operator has a
#: second implementation, and inventing one would be a claim this build cannot support.
REIMPLEMENTATIONS: dict[str, dict[str, str]] = {}

#: Operators that were removed and whose models can no longer be reproduced. An entry is
#: published here only when the removal is real and documented.
RETIRED_OPERATORS: dict[str, str] = {}

STATUS_COMPATIBLE = "compatible"
STATUS_COMPILER_MISMATCH = "compiler_version_mismatch"
STATUS_OPERATOR_MISMATCH = "operator_version_mismatch"
STATUS_RETIRED = "retired_operator"
STATUS_UNKNOWN = "unknown_operator"


class IncompatibleModelVersion(ValueError):
    """A persisted model cannot be reproduced with the operators in this build."""

    def __init__(self, message: str, *, report: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = dict(report or {})


def supported_operator_versions() -> dict[str, str]:
    return operator_versions()


def resolve_operator(name: str, version: str) -> Any:
    """Return the registered operator that reproduces ``version``, or fail closed."""
    spec = REGISTRY.get(name)
    if spec is None:
        raise IncompatibleModelVersion(
            f"operator {name!r} is not registered in this build; its models cannot be reproduced",
            report={"status": STATUS_UNKNOWN, "operator": name, "requested_version": version},
        )
    if spec.version == version:
        return spec
    replacement = REIMPLEMENTATIONS.get(name, {}).get(version)
    if replacement and REGISTRY[name].version == replacement:
        return spec
    raise IncompatibleModelVersion(
        f"operator {name!r} is at version {spec.version!r}, but the analysis recorded "
        f"{version!r}; reinterpreting it would change a stored result",
        report={
            "status": STATUS_OPERATOR_MISMATCH,
            "operator": name,
            "requested_version": version,
            "available_version": spec.version,
        },
    )


def compatibility_report(
    *,
    compiler_version: str | None,
    operators: Mapping[str, str] | None,
    model_version: str | None = None,
) -> dict[str, Any]:
    """Report whether a persisted analysis resolves against this build."""
    mismatches: list[dict[str, Any]] = []
    if compiler_version and compiler_version != COMPILER_VERSION:
        mismatches.append(
            {
                "status": STATUS_COMPILER_MISMATCH,
                "recorded": compiler_version,
                "available": COMPILER_VERSION,
            }
        )
    checked = 0
    for name, version in sorted((operators or {}).items()):
        if name in RETIRED_OPERATORS:
            mismatches.append(
                {
                    "status": STATUS_RETIRED,
                    "operator": name,
                    "requested_version": version,
                    "detail": RETIRED_OPERATORS[name],
                }
            )
            continue
        spec = REGISTRY.get(name)
        if spec is None:
            mismatches.append(
                {
                    "status": STATUS_UNKNOWN,
                    "operator": name,
                    "requested_version": version,
                }
            )
            continue
        checked += 1
        allowed = {spec.version} | {
            historical for historical, replacement in REIMPLEMENTATIONS.get(name, {}).items()
            if replacement == spec.version
        }
        if version not in allowed:
            mismatches.append(
                {
                    "status": STATUS_OPERATOR_MISMATCH,
                    "operator": name,
                    "requested_version": version,
                    "available_version": spec.version,
                }
            )
    return {
        "schema": COMPATIBILITY_SCHEMA,
        "status": STATUS_COMPATIBLE if not mismatches else mismatches[0]["status"],
        "compatible": not mismatches,
        "model_version": model_version,
        "compiler_version": {"recorded": compiler_version, "available": COMPILER_VERSION},
        "operator_build_version": OPERATOR_VERSION,
        "operators_checked": checked,
        "mismatches": mismatches,
        "policy": (
            "A persisted model is reproduced only when every recorded operator resolves to "
            "the implementation that produced it. A mismatch is reported, never repaired by "
            "substituting the current implementation."
        ),
    }


def assert_compatible(report: Mapping[str, Any], *, what: str = "saved model") -> Mapping[str, Any]:
    if report.get("compatible"):
        return report
    raise IncompatibleModelVersion(
        f"{what} cannot be reproduced with this build: {report.get('status')}",
        report=report,
    )


__all__ = [
    "COMPATIBILITY_SCHEMA",
    "REIMPLEMENTATIONS",
    "RETIRED_OPERATORS",
    "IncompatibleModelVersion",
    "compatibility_report",
    "assert_compatible",
    "resolve_operator",
    "supported_operator_versions",
]
