"""Adversarial tests for revision identity, delta semantics and incorporation status.

Three separate claims, because conflating them is how the defects this file pins down survived a
previous pass.

**Identity.** A ``revision_id`` is an immutable event identity. Two records sharing one id are
either the same event supplied twice — which applies its correction twice — or two different events
claiming one identity, which means nothing. Both are refused before any arithmetic, so no caller can
observe a silently deduplicated or silently doubled correction. The same applies to a duplicate
sensitivity declaration for one input: there is no composition rule for two mappings, so choosing
one silently would change the arithmetic without changing the record.

**Semantics.** ``incremental`` deltas are additions and compose commutatively; ``absolute`` deltas are
the total correction relative to the frozen baseline at ``starting_vintage`` and replace rather than
compose. One input may carry increments or a single absolute, never both: the two are relative to
different bases, so their sum is not a number the model defines. The refusal is the point — an
ambiguous mixture that produced a plausible number would be worse than an error.

**Incorporation.** Being public before the decision clock does not establish that the decision's
inputs contained the correction; a frozen source vintage can omit a public document. Only an
incorporation record settles it, so the compiler distinguishes documented incorporation, documented
exclusion and an explicit assumption, and says which one it used.
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

DECISION_CLOCK = "2025-01-15T12:00:00Z"
AUDIT_CLOCK = "2025-02-10T12:00:00Z"
BEFORE_DECISION = "2025-01-05T00:00:00Z"
AFTER_DECISION = "2025-02-01T00:00:00Z"
VINTAGE = "frozen-2024Q4"


def problem(as_of: str = DECISION_CLOCK):
    return mean_variance_problem(
        problem_id="identity",
        assets=["a", "b", "c"],
        expected_returns=[0.08, 0.06, 0.05],
        covariance=np.diag([0.04, 0.03, 0.02]),
        risk_aversion=3.0,
        lower=0.0,
        upper=0.8,
        budget=1.0,
        as_of=as_of,
    )


SENSITIVITY = InputSensitivity("ret_0", (-1.0, 0.0, 0.0))
OTHER_SENSITIVITY = InputSensitivity("ret_1", (0.0, -1.0, 0.0))


def rev(revision_id: str, delta: float, *, evidence_id: str | None = None,
        published: str = AFTER_DECISION, input_key: str = "ret_0",
        supersedes: str | None = None, delta_semantics: str | None = None,
        incorporation: str | None = None, incorporated_in: str | None = None,
        version: int | None = None) -> EvidenceRevision:
    return EvidenceRevision(
        revision_id=revision_id,
        evidence_id=evidence_id or f"ev-{revision_id}",
        input_key=input_key,
        delta=delta,
        available_at=published,
        supersedes=supersedes,
        delta_semantics=delta_semantics,
        incorporation=incorporation,
        incorporated_in=incorporated_in,
        version=version,
    )


def compile_set(revisions, *, sensitivities=(SENSITIVITY,), starting_vintage=VINTAGE,
                audit: str = AUDIT_CLOCK):
    return compile_revisions(problem(), revisions, list(sensitivities),
                             audit_as_of=audit, starting_vintage=starting_vintage)


# ------------------------------------------------------------------ identity: duplicates refused
def test_identical_duplicate_revision_is_refused_rather_than_applied_once():
    single = rev("r1", 0.010)
    with pytest.raises(ValidationError) as caught:
        compile_set([single, single])
    message = str(caught.value)
    assert "duplicate revision_id" in message
    assert "twice" in message
    payload = caught.value.context if hasattr(caught.value, "context") else {}
    detail = payload.get("duplicates", {}).get("r1", {})
    assert detail.get("conflicting") is False or detail.get("identical_payload") is True


def test_duplicate_revision_cannot_double_count_incremental_deltas():
    """The exact failure the review demonstrated: one id, two additions."""
    first = rev("r1", 0.010)
    second = rev("r1", 0.010)
    with pytest.raises(ValidationError):
        compile_set([first, second])


def test_conflicting_duplicate_payload_is_refused_and_reports_the_field():
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("r1", 0.010), rev("r1", 0.020)])
    message = str(caught.value)
    assert "conflicting" in message
    detail = getattr(caught.value, "context", {}).get("duplicates", {})
    if detail:
        assert detail["r1"]["conflicting_fields"] == ["delta"]
        assert detail["r1"]["identical_payload"] is False


def test_duplicate_identity_report_is_order_independent():
    a, b = rev("r1", 0.010), rev("r1", 0.020, evidence_id="ev-other")
    with pytest.raises(ValidationError) as first:
        compile_set([a, b])
    with pytest.raises(ValidationError) as second:
        compile_set([b, a])
    assert str(first.value) == str(second.value)
    assert getattr(first.value, "context", {}).get("duplicates") == \
        getattr(second.value, "context", {}).get("duplicates")


def test_duplicate_id_across_different_inputs_is_refused():
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("r1", 0.01, input_key="ret_0"),
                     rev("r1", 0.02, input_key="ret_1")],
                    sensitivities=(SENSITIVITY, OTHER_SENSITIVITY))
    assert "conflicting" in str(caught.value)


def test_duplicate_identity_in_a_supersession_chain_is_refused():
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("A", 0.01),
                     rev("B", 0.02, supersedes="A", delta_semantics="absolute"),
                     rev("B", 0.02, supersedes="A", delta_semantics="absolute")])
    assert "duplicate revision_id" in str(caught.value)


def test_duplicate_sensitivity_for_one_input_is_refused():
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("r1", 0.01)], sensitivities=(SENSITIVITY, SENSITIVITY))
    assert "duplicate sensitivity" in str(caught.value)


def test_conflicting_sensitivity_for_one_input_is_refused():
    conflicting = InputSensitivity("ret_0", (-2.0, 0.0, 0.0))
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("r1", 0.01)], sensitivities=(SENSITIVITY, conflicting))
    assert "conflicting sensitivity" in str(caught.value)


# ------------------------------------------------------- semantics: composition and replacement
def test_increments_compose_by_addition_and_do_not_depend_on_order():
    revision_a = rev("a", 0.020, delta_semantics="incremental")
    revision_b = rev("b", 0.030, delta_semantics="incremental")
    forward = compile_set([revision_a, revision_b])
    backward = compile_set([revision_b, revision_a])
    assert forward.applied and backward.applied
    # c[0] = -mu[0], so a positive input delta lowers the first cost by 0.050 in total.
    assert np.isclose(forward.delta_cost[0], -0.050)
    assert np.allclose(forward.delta_cost, backward.delta_cost)
    assert dict(forward.correction_semantics) == {"ret_0": "incremental"}


def test_a_lone_absolute_revision_is_the_total_correction_not_an_accumulation():
    revision = rev("a", 0.010, delta_semantics="absolute")
    compiled = compile_set([revision])
    assert np.isclose(compiled.delta_cost[0], -0.010)
    assert dict(compiled.correction_semantics) == {"ret_0": "absolute"}


def test_absolute_and_increment_on_one_input_are_refused_not_summed():
    """+2 incremental then an absolute correction is unambiguous nonsense; refuse it."""
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("inc", 0.002, delta_semantics="incremental"),
                     rev("abs", 0.005, delta_semantics="absolute")])
    message = str(caught.value)
    assert "absolute" in message and "increment" in message
    assert "different bases" in message


def test_two_absolute_revisions_for_one_input_are_refused():
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("abs1", 0.004, delta_semantics="absolute"),
                     rev("abs2", 0.006, delta_semantics="absolute")])
    assert "alternatives, not increments" in str(caught.value)


def test_an_absolute_revision_requires_a_baseline_vintage():
    with pytest.raises(ValidationError) as caught:
        compile_set([rev("abs", 0.004, delta_semantics="absolute")], starting_vintage=None)
    assert "baseline" in str(caught.value)


def test_absolute_on_one_input_and_increment_on_another_compose():
    compiled = compile_set(
        [rev("abs", 0.004, delta_semantics="absolute"),
         rev("inc", 0.002, input_key="ret_1", delta_semantics="incremental")],
        sensitivities=(SENSITIVITY, OTHER_SENSITIVITY),
    )
    assert np.isclose(compiled.delta_cost[0], -0.004)
    assert np.isclose(compiled.delta_cost[1], -0.002)
    assert dict(compiled.correction_semantics) == {"ret_0": "absolute", "ret_1": "incremental"}


def test_a_correction_replaced_by_an_absolute_successor_does_not_mix_with_it():
    """Before and after a replacement: the earlier increment is replaced, not added to."""
    earlier = rev("old", 0.030, delta_semantics="incremental",
                  published="2025-02-01T00:00:00Z")
    replacement = rev("new", 0.012, supersedes="old", delta_semantics="absolute",
                      published="2025-02-05T00:00:00Z")
    compiled = compile_set([earlier, replacement])
    assert [item.revision_id for item in compiled.applied] == ["new"]
    assert np.isclose(compiled.delta_cost[0], -0.012)
    assert "old" in compiled.superseded


def test_a_chain_applies_only_the_operative_version():
    compiled = compile_set([
        rev("A", 0.030),
        rev("B", 0.020, supersedes="A", delta_semantics="absolute"),
        rev("C", 0.010, supersedes="B", delta_semantics="absolute"),
    ])
    assert [item.revision_id for item in compiled.applied] == ["C"]
    assert np.isclose(compiled.delta_cost[0], -0.010)


def test_unknown_delta_semantics_is_refused_at_construction():
    with pytest.raises(ValidationError) as caught:
        rev("r1", 0.01, delta_semantics="relative")
    assert "delta semantics" in str(caught.value)


# ---------------------------------------------------------- incorporation: documented vs assumed
def test_public_before_the_decision_without_a_record_is_labelled_an_assumption():
    revision = rev("early", 0.010, published=BEFORE_DECISION)
    compiled = compile_set([revision])
    assert revision.revision_id in compiled.incorporation_assumed
    assert revision.revision_id not in compiled.incorporation_documented
    assert np.allclose(compiled.delta_cost, 0.0)
    excluded = {item["revision_id"]: item for item in compiled.excluded}
    assert excluded["early"]["incorporation"] == "assumed"
    assert "assumption" in compiled.as_dict()["incorporation"]["assumption"]


def test_documented_incorporation_is_excluded_and_says_so():
    revision = rev("early", 0.010, published=BEFORE_DECISION,
                   incorporation="documented_incorporated", incorporated_in=VINTAGE)
    compiled = compile_set([revision])
    excluded = {item["revision_id"]: item for item in compiled.excluded}
    assert excluded["early"]["incorporation"] == "documented"
    assert excluded["early"]["incorporated_in"] == VINTAGE
    assert revision.revision_id in compiled.incorporation_documented
    assert not compiled.incorporation_assumed
    assert compiled.as_dict()["incorporation"]["assumption"] is None


def test_documented_exclusion_is_applied_because_the_base_model_omitted_it():
    revision = rev("early", 0.010, published=BEFORE_DECISION,
                   incorporation="documented_excluded")
    compiled = compile_set([revision])
    assert [item.revision_id for item in compiled.applied] == ["early"]
    assert np.isclose(compiled.delta_cost[0], -0.010)
    assert "early" in compiled.incorporation_omitted
    assert any("documented as excluded" in note for note in compiled.notes)


def test_documented_incorporation_in_another_vintage_is_refused():
    revision = rev("early", 0.010, published=BEFORE_DECISION,
                   incorporation="documented_incorporated", incorporated_in="other-vintage")
    with pytest.raises(ValidationError) as caught:
        compile_set([revision])
    assert "starting vintage" in str(caught.value)


def test_unknown_incorporation_status_is_refused_at_construction():
    with pytest.raises(ValidationError) as caught:
        rev("r1", 0.01, incorporation="maybe")
    assert "incorporation" in str(caught.value)
