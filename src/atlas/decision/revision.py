"""Compile an evidence revision into an explicit perturbation of a decision problem.

This module is where provenance becomes mathematics. A revision is not a number that
"changes the forecast"; it is an event with a *public availability instant*, an identity, and
a declared effect on the objective coefficients. Two things follow, and they are the whole
point of the module:

1. A revision whose availability instant is later than the decision's ``as_of`` clock cannot
   have influenced that decision. It is excluded, with a reason, and the exclusion is
   recorded rather than silently applied. Applying it would be a hindsight computation.
2. The perturbation is *declared*, not estimated. The mapping from an input change to an
   objective-coefficient change is a linear sensitivity supplied by the caller. The
   certificate's guarantee is conditional on that declaration, and the report says so.

Covariance revisions are deliberately **not** compiled here. A change to the risk matrix
changes the geometry of the problem, and pretending a linear cost perturbation covers it
would be a silent substitution of a different mathematical object. Such a revision returns
``status="unsupported_perturbation_kind"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import numpy as np

from ..core.errors import ValidationError
from .problem import ConvexDecisionProblem

REVISION_SCHEMA = "atlas.decision.evidence_revision.v1"
COMPILATION_SCHEMA = "atlas.decision.revision_compilation.v1"
SENSITIVITY_SCHEMA = "atlas.decision.input_sensitivity.v1"

#: Kinds of perturbation a revision may declare. Anything else is refused explicitly.
SUPPORTED_KINDS = ("linear_objective",)


def parse_instant(value: str | None) -> datetime | None:
    """Parse an ISO-8601 instant, treating a missing zone as UTC.

    Atlas stores evidence instants as UTC with a ``Z`` suffix. A naive timestamp is accepted
    as UTC because the temporal evidence kernel already normalises to UTC; it is never
    interpreted in local time, which would shift an after-hours filing into the prior
    session.
    """

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("an instant must be a non-empty ISO-8601 string", value=value)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError("invalid ISO-8601 instant", value=value) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class EvidenceRevision:
    """One correction or amendment to an input the decision model consumes."""

    revision_id: str
    evidence_id: str
    input_key: str
    delta: float
    available_at: str
    kind: str = "linear_objective"
    supersedes: str | None = None
    amendment: bool = True
    source_id: str = ""
    note: str = ""

    def availability(self) -> datetime:
        parsed = parse_instant(self.available_at)
        assert parsed is not None
        return parsed

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": REVISION_SCHEMA,
            "revision_id": self.revision_id,
            "evidence_id": self.evidence_id,
            "input_key": self.input_key,
            "delta": float(self.delta),
            "available_at": self.available_at,
            "kind": self.kind,
            "supersedes": self.supersedes,
            "amendment": self.amendment,
            "source_id": self.source_id,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class InputSensitivity:
    """Declared linear effect of one input on the objective coefficients.

    ``cost_effect[i]`` is ``d(c_i)/d(input)``. For a mean-variance portfolio built by
    :func:`atlas.decision.problem.mean_variance_problem` the objective cost is ``c = -mu``,
    so an input that raises asset ``i``'s expected return by one unit has ``cost_effect[i] =
    -1``. The declaration is a modelling assumption; a misspecified sensitivity breaks the
    guarantee, which is measured directly in the failure experiments.
    """

    input_key: str
    cost_effect: tuple[float, ...]
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SENSITIVITY_SCHEMA,
            "input_key": self.input_key,
            "cost_effect": [float(v) for v in self.cost_effect],
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class RevisionCompilation:
    """The perturbed problem plus an auditable account of what was applied and excluded.

    Two clocks are recorded, because a revision audit is a statement about a *past* decision
    evaluated with *present* evidence:

    ``decision_as_of``  when the decision was taken; evidence later than this could not have
                        influenced it.
    ``audit_as_of``     when the audit is run; evidence later than this cannot be used even in
                        the corrected program.

    Collapsing the two clocks is a real error: it either excludes the very revisions the audit
    exists to evaluate, or lets a not-yet-public revision into the corrected program.
    """

    status: str
    decision_as_of: str | None
    problem: ConvexDecisionProblem
    applied: tuple[EvidenceRevision, ...] = ()
    excluded: tuple[dict[str, Any], ...] = ()
    delta_cost: tuple[float, ...] = ()
    hindsight: bool = False
    notes: tuple[str, ...] = ()
    audit_as_of: str | None = None
    post_decision_revision_ids: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any(abs(value) > 0.0 for value in self.delta_cost)

    @property
    def magnitude(self) -> float:
        return float(np.linalg.norm(np.asarray(self.delta_cost, dtype=float))) if self.delta_cost else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPILATION_SCHEMA,
            "status": self.status,
            "decision_as_of": self.decision_as_of,
            "applied": [revision.as_dict() for revision in self.applied],
            "excluded": [dict(item) for item in self.excluded],
            "delta_cost": [float(v) for v in self.delta_cost],
            "delta_cost_l2": self.magnitude,
            "changed": self.changed,
            "hindsight": self.hindsight,
            "notes": list(self.notes),
            "audit_as_of": self.audit_as_of,
            "post_decision_revision_ids": list(self.post_decision_revision_ids),
            "perturbed_problem_digest": self.problem.digest(),
        }


def compile_revisions(
    problem: ConvexDecisionProblem,
    revisions: Sequence[EvidenceRevision],
    sensitivities: Sequence[InputSensitivity],
    *,
    as_of: str | None = None,
    audit_as_of: str | None = None,
    allow_future: bool = False,
) -> RevisionCompilation:
    """Apply revisions public at the audit clock and exclude the rest.

    ``as_of`` overrides the decision clock (normally ``problem.as_of``). ``audit_as_of`` is when
    the audit is performed; it defaults to the decision clock, which reproduces an "audit at
    decision time" and therefore applies nothing. For a revision audit, pass the later audit
    instant explicitly.

    ``allow_future=True`` exists **only** for the leakage-contaminated diagnostic arm. It is
    never a deployable configuration, and the compilation records ``hindsight=True`` so a
    downstream certificate cannot present the result as an ex-ante audit.
    """

    clock = as_of if as_of is not None else problem.as_of
    if clock is None:
        return RevisionCompilation(
            status="no_decision_clock",
            decision_as_of=None,
            problem=problem,
            delta_cost=tuple(0.0 for _ in range(problem.dimension)),
            audit_as_of=audit_as_of,
            notes=(
                "no as_of clock is recorded for the decision; revision eligibility cannot be "
                "established and no perturbation is applied",
            ),
        )
    decision_instant = parse_instant(clock)
    assert decision_instant is not None
    audit_clock = audit_as_of if audit_as_of is not None else clock
    audit_instant = parse_instant(audit_clock)
    assert audit_instant is not None
    if audit_instant < decision_instant:
        raise ValidationError("the audit clock cannot precede the decision clock",
                              decision_as_of=clock, audit_as_of=audit_clock)
    sensitivity_by_key = {item.input_key: item for item in sensitivities}
    n = problem.dimension
    delta_cost = np.zeros(n)
    applied: list[EvidenceRevision] = []
    excluded: list[dict[str, Any]] = []
    notes: list[str] = []
    post_decision: list[str] = []

    for revision in revisions:
        if revision.kind not in SUPPORTED_KINDS:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "unsupported_perturbation_kind",
                "kind": revision.kind,
                "detail": "only linear objective perturbations are compiled; a risk-matrix "
                          "revision is a different mathematical object",
            })
            continue
        available = revision.availability()
        if available > audit_instant and not allow_future:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": ("not_available_at_decision" if audit_instant == decision_instant
                           else "not_available_at_audit"),
                "available_at": revision.available_at,
                "decision_as_of": clock,
                "audit_as_of": audit_clock,
                "detail": "the revision was not public at the audit clock; applying it would "
                          "be a hindsight computation",
            })
            continue
        sensitivity = sensitivity_by_key.get(revision.input_key)
        if sensitivity is None:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "no_declared_sensitivity",
                "input_key": revision.input_key,
                "detail": "no declared mapping from this input to the objective coefficients",
            })
            continue
        effect = np.asarray(sensitivity.cost_effect, dtype=float)
        if effect.shape != (n,):
            raise ValidationError("sensitivity effect must match problem dimension",
                                  input_key=revision.input_key, expected=n, received=int(effect.size))
        delta_cost = delta_cost + float(revision.delta) * effect
        applied.append(revision)
        if available > decision_instant:
            post_decision.append(revision.revision_id)

    if allow_future:
        future_reasons = {"not_available_at_decision", "not_available_at_audit"}
        leaked = [item for item in excluded if item["reason"] in future_reasons]
        notes.append(
            "HINDSIGHT DIAGNOSTIC: revisions not public at the clock were applied. "
            "This arm is leakage-contaminated and must never be reported as an ex-ante result."
        )
        excluded = [item for item in excluded if item["reason"] not in future_reasons]
        # Re-run the application for the leaked revisions so the arm is genuinely contaminated.
        for item in leaked:
            revision = next(r for r in revisions if r.revision_id == item["revision_id"])
            sensitivity = sensitivity_by_key.get(revision.input_key)
            if sensitivity is None:
                continue
            delta_cost = delta_cost + float(revision.delta) * np.asarray(sensitivity.cost_effect, dtype=float)
            applied.append(revision)
            post_decision.append(revision.revision_id)

    if delta_cost.any():
        perturbed = problem.replace(
            problem_id=f"{problem.problem_id}::revised",
            linear_costs=tuple(float(v) for v in problem.cost_vector() + delta_cost),
            as_of=audit_clock,
            labels={**problem.labels, "perturbation": "evidence_revision"},
        )
        status = "applied"
    else:
        perturbed = problem
        status = "no_material_change"
        if not applied and not excluded:
            notes.append("no revisions were supplied")

    if excluded:
        notes.append(f"{len(excluded)} revision(s) excluded from the decision-time program")
    return RevisionCompilation(
        status=status,
        decision_as_of=clock,
        problem=perturbed,
        applied=tuple(applied),
        excluded=tuple(excluded),
        delta_cost=tuple(float(v) for v in delta_cost),
        hindsight=allow_future,
        notes=tuple(notes),
        audit_as_of=audit_clock,
        post_decision_revision_ids=tuple(post_decision),
    )


def directional_perturbation(
    problem: ConvexDecisionProblem,
    direction: Sequence[float],
    radius: float,
) -> ConvexDecisionProblem:
    """``c(r) = c + r * direction``: the one-parameter family used by the stability radius.

    The stability radius is only meaningful along a declared direction, so the direction is
    always an explicit argument rather than an internal choice.
    """

    d = np.asarray(direction, dtype=float)
    if d.shape != (problem.dimension,):
        raise ValidationError("direction must match problem dimension",
                              expected=problem.dimension, received=int(d.size))
    if not np.all(np.isfinite(d)):
        raise ValidationError("direction must be finite")
    if radius < 0 or not np.isfinite(radius):
        raise ValidationError("radius must be finite and non-negative", radius=radius)
    return problem.replace(
        linear_costs=tuple(float(v) for v in problem.cost_vector() + float(radius) * d),
        labels={**problem.labels, "perturbation": f"directional@{radius:.6g}"},
    )


def revision_set_magnitude(revisions: Iterable[EvidenceRevision]) -> float:
    values = [abs(float(item.delta)) for item in revisions]
    return float(np.linalg.norm(values)) if values else 0.0


__all__ = [
    "COMPILATION_SCHEMA",
    "REVISION_SCHEMA",
    "SENSITIVITY_SCHEMA",
    "SUPPORTED_KINDS",
    "EvidenceRevision",
    "InputSensitivity",
    "RevisionCompilation",
    "compile_revisions",
    "directional_perturbation",
    "parse_instant",
    "revision_set_magnitude",
]
