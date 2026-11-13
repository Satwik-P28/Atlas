"""Phase 9.6.2 artifacts stay sanitized and keep the failed gate visible."""

from __future__ import annotations

import json
from pathlib import Path

ARTIFACT = Path("artifacts/phase9_6_2_evaluation.json")
FORBIDDEN = {"question", "answer", "evidence", "context", "question_text", "reference_answer"}


def _walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_artifact_is_sanitized():
    payload = json.loads(ARTIFACT.read_text())
    assert not (FORBIDDEN & set(_walk(payload)))


def test_methodology_is_versioned_and_historical_results_untouched():
    payload = json.loads(ARTIFACT.read_text())
    assert payload["methodology_version"] == "9.6.2"
    assert payload["supersedes"] is None
    assert "phase9_6_1_evaluation.json" in payload["historical_results_preserved"]
    prior = json.loads(Path("artifacts/phase9_6_1_evaluation.json").read_text())
    assert prior["methodology_version"] == "9.6.1"
    assert prior["gates"]["answer_presence@5"] is False


def test_failed_cell_localization_gate_stays_failed():
    payload = json.loads(ARTIFACT.read_text())
    assert payload["metrics"]["cell_localization_rate"] < 0.20
    assert payload["gates"]["cell_localization"] is False
