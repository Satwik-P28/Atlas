"""The external beta package must be complete and must not contain fabricated results."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_results_schema_defines_the_session_record() -> None:
    schema = _read("docs/beta_eval_results.schema.json")
    assert schema["$id"] == "atlas.beta_eval_results.v1"
    session = schema["$defs"]["session"]
    for field in ("participant_id", "role", "tasks", "rubric", "questionnaire", "consent", "defects"):
        assert field in session["required"], f"the session record does not require {field}"
    assert session["properties"]["rubric"]["properties"], "the rubric has no dimensions"


def test_recorded_results_are_empty_or_complete() -> None:
    results = _read("docs/beta_eval_results.json")
    assert results["schema"] == "atlas.beta_eval_results.v1"
    assert results["status"] in {"not_run", "partial", "complete"}
    if results["status"] == "not_run":
        assert results["sessions"] == [], "not_run must not carry sessions"
    for session in results["sessions"]:
        assert session["consent"]["recorded"] is not None


def test_results_label_matches_the_release_gate_registry() -> None:
    results = _read("docs/beta_eval_results.json")
    gates = _read("docs/RELEASE_GATES.json")
    assert results["release_label"] == gates["release_label"]


def test_package_documents_every_required_artifact() -> None:
    text = (ROOT / "docs" / "BETA_EVALUATION_PACKAGE.md").read_text(encoding="utf-8").lower()
    for required in (
        "participant instructions",
        "task sheet",
        "evaluation rubric",
        "feedback questionnaire",
        "defect report template",
        "consent",
        "raw results",
    ):
        assert required in text, f"the beta package does not include {required!r}"


def test_user_validation_gate_points_at_the_recorded_absence() -> None:
    """The registry has three groups now; the validation milestone must still say NOT RUN."""
    gates = _read("docs/RELEASE_GATES.json")
    milestones = {item["id"]: item for item in gates["validation_milestones"]}
    gate = milestones["independent_human_evaluation"]
    assert gate["state"] == "NOT RUN"
    assert "BETA_PROGRAM" in gate["command"] or "beta" in gate["command"].lower()
    evidence = gate["evidence"].lower()
    assert "no independent evaluators" in evidence or "no participants" in evidence
    usability = milestones["external_usability"]
    assert usability["state"] == "NOT RUN"
    assert "no fabricated" in usability["evidence"].lower() or "zero participants" in usability["evidence"].lower()
