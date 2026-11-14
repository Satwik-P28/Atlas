"""Phase 9.6.4: evaluator integrity (exit status, metrics, missing input, artifact on failure)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9_6_4_evaluate.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase9_6_4_evaluate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_methodology_version_is_9_6_4():
    assert _module().METHODOLOGY_VERSION == "9.6.4"


def test_passing_gates_exit_zero():
    assert _module().gate_exit_code({"a": True, "b": True}) == 0


def test_failed_gate_exits_nonzero():
    assert _module().gate_exit_code({"a": True, "b": False}) == 1


def test_zero_gates_cannot_pass():
    assert _module().gate_exit_code({}) == 1


def test_zero_denominator_is_not_evaluable():
    assert _module().rate(0, 0) is None
    assert _module().rate(5, 0) is None
    assert _module().rate(1, 2) == 0.5


def test_confusion_matrix_hand_computed():
    # TP=3, FP=1, TN=4, FN=2
    rates = _module().confusion_rates(
        true_positives=3, false_positives=1, true_negatives=4, false_negatives=2)
    assert rates["assertion_precision"] == 0.75          # 3/4
    assert rates["abstention_precision"] == round(4 / 6, 4)
    assert rates["answerable_recall"] == round(3 / 5, 4)  # 3/(3+2)
    assert rates["unanswerable_recall"] == 0.8            # 4/(4+1)
    assert rates["false_assertion_rate"] == 0.2           # 1/5
    assert rates["false_abstention_rate"] == 0.4          # 2/5


def test_empty_confusion_populations_are_not_perfect_scores():
    rates = _module().confusion_rates(
        true_positives=0, false_positives=0, true_negatives=0, false_negatives=0)
    assert rates["assertion_precision"] is None
    assert rates["abstention_precision"] is None
    assert rates["answerable_recall"] is None
    assert rates["unanswerable_recall"] is None


def test_hashlib_is_imported_for_citation_path():
    module = _module()
    assert hasattr(module, "hashlib")
    assert callable(module.hashlib.sha256)


def test_missing_benchmark_input_exits_two_and_writes_artifact(tmp_path):
    environment = dict(os.environ, ATLAS_FINANCEBENCH_ROWS=str(tmp_path / "absent.json"))
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=120)
    assert completed.returncode == 2, completed.stdout + completed.stderr
    artifact = tmp_path / "artifacts" / "phase9_6_4_evaluation.json"
    assert artifact.exists()
    payload = json.loads(artifact.read_text())
    assert payload["evaluation_status"] == "unavailable_reference_data"
    assert payload["methodology_version"] == "9.6.4"
    assert payload["gates"]["reference_data_available"] is False
    assert payload["gates"]["eligible_population"] is False
    assert payload["counts"]["attempted"] == 0


def test_historical_363_artifact_is_unchanged():
    """The 9.6.3 evaluation artifact is a historical record and must not be rewritten."""
    assert (ROOT / "artifacts" / "phase9_6_3_evaluation.json").exists()
    payload = json.loads((ROOT / "artifacts" / "phase9_6_3_evaluation.json").read_text())
    assert payload["schema"] == "atlas.phase9_6_3.evaluation.v1"
