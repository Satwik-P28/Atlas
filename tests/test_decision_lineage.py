"""Adversarial tests for revision lineage: replacement chains and the two clocks.

Two separate claims are tested here, because mixing them is how both previous defects survived.

**Replacement semantics.** A revision that declares ``supersedes`` carries the *corrected value*,
not an increment on top of it. Therefore exactly one revision in a replacement chain may be
applied, and it must be the operative version at the audit clock — not the root, not the whole
chain summed. The compiler resolves the chain to its single live terminal and refuses an archive
that admits more than one.

**Two clocks.** ``available_at`` is when a document became public; ``effective_at`` is when the
correction takes economic effect. Knowing is not the same as applying, but neither is it the same
as *having happened*: a revision may only enter an audit when it was public **and** effective by
the cut-off. A backdated correction published later was not knowable earlier, and a correction
published but not yet effective has not changed the data.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy", reason="the decision research layer requires the optimization extra")

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.decision.problem import mean_variance_problem  # noqa: E402
from atlas.decision.revision import (  # noqa: E402
    EvidenceRevision,
    InputSensitivity,
    compile_revisions,
)

DECISION_CLOCK = "2024-11-01T21:00:00Z"
AUDIT_CLOCK = "2024-11-05T12:00:00Z"


def problem(as_of: str = DECISION_CLOCK):
    return mean_variance_problem(
        problem_id="lineage",
        assets=["a", "b", "c"],
        expected_returns=[0.08, 0.06, 0.05],
        covariance=np.diag([0.04, 0.03, 0.02]),
        risk_aversion=3.0,
        lower=0.0,
        upper=0.8,
        budget=1.0,
        as_of=as_of,
    )


SENSITIVITY = InputSensitivity("ret_0", (-1.0, 0.0, 0.0),
                               note="declared: one unit of the input moves the first cost by -1")


def rev(revision_id: str, delta: float, *, published: str, effective: str | None = None,
        supersedes: str | None = None, status: str = "active",
        withdrawn_at: str | None = None, version: int | None = None,
        delta_semantics: str | None = None, input_key: str = "ret_0") -> EvidenceRevision:
    return EvidenceRevision(
        revision_id=revision_id,
        evidence_id=f"ev-{revision_id}",
        input_key=input_key,
        delta=delta,
        available_at=published,
        supersedes=supersedes,
        status=status,
        withdrawn_at=withdrawn_at,
        effective_at=effective,
        version=version,
        delta_semantics=delta_semantics,
        source_id="test",
    )


def compile_(revisions, *, audit: str = AUDIT_CLOCK, include_pre_decision: bool = False):
    return compile_revisions(problem(), list(revisions), [SENSITIVITY],
                             audit_as_of=audit,
                             starting_vintage="decision-vintage",
                             include_pre_decision=include_pre_decision)


def applied_ids(compilation) -> list[str]:
    return [item.revision_id for item in compilation.applied]


# --------------------------------------------------------------- replacement delta semantics
def test_a_three_deep_chain_applies_only_the_operative_version():
    """A -> B -> C must apply C alone. Applying A and C is the defect the review named."""

    revision_a = rev("A", 0.020, published="2024-11-02T00:00:00Z", version=1)
    revision_b = rev("B", 0.015, published="2024-11-03T00:00:00Z", supersedes="A", version=2)
    revision_c = rev("C", 0.010, published="2024-11-04T00:00:00Z", supersedes="B", version=3)
    compilation = compile_([revision_a, revision_b, revision_c])

    assert applied_ids(compilation) == ["C"]
    # C's delta is the corrected value. A replacement chain that summed would give 0.045.
    assert compilation.delta_cost[0] == pytest.approx(-0.010, abs=1e-12)
    assert compilation.superseded == ("A", "B")
    assert set(compilation.excluded[i]["superseded_by"] for i in range(2)) == {"C"}
    assert all(item["operative_version"] == "C" for item in compilation.excluded)


def test_a_four_deep_chain_applies_only_the_last_version():
    chain = [
        rev("v1", 0.030, published="2024-11-02T00:00:00Z", version=1),
        rev("v2", 0.025, published="2024-11-02T06:00:00Z", supersedes="v1", version=2),
        rev("v3", 0.020, published="2024-11-03T00:00:00Z", supersedes="v2", version=3),
        rev("v4", 0.015, published="2024-11-04T00:00:00Z", supersedes="v3", version=4),
    ]
    compilation = compile_(chain)
    assert applied_ids(compilation) == ["v4"]
    assert compilation.delta_cost[0] == pytest.approx(-0.015, abs=1e-12)
    assert compilation.superseded == ("v1", "v2", "v3")


def test_a_chain_never_applies_two_absolute_deltas_for_one_input():
    """The property behind the previous two tests, stated without a chain length."""

    chain = [
        rev("s0", 0.04, published="2024-11-02T00:00:00Z", version=0),
        rev("s1", 0.03, published="2024-11-02T12:00:00Z", supersedes="s0", version=1),
        rev("s2", 0.02, published="2024-11-03T00:00:00Z", supersedes="s1", version=2),
        rev("s3", 0.01, published="2024-11-04T00:00:00Z", supersedes="s2", version=3),
    ]
    compilation = compile_(chain)
    total = compilation.delta_cost[0]
    assert abs(total) <= 0.04 + 1e-12, "the applied delta is one version's value, not a sum"
    assert total == pytest.approx(-0.01, abs=1e-12)


def test_incremental_corrections_compose_additively():
    """Without ``supersedes`` the deltas are increments and are meant to sum."""

    first = rev("i1", 0.010, published="2024-11-03T00:00:00Z")
    second = rev("i2", 0.004, published="2024-11-04T00:00:00Z")
    compilation = compile_([first, second])
    assert applied_ids(compilation) == ["i1", "i2"]
    assert compilation.delta_cost[0] == pytest.approx(-0.014, abs=1e-12)


def test_a_successor_declared_incremental_is_refused():
    """An increment cannot replace a value: that combination is a double count waiting to happen."""

    root = rev("r", 0.02, published="2024-11-02T00:00:00Z", version=1)
    successor = rev("s", 0.01, published="2024-11-03T00:00:00Z", supersedes="r", version=2,
                    delta_semantics="incremental")
    with pytest.raises(ValidationError, match="absolute"):
        compile_([root, successor])


def test_an_explicit_absolute_revision_without_a_predecessor_is_allowed():
    standalone = rev("only", 0.02, published="2024-11-03T00:00:00Z", delta_semantics="absolute")
    compilation = compile_([standalone])
    assert applied_ids(compilation) == ["only"]


# ------------------------------------------------------------------ which chain nodes are live
def test_a_successor_after_the_cutoff_leaves_the_root_operative():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    future = rev("B", 0.01, published="2024-11-09T00:00:00Z", supersedes="A", version=2)
    compilation = compile_([root, future])
    assert applied_ids(compilation) == ["A"]
    assert compilation.superseded == ()
    assert compilation.excluded[0]["reason"] == "not_public_at_audit"


def test_a_middle_node_after_the_cutoff_stops_the_whole_chain_above_it():
    """If B is unpublished at the cut-off, neither B nor anything after it can replace A."""

    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    middle = rev("B", 0.015, published="2024-11-09T00:00:00Z", supersedes="A", version=2)
    later = rev("C", 0.010, published="2024-11-10T00:00:00Z", supersedes="B", version=3)
    compilation = compile_([root, middle, later])
    assert applied_ids(compilation) == ["A"]
    assert compilation.superseded == ()
    assert {item["reason"] for item in compilation.excluded} == {"not_public_at_audit"}


def test_a_withdrawn_successor_leaves_the_root_operative():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    retracted = rev("B", 0.01, published="2024-11-03T00:00:00Z", supersedes="A", version=2,
                    status="withdrawn", withdrawn_at="2024-11-04T00:00:00Z")
    compilation = compile_([root, retracted])
    assert applied_ids(compilation) == ["A"]
    assert compilation.superseded == ()
    assert compilation.withdrawn == ("B",)


def test_a_withdrawal_after_the_cutoff_leaves_the_chain_intact():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    successor = rev("B", 0.01, published="2024-11-03T00:00:00Z", supersedes="A", version=2,
                    status="withdrawn", withdrawn_at="2024-11-20T00:00:00Z")
    compilation = compile_([root, successor])
    assert applied_ids(compilation) == ["B"]
    assert compilation.superseded == ("A",)
    assert compilation.withdrawn == ()


def test_branching_replacements_are_refused_rather_than_tie_broken():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    left = rev("B", 0.015, published="2024-11-03T00:00:00Z", supersedes="A", version=2)
    right = rev("C", 0.010, published="2024-11-03T12:00:00Z", supersedes="A", version=3)
    with pytest.raises(ValidationError, match="ambiguous revision lineage"):
        compile_([root, left, right])


def test_a_withdrawn_middle_with_a_live_replacement_is_refused_as_a_double_count():
    """B was withdrawn, so A stands; C replaces B. Two absolute values for one input is a conflict.

    The compiler cannot know whether C was meant to replace A as well, so it refuses instead of
    applying both and reporting a doubled correction as an audit.
    """

    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    middle = rev("B", 0.015, published="2024-11-02T12:00:00Z", supersedes="A", version=2,
                 status="withdrawn", withdrawn_at="2024-11-03T00:00:00Z")
    replacement = rev("C", 0.010, published="2024-11-04T00:00:00Z", supersedes="B", version=3)
    with pytest.raises(ValidationError, match="absolute revision"):
        compile_([root, middle, replacement])


def test_a_longer_cycle_is_refused():
    first = rev("a", 0.02, published="2024-11-02T00:00:00Z", supersedes="c", version=1)
    second = rev("b", 0.02, published="2024-11-02T06:00:00Z", supersedes="a", version=2)
    third = rev("c", 0.02, published="2024-11-02T12:00:00Z", supersedes="b", version=3)
    with pytest.raises(ValidationError, match="cycle"):
        compile_([first, second, third])


def test_version_must_increase_along_the_chain():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=5)
    successor = rev("B", 0.01, published="2024-11-03T00:00:00Z", supersedes="A", version=5)
    with pytest.raises(ValidationError, match="strictly larger version"):
        compile_([root, successor])


# ------------------------------------------------ public availability versus effective time
def test_a_backdated_correction_cannot_enter_an_audit_before_it_is_public():
    """The review's exact case: published 2025-02-01, effective 2025-01-01, audited 2025-01-15."""

    backdated = rev("backdated", 0.02, published="2025-02-01T00:00:00Z",
                    effective="2025-01-01T00:00:00Z")
    compilation = compile_([backdated], audit="2025-01-15T00:00:00Z")
    assert compilation.applied == ()
    assert compilation.excluded[0]["reason"] == "not_public_at_audit"
    assert compilation.excluded[0]["effective_at"] == "2025-01-01T00:00:00Z"


