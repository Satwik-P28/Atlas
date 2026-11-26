"""The release gate registry must stay honest and internally consistent.

A gate registry is only useful if it cannot quietly claim readiness while a mandatory gate is
failing. These tests pin the vocabulary, the required gates per group, the summary arithmetic, and
the rule that an unresolved data-rights, history, licensing or publication gate forbids a
public-release recommendation.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "RELEASE_GATES.json"

GROUPS = ("engineering_gates", "distribution_gates", "validation_milestones")

REQUIRED_ENGINEERING = {
    "financial_correctness",
    "historical_integrity",
    "security",
    "packaged_installation",
    "flagship_workflow",
    "research_reproducibility",
    "artifact_integrity",
    "documentation_accuracy",
    "mcp_interoperability",
    "browser_certification",
    "performance",
}

REQUIRED_DISTRIBUTION = {
    "data_redistribution_rights",
    "historical_exposure_remediation",
    "software_licensing",
    "third_party_notices",
    "authorized_publication_destination",
}

REQUIRED_VALIDATION = {
    "independent_human_evaluation",
    "external_usability",
    "adoption",
    "external_contributions",
}

# A public release needs these resolved, whichever group they sit in.
BLOCKING_GATES = {
    "financial_correctness",
    "security",
    "flagship_workflow",
    "data_redistribution_rights",
    "historical_exposure_remediation",
    "software_licensing",
    "authorized_publication_destination",
}

ALLOWED_DECISIONS = {
    "READY FOR PUBLIC BETA",
    "READY FOR EXPERIMENTAL PUBLIC PREVIEW",
    "READY FOR PRIVATE RELEASE CANDIDATE",
    "NOT READY FOR RELEASE",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def all_gates(registry: dict) -> list[dict]:
    return [gate for group in GROUPS for gate in registry[group]]


def test_registry_declares_every_required_gate(registry: dict) -> None:
    expected = {
        "engineering_gates": REQUIRED_ENGINEERING,
        "distribution_gates": REQUIRED_DISTRIBUTION,
        "validation_milestones": REQUIRED_VALIDATION,
    }
    for group, required in expected.items():
        ids = {gate["id"] for gate in registry[group]}
        assert required <= ids, f"{group} is missing {sorted(required - ids)}"
        assert len(registry[group]) == len(ids), f"{group} contains duplicate gate ids"
    every = [gate["id"] for gate in all_gates(registry)]
    assert len(every) == len(set(every)), "a gate id appears in more than one group"


def test_gate_states_use_only_the_allowed_vocabulary(registry: dict) -> None:
    allowed = set(registry["states"])
    for gate in all_gates(registry):
        assert gate["state"] in allowed, f"{gate['id']} has an undefined state {gate['state']!r}"
        assert gate["evidence"].strip(), f"{gate['id']} has no evidence"
        assert gate["command"].strip(), f"{gate['id']} has no reproduction command"


def test_summary_matches_the_gates(registry: dict) -> None:
    summary = registry["summary"]
    for group in GROUPS:
        counts = Counter(gate["state"] for gate in registry[group])
        recorded = summary[group]
        for state, count in counts.items():
            key = state.lower().replace(" ", "_")
            assert recorded.get(key) == count, f"{group}: {state} is {count}, summary says {recorded.get(key)}"
        assert sum(recorded.values()) == len(registry[group]), (
            f"{group}: summary counts do not add up to the number of gates")


def test_decision_is_one_of_the_allowed_conclusions(registry: dict) -> None:
    assert registry["decision"] in ALLOWED_DECISIONS


def test_public_release_is_forbidden_while_a_mandatory_gate_fails(registry: dict) -> None:
    states = {gate["id"]: gate["state"] for gate in all_gates(registry)}
    unresolved = [
        gate for gate in BLOCKING_GATES if states.get(gate) in {"FAIL", "BLOCKED", "NOT RUN"}
    ]
    if unresolved:
        assert registry["decision"] not in {
            "READY FOR PUBLIC BETA",
            "READY FOR EXPERIMENTAL PUBLIC PREVIEW",
        }, (
            "the registry recommends a public release while mandatory gates are unresolved: "
            f"{sorted(unresolved)}"
        )


def test_a_private_candidate_may_not_leave_an_engineering_gate_failed(registry: dict) -> None:
    failing = [gate["id"] for gate in registry["engineering_gates"] if gate["state"] in {"FAIL", "BLOCKED"}]
    if failing:
        assert registry["decision"] == "NOT READY FOR RELEASE", (
            f"engineering gates {sorted(failing)} are unresolved but the candidate is recommended")


def test_candidate_commit_is_on_this_branch(registry: dict) -> None:
    """In the distribution candidate this is a recorded absence, not a failure.

    The registry names the commit the artifacts were built from in the development repository.
    A single-commit sanitized distribution candidate does not contain that object, so the check
    reports why it cannot run instead of failing or pretending it passed.
    """
    candidate = registry["candidate_commit"]
    exists = subprocess.run(["git", "cat-file", "-e", f"{candidate}^{{commit}}"], cwd=ROOT)
    if exists.returncode != 0:
        pytest.skip(f"candidate commit {candidate} belongs to the development repository's "
                    "history and is not present in this single-commit distribution candidate")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=ROOT)
    assert ancestor.returncode == 0, f"candidate commit {candidate} is not an ancestor of HEAD"


def test_readiness_report_states_the_same_decision(registry: dict) -> None:
    report = (ROOT / "docs" / "RELEASE_READINESS.md").read_text(encoding="utf-8")
    assert registry["decision"] in report, (
        "the human-readable readiness report does not state the registry's decision"
    )
