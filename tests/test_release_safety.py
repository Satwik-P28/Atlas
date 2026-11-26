"""Release-safety tooling must behave as documented, including when it cannot run.

The scanner is allowed to be inconclusive; it is not allowed to be wrong. These tests pin
the severity mapping, the inconclusive verdict, the restricted-path classification, the
determinism of the sanitized archive and the fact that the archive cannot contain an
excluded path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scan():
    return _load("scan_dependencies", "scripts/scan_dependencies.py")


@pytest.fixture(scope="module")
def archive():
    return _load("build_sanitized_archive", "scripts/build_sanitized_archive.py")


# --------------------------------------------------------------- dependency scan
def test_severity_mapping_prefers_the_advisory_database(scan) -> None:
    assert scan.normalise_severity({"database_specific": {"severity": "HIGH"}}) == "high"
    assert scan.normalise_severity({"database_specific": {"severity": "medium"}}) == "moderate"
    assert scan.normalise_severity({"severity": [{"score": "9.8"}]}) == "critical"
    assert scan.normalise_severity({"severity": [{"score": "7.5"}]}) == "high"
    assert scan.normalise_severity({}) == "unknown"


def test_severity_counts_are_complete(scan) -> None:
    counts = scan.summarise([
        {"severity": "critical"}, {"severity": "high"}, {"severity": "high"},
        {"severity": "low"}, {"severity": "made-up"},
    ])
    assert counts["critical"] == 1
    assert counts["high"] == 2
    assert counts["low"] == 1
    assert counts["unknown"] == 1
    assert counts["moderate"] == 0


def test_an_offline_scan_is_inconclusive_not_clean(scan) -> None:
    report = scan.build_report(ROOT, network=False)
    assert report["verdict"] == "not_run"
    assert report["exit_code"] == 3
    assert report["python"]["status"] == "not_run"
    assert "network disabled" in report["python"]["reason"]


def test_python_inventory_reports_installed_versions(scan) -> None:
    packages = scan.python_packages()
    assert len(packages) > 3
    assert any(package["name"].lower() == "numpy" for package in packages)
    assert all(package["version"] for package in packages)


# ------------------------------------------------------------ sanitized archive
def test_restricted_paths_are_excluded_and_code_is_kept(archive) -> None:
    included, excluded = archive.select([
        {"path": "fixtures/market/nasdaq_prices.csv", "sha": "a"},
        {"path": "fixtures/market/alphavantage_daily.json", "sha": "b"},
        {"path": ".env", "sha": "c"},
        {"path": "src/atlas/market/prices.py", "sha": "d"},
        {"path": "pyproject.toml", "sha": "e"},
    ])
    assert [entry["path"] for entry in included] == ["src/atlas/market/prices.py", "pyproject.toml"]
    assert {entry["path"] for entry in excluded} == {
        "fixtures/market/nasdaq_prices.csv",
        "fixtures/market/alphavantage_daily.json",
        ".env",
    }


def test_archive_is_deterministic_and_cannot_contain_an_excluded_path(archive, tmp_path) -> None:
    entries = [
        entry for entry in archive.commit_entries("HEAD")
        if entry["path"] in {"pyproject.toml", "README.md", "src/atlas/__init__.py"}
    ]
    assert len(entries) == 3
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    written = archive.write_archive(entries, first)
    archive.write_archive(entries, second)
    assert first.read_bytes() == second.read_bytes()
    assert written["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()

    excluded = [{"path": "fixtures/market/nasdaq_prices.csv", "sha": "0"}]
    verification = archive.verify_archive(first, excluded)
    assert verification["clean"] is True
    assert verification["files"] == 3


def test_archive_verification_detects_a_leaked_path(archive, tmp_path) -> None:
    entries = [entry for entry in archive.commit_entries("HEAD")
               if entry["path"] == "pyproject.toml"]
    target = tmp_path / "leak.tar.gz"
    archive.write_archive(entries, target)
    verification = archive.verify_archive(target, [{"path": "pyproject.toml", "sha": "0"}])
    assert verification["clean"] is False
    assert verification["excluded_present"] == ["pyproject.toml"]


# --------------------------------------------------------- packaged-install harness
def test_packaged_install_reports_a_missing_wheel_instead_of_passing(tmp_path) -> None:
    harness = _load("verify_packaged_install", "scripts/verify_packaged_install.py")
    result = harness.main(["--dist", str(tmp_path / "empty"), "--workdir", str(tmp_path),
                           "--out", str(tmp_path / "report.json")])
    assert result == 2
    assert not (tmp_path / "report.json").exists()


def test_packaged_install_uses_a_clean_environment(monkeypatch) -> None:
    harness = _load("verify_packaged_install", "scripts/verify_packaged_install.py")
    monkeypatch.setenv("PYTHONPATH", "/should/not/leak")
    monkeypatch.setenv("ATLAS_DB", "leaked.db")
    env = harness.clean_env()
    assert "PYTHONPATH" not in env
    assert "ATLAS_DB" not in env


def test_licence_is_applied_and_metadata_declares_it() -> None:
    """The licence is applied, not merely staged.

    Phase 10.6 asserted the opposite (a staged text and no root LICENSE) because applying a licence
    is the copyright holder's act. The holder authorised Apache-2.0 with a named copyright line, so
    this test now pins the applied state: the root text is the canonical Apache-2.0 text, the notice
    names the holder, the staged duplicate is gone, and the package metadata ships all three files.
    """
    canonical = (ROOT / "licenses" / "Apache-2.0.txt").read_text(encoding="utf-8")
    assert "Apache License" in canonical and "Version 2.0, January 2004" in canonical
    assert len(canonical.encode("utf-8")) > 10_000
    applied = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert applied == canonical, "the applied licence must be the verbatim canonical text"
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Satwik Peddireddi" in notice
    third_party = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "lightweight-charts" in third_party and "not covered" in third_party.lower()
    assert not (ROOT / "licenses" / "PENDING-AUTHORIZATION.md").exists()
    assert (ROOT / "licenses" / "AUTHORIZATION-RECORD.md").is_file()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "Apache-2.0"' in pyproject
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        assert name in pyproject, f"{name} is not declared in license-files"