def test_public_but_not_yet_effective_is_excluded():
    not_yet = rev("pending", 0.02, published="2024-11-02T00:00:00Z",
                  effective="2024-12-01T00:00:00Z")
    compilation = compile_([not_yet])
    assert compilation.applied == ()
    assert compilation.excluded[0]["reason"] == "not_effective_at_audit"


def test_both_conditions_are_required_at_the_decision_clock_for_the_double_count_guard():
    """Public before the decision but effective after it: not inside the vintage, so apply it."""

    pending = rev("later", 0.02, published="2024-10-15T00:00:00Z",
                  effective="2024-11-03T00:00:00Z")
    compilation = compile_([pending])
    assert applied_ids(compilation) == ["later"]
    assert compilation.incorporated == ()
    assert compilation.post_decision_revision_ids == ("later",)


def test_a_fully_incorporated_revision_is_excluded():
    old = rev("old", 0.02, published="2024-10-15T00:00:00Z",
              effective="2024-10-20T00:00:00Z")
    compilation = compile_([old])
    assert compilation.applied == ()
    assert compilation.excluded[0]["reason"] == "already_incorporated_in_decision_vintage"


def test_a_backdated_successor_cannot_suppress_before_it_is_public():
    """Supersession must use the same two conditions as eligibility, not the effective date alone."""

    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    hidden = rev("B", 0.01, published="2024-11-20T00:00:00Z", effective="2024-11-02T00:00:00Z",
                 supersedes="A", version=2)
    compilation = compile_([root, hidden])
    assert applied_ids(compilation) == ["A"], "an unreadable document cannot replace anything"
    assert compilation.superseded == ()
    assert compilation.excluded[0]["reason"] == "not_public_at_audit"


