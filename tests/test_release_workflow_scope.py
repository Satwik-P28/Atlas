"""Dataset releases and software releases must not share a publication path.

`release.yml` publishes a wheel to PyPI from a *published GitHub release*. A dataset
release is also a published GitHub release, so without an explicit guard it would try to
verify and upload assets that are not the software distribution.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def test_the_pypi_workflow_is_limited_to_software_version_tags() -> None:
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "if: startsWith(github.event.release.tag_name, 'v')" in text
    assert "jobs:\n  publish:" in text


def test_the_dataset_workflow_uses_its_own_tag_namespace_and_no_wheel() -> None:
    text = (WORKFLOWS / "open-data-release.yml").read_text(encoding="utf-8")
    assert "open-data-YYYY-MM" in text
    lower = text.lower()
    for forbidden in ("pypi", "twine", "atlas_quant-", "gh-action-pypi-publish"):
        assert forbidden not in lower, forbidden
    # Repository dispatch and manual dispatch only: no push or release trigger that could
    # collide with a software tag.
    assert "workflow_dispatch:" in text
    assert "types: [published]" not in text
