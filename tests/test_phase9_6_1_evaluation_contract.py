"""Phase 9.6.1 evaluation contract: exact K, content fingerprint, sanitized artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.research import evaluation_v2 as ev
from atlas.research.evaluation import Question
from atlas.research.evaluation_v2 import (
    abstention_metrics, evaluation_fingerprint, licensed_exposure, required_metric, sanitize,
)

CONFIG = {"methodology_version": "9.6.1", "k": 10}


def question(answer: str = "1,577") -> Question:
    return Question(
        question_id="fb-001", company="3M", doc_type="10k", period="FY2018",
        question="What was net sales?", answer=answer, target_document_id="DOC-1",
        issuer_id="ISS-1", cutoff="2019-06-01T00:00:00Z", availability_time=None,
        target_accession="0000066740-19-000010",
    )


def test_answer_change_changes_fingerprint():
    first = evaluation_fingerprint([question("1,577")], CONFIG)
    second = evaluation_fingerprint([question("1,578")], CONFIG)
    assert first != second


def test_question_text_change_changes_fingerprint():
    original = question()
    edited = question()
    edited.question = "What were net sales?"
    assert evaluation_fingerprint([original], CONFIG) != evaluation_fingerprint([edited], CONFIG)


def test_config_change_changes_fingerprint():
    assert (evaluation_fingerprint([question()], CONFIG)
            != evaluation_fingerprint([question()], {**CONFIG, "k": 5}))


def test_fingerprint_publishes_no_licensed_text():
    digest = evaluation_fingerprint([question()], CONFIG)
    assert len(digest) == 64 and "net sales" not in digest


def test_gate_cannot_read_a_metric_at_the_wrong_k():
    metrics = {"document_recall@10": 1.0}
    with pytest.raises(KeyError):
        required_metric(metrics, "document_recall@5")
    assert required_metric({"document_recall@5": 0.5}, "document_recall@5") == 0.5


def test_abstention_metrics_are_balanced_and_explicit():
    result = abstention_metrics(positives=[False, False, True, False],
                                negatives=[True, True, False, False])
    assert result["precision"] == 0.6667       # 2 of 3 abstentions were unanswerable
    assert result["recall"] == 0.5             # 2 of 4 negatives caught
    assert result["false_abstention_rate"] == 0.25  # 1 of 4 answerable questions refused
    assert result["true_negative_abstentions"] == 3


def test_sanitize_removes_licensed_fields_recursively():
    payload = {"schema": "atlas.phase9_6.evaluation.v1",
               "records": [{"question_id": "fb-001", "question": "What?", "answer": "1577",
                            "nested": {"evidence": "x" * 120}}]}
    cleaned = sanitize(payload)
    assert cleaned == {"schema": "atlas.phase9_6.evaluation.v1",
                       "records": [{"question_id": "fb-001", "nested": {}}]}


def test_committed_artifacts_contain_no_prohibited_fields():
    for path in sorted(Path("artifacts").glob("*.json")):
        payload = json.loads(path.read_text())
        assert licensed_exposure(payload) == [], \
            f"{path} leaks licensed text: {licensed_exposure(payload)[:5]}"


def test_local_trace_is_git_ignored():
    ignore = Path(".gitignore").read_text()
    assert "var/" in ignore or "phase9_6_1_eval_trace" in ignore
