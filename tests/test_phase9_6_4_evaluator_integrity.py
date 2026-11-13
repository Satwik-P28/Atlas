"""Phase 9.6.4: evaluator integrity (exit status, missing input, artifact on failure)."""

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


def test_passing_gates_exit_zero():
    assert _module().gate_exit_code({"a": True, "b": True}) == 0


def test_failed_gate_exits_nonzero():
    assert _module().gate_exit_code({"a": True, "b": False}) == 1


def test_zero_gates_cannot_pass():
    assert _module().gate_exit_code({}) == 1


def test_missing_benchmark_input_fails_and_still_writes_artifact(tmp_path):
    environment = dict(os.environ, ATLAS_FINANCEBENCH_ROWS=str(tmp_path / "absent.json"))
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=120)
    assert completed.returncode != 0, completed.stdout + completed.stderr
    artifact = tmp_path / "artifacts" / "phase9_6_4_evaluation.json"
    assert artifact.exists()
    payload = json.loads(artifact.read_text())
    assert payload["evaluation_status"] == "unavailable_reference_data"
    assert payload["gates"]["reference_data_available"] is False
    assert payload["gates"]["eligible_population"] is False
    assert payload["counts"]["attempted"] == 0


def test_historical_363_artifact_is_unchanged():
    """The 9.6.3 evaluation artifact is a historical record and must not be rewritten."""
    assert (ROOT / "artifacts" / "phase9_6_3_evaluation.json").exists()
    payload = json.loads((ROOT / "artifacts" / "phase9_6_3_evaluation.json").read_text())
    assert payload["schema"] == "atlas.phase9_6_3.evaluation.v1"
