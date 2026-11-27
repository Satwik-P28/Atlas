"""One release version, reported everywhere.

A package that ships one version and reports another makes every bug report and artifact
manifest ambiguous. The previous tree did exactly that: ``pyproject.toml`` said 0.2.0 while
``atlas.__version__`` said 0.1.0, and the HTTP API advertised a third number. This test pins
the single-source contract: the Python attribute is authoritative, ``pyproject.toml`` reads
it dynamically, the web package uses the release label, and installed metadata agrees.
"""

from __future__ import annotations

import json
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import atlas

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_reads_the_version_from_the_package() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert "version" not in project, "the version must not be duplicated in pyproject.toml"
    assert project["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "atlas.__version__"}


def test_release_label_matches_the_pep440_version() -> None:
    assert atlas.__version__ == "0.2.0b2"
    assert atlas.__release_label__ == "v0.2.0-beta.2"


def test_web_package_uses_the_release_label() -> None:
    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == atlas.__release_label__.lstrip("v")


def test_installed_metadata_agrees_with_the_package() -> None:
    try:
        installed = metadata.version("atlas-quant")
    except metadata.PackageNotFoundError:  # pragma: no cover - unpackaged source tree
        pytest.skip("atlas-quant is not installed in this environment")
    assert installed == atlas.__version__


def test_http_api_separates_contract_version_from_release_version(tmp_path) -> None:
    pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")
    from fastapi.testclient import TestClient

    from atlas.terminal.api import API_CONTRACT_VERSION, create_app

    app = create_app(tmp_path / "no.db")
    # The OpenAPI contract version is pinned by the API contract test; it is not the release.
    assert app.version == API_CONTRACT_VERSION == "0.4.0"
    health = TestClient(app).get("/api/health").json()
    assert health["release_version"] == atlas.__version__