def test_a_public_successor_that_is_not_yet_effective_cannot_suppress_either():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    early = rev("B", 0.01, published="2024-11-03T00:00:00Z", effective="2024-12-01T00:00:00Z",
                supersedes="A", version=2)
    compilation = compile_([root, early])
    assert applied_ids(compilation) == ["A"]
    assert compilation.superseded == ()
    assert compilation.excluded[0]["reason"] == "not_effective_at_audit"


def test_cutoff_boundaries_are_inclusive_for_publication_and_effect():
    exactly_public = rev("on-time", 0.02, published=AUDIT_CLOCK)
    compilation = compile_([exactly_public])
    assert applied_ids(compilation) == ["on-time"]

    exactly_effective = rev("on-effect", 0.02, published="2024-11-02T00:00:00Z",
                            effective=AUDIT_CLOCK)
    second = compile_([exactly_effective])
    assert applied_ids(second) == ["on-effect"]


def test_after_hours_publication_is_not_backdated_to_the_session():
    """A 22:30 acceptance does not count for an audit run at noon the same day."""

    after_hours = rev("late", 0.02, published="2024-11-05T22:30:00Z")
    noon = compile_([after_hours], audit="2024-11-05T12:00:00Z")
    assert noon.applied == ()
    assert noon.excluded[0]["reason"] == "not_public_at_audit"

    evening = compile_([after_hours], audit="2024-11-05T23:00:00Z")
    assert applied_ids(evening) == ["late"]


def test_lineage_records_carry_the_timing_and_semantics_used_to_decide():
    root = rev("A", 0.02, published="2024-11-02T00:00:00Z", version=1)
    successor = rev("B", 0.01, published="2024-11-03T00:00:00Z", supersedes="A", version=2)
    compilation = compile_([root, successor])
    entry = next(item for item in compilation.lineage if item["revision_id"] == "A")
    assert entry["effective_at"] == "2024-11-02T00:00:00Z"
    assert entry["delta_semantics"] == "absolute", "the replaced value is absolute by definition"
    assert entry["category"] == "superseded"
    successor_entry = next(item for item in compilation.lineage
                           if item["revision_id"] == "B")
    assert successor_entry["delta_semantics"] == "absolute"
