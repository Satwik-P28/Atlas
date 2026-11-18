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
    """One correction or amendment to an input the decision model consumes.

    ``incorporated_in`` names the data vintage that already contains this correction. It is the
    difference between "this was public before the decision" and "this is actually inside the
    numbers the decision was computed from". Applying a correction twice because it happens to
    predate the audit clock is a double count, not an audit, so the compiler requires the
    lineage to be stated rather than inferred from timestamps alone.

    ``status`` distinguishes an active correction from one that was withdrawn or superseded
    before the audit: including a retracted correction in the revised program would be as wrong
    as omitting a valid one.
    """

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
    status: str = "active"
    incorporated_in: str | None = None
    #: Immutable effective-time record. ``available_at`` is when the document became public;
    #: ``effective_at`` is when the correction takes effect for the data. They default to the same
    #: instant, and when they differ the *effective* instant governs eligibility and supersession.
    effective_at: str | None = None
    #: When the correction was withdrawn, if it ever was. A withdrawal dated after the audit clock
    #: cannot un-apply a correction that was live at the cut-off.
    withdrawn_at: str | None = None
    #: Monotone version number. A successor must carry a strictly larger version than the revision
    #: it supersedes; a violation is refused rather than silently reordered.
    version: int | None = None
    #: What ``delta`` means. ``"incremental"``: add this much to the input (several may compose).
    #: ``"absolute"``: this *is* the corrected value, so it replaces any earlier one. ``None``
    #: infers: absolute when the revision declares ``supersedes``, incremental otherwise. The two
    #: are different claims and summing an absolute delta on top of the value it replaces is the
    #: double count this field exists to make impossible to express by accident.
    delta_semantics: str | None = None

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
            "status": self.status,
            "incorporated_in": self.incorporated_in,
            "effective_at": self.effective_at,
            "withdrawn_at": self.withdrawn_at,
            "version": self.version,
            "delta_semantics": self.delta_semantics or
            ("absolute" if self.supersedes else "incremental"),
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
    starting_vintage: str | None = None
    lineage: tuple[dict[str, Any], ...] = ()
    incorporated: tuple[str, ...] = ()
    superseded: tuple[str, ...] = ()
    withdrawn: tuple[str, ...] = ()

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
            "starting_vintage": self.starting_vintage,
            "lineage": [dict(item) for item in self.lineage],
            "incorporated": list(self.incorporated),
            "superseded": list(self.superseded),
            "withdrawn": list(self.withdrawn),
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
    starting_vintage: str | None = None,
    include_pre_decision: bool = False,
) -> RevisionCompilation:
    """Apply revisions public at the audit clock and exclude the rest.

    ``as_of`` overrides the decision clock (normally ``problem.as_of``). ``audit_as_of`` is when
    the audit is performed; it defaults to the decision clock, which reproduces an "audit at
    decision time" and therefore applies nothing. For a revision audit, pass the later audit
    instant explicitly.

    ``allow_future=True`` exists **only** for the leakage-contaminated diagnostic arm. It is
    never a deployable configuration, and the compilation records ``hindsight=True`` so a
    downstream certificate cannot present the result as an ex-ante audit.

    Eligibility is not the same as novelty. A correction published before the decision clock is
    already inside the vintage the decision was computed from, so applying it again double
    counts it. ``include_pre_decision=False`` (the default) therefore excludes such a revision
    with reason ``already_incorporated_in_decision_vintage``, and ``starting_vintage`` records
    which vintage the base program represents. Passing ``include_pre_decision=True`` is the
    explicit opt-in for a "the model missed evidence that was already public" experiment, which
    is a different question from an evidence revision.

    Corrections that were withdrawn or superseded *by the audit clock* are excluded, with the
    reason recorded, because a retracted correction is not part of the corrected program. Every
    revision receives exactly one lineage category, so the compiler's decisions can be audited
    without reading its control flow.

    Supersession and withdrawal are resolved **against the cut-off, not against the archive**. A
    successor that is published after the audit clock, or withdrawn before it, cannot retroactively
    erase the revision it was meant to replace: at the audit instant the earlier revision was the
    operative record. Resolution is recursive, so a chain of replacements is followed only as far
    as the cut-off allows, and a cycle cannot suppress anything. Version numbers, where supplied,
    must strictly increase along a replacement chain and a revision cannot take effect before the
    one it replaces; both are refused rather than reordered. Each revision carries an immutable
    ``effective_at`` (defaulting to ``available_at``) and, if retracted, an immutable
    ``withdrawn_at``.
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
    lineage: list[dict[str, Any]] = []
    incorporated: list[str] = []
    superseded: list[str] = []
    withdrawn: list[str] = []
    supplied_ids = {item.revision_id for item in revisions}
    by_id = {item.revision_id: item for item in revisions}

    def public_at(revision: EvidenceRevision, instant: datetime) -> bool:
        """Was the *document* public by ``instant``? Publication is when it could be known."""

        return revision.availability() <= instant

    def effective_at(revision: EvidenceRevision) -> datetime:
        """The instant the correction takes economic effect (defaults to publication)."""

        parsed = parse_instant(revision.effective_at or revision.available_at)
        assert parsed is not None
        return parsed

    def effective_by(revision: EvidenceRevision, instant: datetime) -> bool:
        return effective_at(revision) <= instant

    def eligible_at(revision: EvidenceRevision, instant: datetime) -> bool:
        """Public **and** effective by ``instant``. Both conditions, never either one.

        A revision cannot enter an audit before it became publicly available, even when its
        economic effective date is earlier: a backdated correction whose document appears later was
        not knowable earlier, so applying it is a look-ahead leak. Conversely a revision that is
        public but not yet effective has not changed the data at the clock, so it is not applied
        either. An earlier version used ``effective_at or available_at`` as the sole test, which
        made a backdated but unpublished correction eligible, and the same flaw leaked into
        supersession: a successor nobody could have read yet could suppress its predecessor.
        """

        return public_at(revision, instant) and effective_by(revision, instant)

    def withdrawn_at_audit(revision: EvidenceRevision) -> bool:
        """Was this revision withdrawn *by the audit clock*?"""

        if revision.status != "withdrawn":
            return False
        if revision.withdrawn_at is None:
            return True
        stamp = parse_instant(revision.withdrawn_at)
        return bool(stamp is not None and stamp <= audit_instant)

    successors: dict[str, list[EvidenceRevision]] = {}
    for item in revisions:
        if item.supersedes and item.supersedes != item.revision_id:
            successors.setdefault(item.supersedes, []).append(item)

    def _walk(node: str, path: tuple[str, ...] = ()) -> None:
        if node in path:
            raise ValidationError("a supersedes chain forms a cycle; version lineage must be a "
                                  "directed acyclic graph", chain=[*path, node])
        for candidate in successors.get(node, []):
            _walk(candidate.revision_id, (*path, node))

    for start in list(successors):
        _walk(start)

    # Version ordering is an invariant of the record, not a preference: check every declared
    # replacement once, before any temporal filtering, so an inconsistent archive is refused even
    # when the cut-off would have hidden the inconsistency.
    for predecessor_id, candidates in successors.items():
        predecessor = by_id.get(predecessor_id)
        if predecessor is None:
            continue
        for candidate in candidates:
            if (candidate.version is not None and predecessor.version is not None
                    and candidate.version <= predecessor.version):
                raise ValidationError(
                    "a superseding revision must carry a strictly larger version",
                    predecessor=predecessor_id, predecessor_version=predecessor.version,
                    successor=candidate.revision_id, successor_version=candidate.version,
                )
            if effective_at(candidate) < effective_at(predecessor):
                raise ValidationError(
                    "a superseding revision cannot take effect before the revision it replaces",
                    predecessor=predecessor_id, successor=candidate.revision_id,
                )
            semantics = candidate.delta_semantics or "absolute"
            if semantics != "absolute":
                raise ValidationError(
                    "a revision that supersedes another must declare absolute (replacement) delta "
                    "semantics: an incremental delta would be added on top of the value it "
                    "replaces, counting the correction twice",
                    predecessor=predecessor_id, successor=candidate.revision_id,
                    delta_semantics=semantics,
                )

    def is_live(revision: EvidenceRevision) -> bool:
        """Operative at the audit clock: not withdrawn, public, and effective."""

        return not withdrawn_at_audit(revision) and eligible_at(revision, audit_instant)

    terminal_cache: dict[str, tuple[str, ...]] = {}

    def terminals(revision_id: str) -> tuple[str, ...]:
        """The operative version(s) at the end of a replacement chain, at the audit clock.

        A revision is followed only through *live* successors, so a successor that is not public,
        not yet effective, or withdrawn by the cut-off replaces nothing. Every ancestor of a live
        terminal is superseded — including the nodes in the middle of a chain. An earlier version
        asked whether a successor was *itself terminal*, which made ``A -> B -> C`` skip B for A
        and leave both A and C applied: a doubled replacement delta reported as an audit.

        The result is a tuple because an archive can contradict itself; the caller refuses an
        ambiguous branch instead of resolving it with an arbitrary tie-break.
        """

        if revision_id in terminal_cache:
            return terminal_cache[revision_id]
        live_children = [item for item in successors.get(revision_id, []) if is_live(item)]
        if not live_children:
            terminal_cache[revision_id] = (revision_id,)
            return terminal_cache[revision_id]
        found: list[str] = []
        for child in live_children:
            for term in terminals(child.revision_id):
                if term not in found:
                    found.append(term)
        terminal_cache[revision_id] = tuple(sorted(found))
        return terminal_cache[revision_id]

    superseded_by: dict[str, str] = {}
    for revision in revisions:
        resolved = terminals(revision.revision_id)
        if len(resolved) > 1:
            raise ValidationError(
                "ambiguous revision lineage: more than one live successor replaces this revision "
                "and none supersedes the others, so the operative version is undetermined",
                revision_id=revision.revision_id, operative_candidates=list(resolved),
            )
        if resolved and resolved != (revision.revision_id,):
            superseded_by[revision.revision_id] = resolved[0]
    superseded_ids = set(superseded_by)
    pending_successor_ids = {
        predecessor for predecessor in successors
        if predecessor in supplied_ids and predecessor not in superseded_ids
    }

    def semantics_of(revision: EvidenceRevision) -> str:
        """What this revision's ``delta`` claims, resolving the default.

        A revision that is *replaced* carries an absolute value even when it does not itself
        declare ``supersedes``: being the thing a successor replaces is what makes its delta the
        corrected value rather than an increment. Inferring only from the revision's own field made
        the root of a chain look incremental and hid a two-absolute-revision conflict.
        """

        if revision.delta_semantics:
            return revision.delta_semantics
        if revision.supersedes or revision.revision_id in successors:
            return "absolute"
        return "incremental"

    def record(revision: EvidenceRevision, category: str, included: bool, reason: str | None,
               detail: str) -> None:
        lineage.append({
            "revision_id": revision.revision_id,
            "evidence_id": revision.evidence_id,
            "input_key": revision.input_key,
            "available_at": revision.available_at,
            "effective_at": revision.effective_at or revision.available_at,
            "withdrawn_at": revision.withdrawn_at,
            "version": revision.version,
            "delta_semantics": semantics_of(revision),
            "status": revision.status,
            "incorporated_in": revision.incorporated_in,
            "category": category,
            "included_in_revision": included,
            "reason": reason,
            "detail": detail,
        })

    for revision in revisions:
        if revision.kind not in SUPPORTED_KINDS:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "unsupported_perturbation_kind",
                "kind": revision.kind,
                "detail": "only linear objective perturbations are compiled; a risk-matrix "
                          "revision is a different mathematical object",
            })
            record(revision, "unsupported_kind", False, "unsupported_perturbation_kind",
                   "a risk-matrix revision is a different mathematical object")
            continue
        if withdrawn_at_audit(revision):
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "withdrawn_before_audit",
                "available_at": revision.available_at,
                "withdrawn_at": revision.withdrawn_at,
                "audit_as_of": audit_clock,
                "detail": "the correction was retracted before the audit clock; a retracted "
                          "correction is not part of the corrected program",
            })
            withdrawn.append(revision.revision_id)
            record(revision, "withdrawn", False, "withdrawn_before_audit",
                   "retracted on or before the audit clock")
            continue
        if revision.revision_id in superseded_ids:
            replacement = superseded_by[revision.revision_id]
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "superseded_before_audit",
                "superseded_by": replacement,
                "audit_as_of": audit_clock,
                "operative_version": replacement,
                "detail": "a later revision, itself public and effective at the audit clock, "
                          "replaces this one; only the operative version's delta is applied",
            })
            superseded.append(revision.revision_id)
            record(revision, "superseded", False, "superseded_before_audit",
                   f"replaced by {replacement}, which was public and effective by the audit clock")
            continue
        if not public_at(revision, audit_instant) and not allow_future:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": ("not_public_at_decision" if audit_instant == decision_instant
                           else "not_public_at_audit"),
                "available_at": revision.available_at,
                "effective_at": revision.effective_at,
                "decision_as_of": clock,
                "audit_as_of": audit_clock,
                "detail": "the document was not public at the audit clock; an economic effective "
                          "date cannot make a document knowable, so applying it would be a "
                          "hindsight computation",
            })
            record(revision, "published_after_audit", False, "not_public_at_audit",
                   "not public at the audit clock")
            continue
        if not effective_by(revision, audit_instant) and not allow_future:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": ("not_effective_at_decision" if audit_instant == decision_instant
                           else "not_effective_at_audit"),
                "available_at": revision.available_at,
                "effective_at": revision.effective_at or revision.available_at,
                "audit_as_of": audit_clock,
                "detail": "the correction was public but had not taken economic effect at the "
                          "audit clock; the data it would change had not changed yet",
            })
            record(revision, "published_before_effective", False, "not_effective_at_audit",
                   "public but not yet effective at the audit clock")
            continue
        if eligible_at(revision, decision_instant) and not include_pre_decision:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "already_incorporated_in_decision_vintage",
                "available_at": revision.available_at,
                "effective_at": revision.effective_at or revision.available_at,
                "decision_as_of": clock,
                "starting_vintage": starting_vintage,
                "detail": "the correction was public before the decision clock, so the base "
                          "program already reflects it; applying it again would double count",
            })
            incorporated.append(revision.revision_id)
            record(revision, "incorporated_before_decision", False,
                   "already_incorporated_in_decision_vintage",
                   "public before the decision clock; already inside the base vintage")
            continue
        sensitivity = sensitivity_by_key.get(revision.input_key)
        if sensitivity is None:
            excluded.append({
                "revision_id": revision.revision_id,
                "reason": "no_declared_sensitivity",
                "input_key": revision.input_key,
                "detail": "no declared mapping from this input to the objective coefficients",
            })
            record(revision, "unmapped", False, "no_declared_sensitivity",
                   "no declared mapping to objective coefficients")
            continue
        effect = np.asarray(sensitivity.cost_effect, dtype=float)
        if effect.shape != (n,):
            raise ValidationError("sensitivity effect must match problem dimension",
                                  input_key=revision.input_key, expected=n, received=int(effect.size))
        delta_cost = delta_cost + float(revision.delta) * effect
        applied.append(revision)
        if not eligible_at(revision, decision_instant):
            post_decision.append(revision.revision_id)
        record(revision, "published_after_decision"
               if not eligible_at(revision, decision_instant)
               else "pre_decision_explicitly_included", True, None,
               "applied to the corrected program")
    dangling = {item.supersedes for item in revisions
                if item.supersedes and item.supersedes not in supplied_ids
                and item.supersedes != item.revision_id}
    if dangling:
        notes.append(
            f"{len(dangling)} 'supersedes' reference(s) point outside the supplied revision set; "
            "the predecessor was not compiled and nothing was suppressed"
        )
    for predecessor in pending_successor_ids:
        replacement = successors[predecessor][0]
        notes.append(
            f"revision {predecessor} has a declared successor {replacement.revision_id} that is "
            "not effective at the audit clock; the earlier revision stands"
        )

    # One operative absolute revision per input. Two of them would each claim to *be* the corrected
    # value, so summing them double counts — the failure mode a broken chain produces. Incremental
    # corrections are additive by construction and may share an input freely.
    absolute_by_input: dict[str, list[str]] = {}
    for revision in applied:
        if semantics_of(revision) == "absolute":
            absolute_by_input.setdefault(revision.input_key, []).append(revision.revision_id)
    conflicts = {key: ids for key, ids in absolute_by_input.items() if len(ids) > 1}
    if conflicts:
        raise ValidationError(
            "more than one operative absolute revision for the same input; their deltas are "
            "alternatives, not increments, so applying both would double count",
            input_keys=sorted(conflicts), revisions=conflicts,
        )

    if allow_future:
        future_reasons = {"not_public_at_decision", "not_public_at_audit",
                          "not_effective_at_decision", "not_effective_at_audit"}
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
        starting_vintage=starting_vintage,
        lineage=tuple(lineage),
        incorporated=tuple(incorporated),
        superseded=tuple(superseded),
        withdrawn=tuple(withdrawn),
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
