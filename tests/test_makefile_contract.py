"""The Makefile is a documented interface: it must parse.

A wrapped comment line without a leading ``#`` makes GNU make fail with "missing separator"
before it runs anything, so every documented workflow (``make demo``, ``make test``,
``make focus-demo``) is unusable while the test suite still passes — because nothing in the
suite invoked make. This test invokes it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_makefile_parses_and_help_runs() -> None:
    completed = subprocess.run(
        ["make", "--no-print-directory", "help"], cwd=ROOT, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    output = completed.stdout
    for target in ("install", "test", "demo", "focus-demo", "serve"):
        assert target in output, f"`make help` does not document the {target!r} target"


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_every_help_listed_target_exists() -> None:
    # ``-p`` dumps make's database; ``-n`` only prints commands. Question mode (``-q``)
    # exits non-zero whenever a target is out of date, so its status is not the signal here.
    listing = subprocess.run(
        ["make", "--no-print-directory", "-n", "-p"], cwd=ROOT, capture_output=True, text=True
    )
    assert "missing separator" not in listing.stderr, listing.stderr[-3000:]
    declared = {
        line.split(":", 1)[0]
        for line in listing.stdout.splitlines()
        if line and not line.startswith((" ", "\t", "#", ".")) and ":" in line
    }
    help_output = subprocess.run(
        ["make", "--no-print-directory", "help"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    documented: set[str] = set()
    for line in help_output.splitlines():
        if not line.strip() or line.startswith(" "):
            continue
        name = line.split()[0]
        if "{" in name and name.endswith("}"):
            prefix, _, rest = name.partition("{")
            for option in rest[:-1].split(","):
                documented.add(prefix + option)
        else:
            documented.add(name)
    missing = sorted(name for name in documented if name not in declared)
    assert not missing, f"`make help` documents targets that do not exist: {missing}"
