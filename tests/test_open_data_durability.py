"""Durability, restore and market-layer tests.

These tests never touch the network. They prove that a committed manifest is compared
to real bytes, that a corrupted or absent snapshot is reported as such, and that a
distribution package can be restored with its exact snapshot identity on a clean store.
"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from atlas.open_data.durable import inventory, restore_package
from atlas.open_data.market import import_local, provider_catalog
from atlas.open_data.registry import Registry, validate_payload
from atlas.open_data.store import SnapshotStore


def _registry(tmp_path: Path) -> Registry:
    payload = {
        "registry_version": 1,
        "datasets": [{
            "id": "test.dataset", "provider": "TEST", "title": "Test", "description": "d",
            "official_source_url": "https://example.org", "download_endpoint": "https://example.org/x",
            "license_name": "PD", "license_url": "https://example.org/pd",
            "rights_class": "public_domain", "rights_verified_at": "2026-01-01",
            "rights_evidence": "e", "commercial_use": True, "redistribution": True,
            "modification": True, "attribution_required": False, "attribution_text": "",
            "third_party_exclusions": [], "geographic_coverage": "US",
            "historical_coverage": {"start": None, "end": None}, "update_frequency": "daily",
            "auth_required": False, "expected_size_bytes": 3, "schema_version": "1",
            "ingestion_status": "acquired", "adapter": "archive", "formats": ["csv"],
        }],
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Registry.load(path)


def _snapshot(store: SnapshotStore, tmp_path: Path) -> tuple[str, str]:
    source = tmp_path / "payload.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    staging = store.new_staging("test.dataset")
    entry = store.add_file(staging, source, name="payload.csv")
    snapshot = store.commit(staging, {
        "dataset_id": "test.dataset", "provider": "TEST", "files": [entry],
        "source": {"download_endpoint": "https://example.org/x"},
    })
    return snapshot.snapshot_id, snapshot.manifest_sha256


def _export_manifest(store: SnapshotStore, root: Path, dataset: str, snapshot_id: str) -> None:
    import shutil
    target = root / dataset / f"{snapshot_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(store.snapshot_path(dataset, snapshot_id) / "manifest.json", target)


def test_inventory_distinguishes_verified_missing_and_corrupt(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "store")
    registry = _registry(tmp_path)
    manifests = tmp_path / "manifests"
    snapshot_id, _ = _snapshot(store, tmp_path)
    _export_manifest(store, manifests, "test.dataset", snapshot_id)

    report = inventory(store, registry, manifests_root=manifests)
    assert report["by_status"] == {"verified": 1}
    assert report["latest_verified_datasets"] == 1
    assert report["items"][0]["redistributable"] is True

    # Corrupt one byte: the stored manifest still claims the old hash, so deep
    # verification must fail rather than trusting the manifest.
    payload = store.snapshot_path("test.dataset", snapshot_id) / "files" / "payload.csv"
    payload.chmod(0o644)
    payload.write_text("a,b\n9,9\n", encoding="utf-8")
    corrupt = inventory(store, registry, manifests_root=manifests)
    assert corrupt["by_status"] == {"corrupt": 1}
    assert corrupt["latest_verified_datasets"] == 0
    assert corrupt["recovery"][0]["dataset_id"] == "test.dataset"

    # Remove the snapshot entirely: the committed manifest is preserved, so this is
    # recoverable evidence of a missing snapshot rather than an unapproved dataset.
    import shutil
    shutil.rmtree(store.dataset_path if hasattr(store, "dataset_path") else store.snapshot_path("test.dataset", snapshot_id))
    missing = inventory(store, registry, manifests_root=manifests)
    assert missing["by_status"] == {"missing": 1}
    assert missing["items"][0]["committed"] is True
    assert missing["items"][0]["present"] is False


def test_restore_package_reproduces_the_exact_snapshot(tmp_path: Path) -> None:
    zstd = pytest.importorskip("zstandard")
    store = SnapshotStore(tmp_path / "store")
    snapshot_id, _ = _snapshot(store, tmp_path)
    snapshot = store.list_snapshots("test.dataset")[0]

    package_root = tmp_path / "package"
    target = package_root / "datasets" / "test.dataset" / snapshot_id
    (target / "files").mkdir(parents=True)
    for entry in snapshot.files:
        source = snapshot.path / "files" / entry["path"]
        (target / "files" / entry["path"]).write_bytes(source.read_bytes())
    (target / "manifest.json").write_text(json.dumps(snapshot.manifest), encoding="utf-8")
    (package_root / "PACKAGE_MANIFEST.json").write_text(json.dumps({
        "package_version": 1,
        "datasets": [{
            "dataset_id": "test.dataset", "snapshot_id": snapshot_id,
            "manifest_sha256": snapshot.manifest_sha256,
        }],
    }), encoding="utf-8")

    archive = tmp_path / "package.tar.zst"
    with archive.open("wb") as raw:
        with zstd.ZstdCompressor(level=3).stream_writer(raw) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for path in sorted(package_root.rglob("*")):
                    if path.is_file():
                        tar.add(path, arcname=path.relative_to(package_root).as_posix())

    restored_store = SnapshotStore(tmp_path / "restored")
    result = restore_package(restored_store, archive)
    assert result["restored"] == 1
    restored = restored_store.list_snapshots("test.dataset")
    assert [snapshot.snapshot_id for snapshot in restored] == [snapshot_id]
    assert restored_store.verify(restored[0], deep=True)["ok"] is True

    again = restore_package(restored_store, archive)
    assert again["already_present"] == 1
    assert again["restored"] == 0


def test_market_layer_refuses_synthetic_production_prices(tmp_path: Path) -> None:
    catalog = provider_catalog()
    assert catalog["redistributable_provider_found"] is False
    assert all(provider["redistribution"] is False for provider in catalog["providers"])

    bars = tmp_path / "bars.csv"
    bars.write_text("date,open,high,low,close,volume\n2026-01-02,1,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        import_local(tmp_path / "atlas.db", bars, security_id="SEC-x", mic="XNYS",
                     source_name="synthetic demo prices")


def test_issuer_authored_sec_archives_are_not_classified_public_domain() -> None:
    """17 USC 105 covers agency works, not registrant-authored filings."""
    registry = Registry.load()
    for dataset_id in (
        "sec.companyfacts",
        "sec.submissions",
        "sec.financial_statement_data_sets",
        "sec.insider_transactions",
        "sec.form13f",
        "sec.form_n_port",
        "sec.form_n_cen",
    ):
        dataset = registry.get(dataset_id)
        assert dataset.rights_class.value == "redistributable_conditions", dataset_id
        assert dataset["attribution_required"] is True, dataset_id
    # Agency-authored metadata keeps the public-domain class.
    assert registry.get("sec.company_tickers").rights_class.value == "public_domain"
    # Uncleared third-party exclusions keep the raw notes archive out of releases.
    assert registry.get("sec.notes_data_sets")["third_party_exclusions"]


def test_registry_validation_refuses_a_public_domain_claim_for_issuer_content() -> None:
    """The corrected semantics are enforced, not just documented.

    A future entry cannot reintroduce the categorical claim by hand: the class and the
    licence text are both checked against the issuer-authored fact.
    """
    registry = Registry.load()
    entry = dict(registry.get("sec.companyfacts").to_dict())
    entry["rights_class"] = "public_domain"
    entry["license_name"] = "U.S. federal government work - public domain (17 USC 105)"
    errors = validate_payload({"registry_version": 1, "datasets": [entry]})
    assert any("issuer-authored content cannot be classified public_domain" in error
               for error in errors), errors

    licence_only = dict(registry.get("sec.companyfacts").to_dict())
    licence_only["license_name"] = "U.S. federal government work - public domain"
    errors = validate_payload({"registry_version": 1, "datasets": [licence_only]})
    assert any("cannot carry a public-domain licence claim" in error for error in errors)

    # Every issuer-authored entry states the conditional basis, and the agency-authored
    # metadata stays public domain.
    for dataset in registry:
        if dataset.get("issuer_authored"):
            assert dataset.rights_class.value == "redistributable_conditions", dataset.id
            assert "public domain" not in dataset["license_name"].lower(), dataset.id
            assert dataset.get("third_party_exclusions") is not None, dataset.id
    assert registry.get("sec.company_tickers").rights_class.value == "public_domain"
    assert not registry.get("sec.company_tickers").get("issuer_authored")


def test_published_rights_fields_match_the_current_registry() -> None:
    """A published index must never keep describing a superseded rights class.

    Acquisition-time manifests record the class as it stood when the bytes were
    fetched; the registry decision supersedes it. These artefacts must therefore be
    re-derived with ``--refresh-rights`` after a reclassification.
    """
    root = Path(__file__).resolve().parents[1]
    registry = Registry.load()
    index = root / "data/open_data/releases/index.json"
    if index.exists():
        payload = json.loads(index.read_text(encoding="utf-8"))
        for asset in payload["assets"]:
            dataset = registry.get(asset["dataset_id"])
            assert asset["rights_class"] == dataset.rights_class.value, asset["dataset_id"]
            assert asset["license_name"] == dataset["license_name"], asset["dataset_id"]
    metrics = root / "artifacts/open_data_phase2.json"
    if metrics.exists():
        payload = json.loads(metrics.read_text(encoding="utf-8"))
        for entry in payload.get("datasets") or []:
            dataset = registry.get(entry["dataset_id"])
            assert entry["rights_class"] == dataset.rights_class.value, entry["dataset_id"]
