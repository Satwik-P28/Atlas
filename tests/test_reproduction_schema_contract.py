"""The Phase 9.2 reproduction must track the current migration chain, not a frozen schema number.

Every migration added after 9.2 previously broke hosted CI in a way that looked like a
serialisation defect: ``scripts/reproduce_phase9_2.py`` asserted ``fresh_schema == 13``
while the chain had moved to 14. Reproducibility means "this build reproduces the package
on a database migrated by this build", so the script must compare against
``LATEST_VERSION``. These tests pin that contract; they execute the real script rather
than inspecting its source.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reproduce_phase9_2.py"
ARTIFACT = ROOT / "artifacts" / "phase9_2_application.atlas"


def test_reproduction_script_runs_against_the_current_migration_chain() -> None:
    if not ARTIFACT.is_file():
        pytest.skip("the committed Phase 9.2 application package is absent")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    summary = json.loads(completed.stdout)
    assert summary["exit"] == 0
    assert summary["differences"] == {}

    sys.path.insert(0, str(ROOT / "src"))
    from atlas.storage.migrations import LATEST_VERSION

    written = json.loads((ROOT / "artifacts" / "phase9_2_reproduction.json").read_text())
    assert written["fresh_schema"] == LATEST_VERSION
    assert written["execution"]["reproduced"] is True
    assert written["execution"]["differences"] == {}
    # Byte-for-byte determinism: regenerating the reproduction must reproduce the committed
    # artifact exactly, not merely an equivalent value per share.
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", "--", "artifacts/phase9_2_reproduction.json"],
        cwd=ROOT,
    )
    assert unchanged.returncode == 0, "the reproduction rewrote a committed artifact"


def test_reproduction_script_does_not_pin_a_literal_schema_number() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'result["fresh_schema"] == LATEST_VERSION' in source
    assert "# Phase 9.2 application package on a clean schema-13" not in source
