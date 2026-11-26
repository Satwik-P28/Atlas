"""Distribution rights must stay complete, current and enforced.

Two independently checkable properties:

* the source-rights inventory covers every tracked data path, so a new fixture cannot be
  committed without a stated rights basis;
* the distribution audit's classification and scan logic behave as documented, and the
  current release tree contains no restricted vendor data or credentials.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "DATA_RIGHTS_INVENTORY.json"


def _audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_distribution", ROOT / "scripts" / "audit_distribution.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_inventory_entries_are_well_formed() -> None:
    inventory = _inventory()
    classes = set(inventory["rights_classes"])
    identifiers = set()
    for entry in inventory["entries"]:
        assert entry["id"] not in identifiers, f"duplicate inventory id {entry['id']}"
        identifiers.add(entry["id"])
        assert entry["rights_class"] in classes
        assert entry["origin"].strip()
        assert entry["basis"].strip()
        assert entry["verification"].strip()
        assert entry["paths"], f"{entry['id']} declares no paths"
        assert isinstance(entry["contains_personal_data"], bool)
        assert isinstance(entry["contains_executable_code"], bool)


def test_every_tracked_data_path_has_a_rights_entry() -> None:
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=ROOT, text=True
    ).splitlines()
    entries = _inventory()["entries"]
    data_paths = [
        path
        for path in paths
        if path.startswith(("fixtures/", "artifacts/", "docs/"))
        or path in {"README.md", "ATLAS_MASTER_SPEC.md", "PHASE9_2_FINAL_ACCEPTANCE.md"}
    ]
    uncovered = [
        path
        for path in data_paths
        if not any(fnmatch.fnmatch(path, pattern) for entry in entries for pattern in entry["paths"])
    ]
    assert not uncovered, f"{len(uncovered)} tracked data paths have no rights entry: {uncovered[:10]}"


def test_restricted_vendor_entry_does_not_match_the_current_tree() -> None:
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=ROOT, text=True
    ).splitlines()
    restricted = [entry for entry in _inventory()["entries"] if entry["rights_class"] == "restricted_vendor"]
    assert restricted, "the historical vendor exposure must be recorded, not deleted"
    for entry in restricted:
        assert entry["redistribution"] == "not_permitted"
        assert entry["blocks_public_release"] is True
    matched = [
        path
        for path in paths
        if any(fnmatch.fnmatch(path, pattern) for entry in restricted for pattern in entry["paths"])
    ]
    assert matched == [], f"restricted vendor data is tracked in the release tree: {matched}"


def test_classification_separates_vendor_data_from_adapter_code() -> None:
    module = _audit_module()
    assert module.classify_path("fixtures/market/nasdaq_JPM.csv") == "restricted_vendor"
    assert module.classify_path("fixtures/market/ibm_daily_alphavantage.json") == "restricted_vendor"
    assert module.classify_path("src/atlas/ingestion/market_alphavantage.py") == "vendor_adapter_code"
    assert module.classify_path(".env") == "secret_like"
    assert module.classify_path("docs/USER_GUIDE.md") == "none"


def test_scan_reports_restricted_and_secret_paths() -> None:
    module = _audit_module()
    found = module.scan_paths(
        [
            "fixtures/market/nasdaq_JPM.csv",
            "config/credentials.json",
            "src/atlas/cli.py",
        ]
    )
    assert found["restricted_vendor"] == ["fixtures/market/nasdaq_JPM.csv"]
    assert found["secret_like"] == ["config/credentials.json"]


def test_release_tree_contains_no_credentials_or_known_secret_shapes() -> None:
    report = _audit_module().build_report(ROOT)
    assert report["current_tree"]["secret_like_paths"] == []
    assert report["current_tree"]["secret_content_findings"] == []
    assert report["current_tree"]["restricted_vendor_paths"] == []
    assert report["current_tree"]["clean"] is True


def test_history_exposure_is_reported_with_the_refs_that_keep_it_alive() -> None:
    report = _audit_module().build_report(ROOT)
    exposed = report["history"]["restricted_vendor_paths_reachable"]
    if not exposed:  # pragma: no cover - only after an authorised history rewrite
        assert report["verdict"] == "clean"
        return
    assert report["verdict"] == "history_exposed"
    for item in exposed:
        assert item["classification"] == "restricted_vendor"
        assert item["added_by"], f"{item['path']} has no adding commit"
        assert item["reachable_from_refs"], f"{item['path']} is not reachable from any ref"
