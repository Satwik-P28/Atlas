"""Release security, multipart packaging and clean-install lifecycle tests.

No network. Every asset used here is built from bytes that the store has already
hashed, so the tests prove the same properties the workflow relies on: inputs are
validated before use, parts are hashed and rejected when missing, and an install
verifies and restores without replacing an existing snapshot.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml

from atlas.open_data import multipart
from atlas.open_data.distribution import InstallError, download, install, resolve_assets
from atlas.open_data.release import (
    ReleaseInputError, allowed_dataset_ids, build_plan, release_catalog,
    validate_dataset_ids, validate_filenames, validate_oversized, validate_tag,
)
from atlas.open_data.registry import Registry
from atlas.open_data.store import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/open-data-release.yml"


def _registry(tmp_path: Path, *, rights: str = "public_domain") -> Registry:
    payload = {
        "registry_version": 1,
        "reviewed_at": "2026-11-01T00:00:00Z",
        "datasets": [{
            "id": "test.dataset", "provider": "TEST", "title": "Test dataset",
            "description": "d", "official_source_url": "https://example.org",
            "download_endpoint": "https://example.org/x",
            "license_name": "PD", "license_url": "https://example.org/pd",
            "rights_class": rights, "rights_verified_at": "2026-01-01",
            "rights_evidence": "e", "commercial_use": True, "redistribution": True,
            "modification": True, "attribution_required": False, "attribution_text": "",
            "third_party_exclusions": [], "geographic_coverage": "US",
            "historical_coverage": {"start": None, "end": None},
            "update_frequency": "daily", "auth_required": False,
            "expected_size_bytes": 10, "schema_version": "1",
            "ingestion_status": "verified", "adapter": "archive", "formats": ["json"],
        }],
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Registry.load(path)


def _snapshot(tmp_path: Path, *, dataset_id: str = "sec.company_tickers",
              content: bytes = b'{"fields": [], "data": []}\n') -> tuple[SnapshotStore, object]:
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source.json"
    source.write_bytes(content)
    staging = store.new_staging(dataset_id)
    entry = store.add_file(staging, source, name="company_tickers_exchange.json")
    snapshot = store.commit(staging, {
        "dataset_id": dataset_id,
        "source": {"download_endpoint": "https://www.sec.gov/files/company_tickers_exchange.json"},
        "retrieval": {"completed_at": "2026-11-25T00:00:00Z"},
        "files": [entry],
    })
    return store, snapshot


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- input validation
def test_unknown_and_unsafe_dataset_ids_are_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(ReleaseInputError, match="unknown dataset"):
        validate_dataset_ids("test.dataset sec.companyfacts", registry)
    with pytest.raises(ReleaseInputError, match="malformed"):
        validate_dataset_ids("test.dataset; rm -rf /", registry)
    with pytest.raises(ReleaseInputError, match="malformed"):
        validate_dataset_ids("$(whoami)", registry)
    with pytest.raises(ReleaseInputError, match="duplicate"):
        validate_dataset_ids("test.dataset test.dataset", registry)
    with pytest.raises(ReleaseInputError, match="no dataset ids"):
        validate_dataset_ids("   ", registry)
    assert validate_dataset_ids("test.dataset", registry) == ["test.dataset"]


def test_a_dataset_whose_rights_do_not_allow_publication_is_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path, rights="local_use_only")
    with pytest.raises(ReleaseInputError, match="not redistributable"):
        validate_dataset_ids("test.dataset", registry)
    assert allowed_dataset_ids(registry) == set()


def test_release_tag_grammar() -> None:
    assert validate_tag("open-data-2026-11") == "open-data-2026-11"
    assert validate_tag("open-data-2026-11-r2") == "open-data-2026-11-r2"
    for value in ("open-data-2026-13", "latest", "open-data-2026-11;id", "", "2026-11"):
        with pytest.raises(ReleaseInputError):
            validate_tag(value)


def test_oversized_claims_must_be_approved_and_above_the_limit(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    accepted = validate_oversized("test.dataset=5000000000", registry)
    assert accepted[0]["raw_bytes"] == 5_000_000_000
    with pytest.raises(ReleaseInputError, match="not above"):
        validate_oversized("test.dataset=10", registry)
    with pytest.raises(ReleaseInputError, match="non-numeric"):
        validate_oversized("test.dataset=lots", registry)
    with pytest.raises(ReleaseInputError, match="may not be published"):
        validate_oversized("other.dataset=5000000000", registry)
    with pytest.raises(ReleaseInputError, match="dataset=bytes"):
        validate_oversized("test.dataset", registry)


def test_asset_filenames_must_belong_to_an_approved_dataset(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    names = ["test.dataset.tar.zst", "test.dataset.tar.zst.sha256", "test.dataset.parts.json",
             "test.dataset-period-2024q1.tar.zst"]
    assert validate_filenames(names, allowed_dataset_ids=allowed_dataset_ids(registry)) == names
    for bad in ("../../../etc/passwd", ".hidden", "test.dataset;rm.tar.zst",
                "other.dataset.tar.zst", "test dataset.tar.zst"):
        with pytest.raises(ReleaseInputError):
            validate_filenames([bad], allowed_dataset_ids=allowed_dataset_ids(registry))


def test_plan_is_the_only_validated_input() -> None:
    registry = Registry.load()
    plan = build_plan(["sec.company_tickers", "treasury.nominal_yields"],
                      "open-data-2026-11", "sec.financial_statement_data_sets=5709542274", registry)
    assert plan["release_tag"] == "open-data-2026-11"
    assert [item["dataset_id"] for item in plan["datasets"]] == [
        "sec.company_tickers", "treasury.nominal_yields"]
    assert plan["oversized"][0]["dataset_id"] == "sec.financial_statement_data_sets"


# ------------------------------------------------------------------ workflow policy
def test_workflow_never_interpolates_inputs_into_a_shell() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job_name, job in document["jobs"].items():
        for step in job["steps"]:
            run = step.get("run")
            if run:
                assert "${{" not in run, f"{job_name}: {step.get('name')} interpolates into a shell"


def test_workflow_pins_actions_and_minimises_permissions() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert document["permissions"] == {"contents": "read"}
    for job_name, job in document["jobs"].items():
        for step in job["steps"]:
            uses = step.get("uses")
            if uses:
                assert re.search(r"@[0-9a-f]{40}$", uses), f"{job_name}: {uses} is not pinned"
    for job_name in ("draft", "publish"):
        assert document["jobs"][job_name]["environment"] == "open-data-release"
        assert document["jobs"][job_name]["permissions"] == {"contents": "write"}
    for job_name in ("plan", "package"):
        assert document["jobs"][job_name]["permissions"] == {"contents": "read"}
    # Promotion happens in a second protected job that needs the verified draft.
    assert document["jobs"]["publish"]["needs"] == "draft"


def test_workflow_creates_a_draft_before_publishing() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--draft" in (ROOT / "scripts/release_step.py").read_text(encoding="utf-8")
    assert "inputs.mode == 'public'" in text
    assert "refuse an existing tag" in text.lower()
    # The draft is byte-verified before promotion, and promotion checks it again
    # without rebuilding it under a different tag.
    assert text.count("--require-byte-verification") == 2
    assert "--metadata-only" in text
    assert "check_release_environment.py" in text


def test_workflow_artifact_paths_are_single_rooted() -> None:
    """An artifact upload with two roots changes the layout on download.

    GitHub computes the artifact root as the common parent of the uploaded paths, so
    uploading `dist/`, `data/open_data/manifests/**` and `/tmp/acquire.json` together
    puts `dist/...` inside the artifact and downloading it to `dist` yields
    `dist/dist/...`. Each upload therefore names exactly one root, and each download
    restores it to the directory the next job expects.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    uploads: dict[str, str] = {}
    downloads: dict[str, str] = {}
    for job_name, job in document["jobs"].items():
        for step in job["steps"]:
            uses = str(step.get("uses") or "")
            if "upload-artifact" in uses:
                raw = str(step["with"]["path"])
                lines = [line.strip() for line in raw.replace("|", "\n").splitlines()
                         if line.strip()]
                assert len(lines) == 1, f"{job_name} uploads more than one path root: {lines}"
                assert "*" not in lines[0], f"{job_name} uploads a glob: {lines[0]}"
                uploads[step["with"]["name"]] = lines[0].rstrip("/")
            if "download-artifact" in uses:
                downloads[step["with"]["name"]] = str(step["with"]["path"]).rstrip("/")
    assert uploads["release-plan"] == "dist/release-plan.json"
    assert downloads["release-plan"] == "dist"
    assert uploads["release-package"] == "dist"
    assert downloads["release-package"] == "dist"
    assert uploads["release-manifests"] == "data/open_data/manifests"
    assert downloads["release-manifests"] == "data/open_data/manifests"


def test_publication_environment_must_require_reviewers() -> None:
    module = _script("check_release_environment")
    unprotected = module.evaluate({
        "name": "open-data-release", "protection_rules": [], "deployment_branch_policy": None,
    })
    assert unprotected["ok"] is False
    assert any("reviewer" in finding for finding in unprotected["findings"])
    self_review = module.evaluate({
        "name": "open-data-release",
        "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}],
                              "prevent_self_review": False}],
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
    })
    assert self_review["ok"] is False
    protected = module.evaluate({
        "name": "open-data-release",
        "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}],
                              "prevent_self_review": True}],
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
    })
    assert protected["ok"] is True
    assert protected["required_reviewers"] == 1


# ------------------------------------------------------------------ byte multipart
def test_byte_parts_reconstruct_the_original_file_exactly(tmp_path: Path) -> None:
    source = tmp_path / "archive.zip"
    source.write_bytes(bytes(range(256)) * 40)
    out = tmp_path / "parts"
    index = multipart.split_source(source, out, dataset_id="test.dataset",
                                    snapshot_id="snap", part_limit=4096)
    assert len(index["parts"]) == 3
    assert max(part["bytes"] for part in index["parts"]) <= 4096
    assert multipart.verify_parts(index, out)["ok"]
    destination = tmp_path / "rebuilt.zip"
    result = multipart.reconstruct(index, out, destination)
    assert result["status"] == "reconstructed"
    assert destination.read_bytes() == source.read_bytes()
    assert _sha(destination) == index["source"]["sha256"]
    again = multipart.reconstruct(index, out, destination)
    assert again["status"] == "already_present"


def test_missing_and_corrupt_parts_are_rejected_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "archive.zip"
    source.write_bytes(b"x" * 10_000)
    out = tmp_path / "parts"
    index = multipart.split_source(source, out, dataset_id="test.dataset",
                                    snapshot_id="snap", part_limit=4096)
    missing_name = index["parts"][1]["name"]
    (out / missing_name).unlink()
    report = multipart.verify_parts(index, out)
    assert report["missing"] == [missing_name]
    destination = tmp_path / "rebuilt.zip"
    with pytest.raises(multipart.MissingPartError):
        multipart.reconstruct(index, out, destination)
    assert not destination.exists()


def test_a_corrupt_part_is_detected(tmp_path: Path) -> None:
    source = tmp_path / "archive.zip"
    source.write_bytes(b"y" * 9000)
    out = tmp_path / "parts"
    index = multipart.split_source(source, out, dataset_id="test.dataset",
                                    snapshot_id="snap", part_limit=4096)
    target = out / index["parts"][0]["name"]
    payload = bytearray(target.read_bytes())
    payload[0] ^= 0xFF
    target.write_bytes(payload)
    report = multipart.verify_parts(index, out)
    assert not report["ok"]
    assert report["corrupt"]
    with pytest.raises(multipart.CorruptPartError):
        multipart.reconstruct(index, out, tmp_path / "rebuilt.zip")


# ---------------------------------------------------------------- period packages
def _financial_statement_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "financial_statement_data_sets.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("2023q4.zip", b"PK-q4-2023" * 50)
        bundle.writestr("2023q4_notes.zip", b"notes-2023q4")
        bundle.writestr("2024q1.zip", b"PK-q1-2024" * 50)
        bundle.writestr("2024q1_notes.zip", b"notes-2024q1")
    return archive


def test_period_parts_can_install_one_quarter(tmp_path: Path) -> None:
    source = _financial_statement_archive(tmp_path)
    out = tmp_path / "parts"
    index = multipart.build_period_parts(source, out, dataset_id="sec.financial_statement_data_sets",
                                         snapshot_id="snap", part_limit=1_900_000_000)
    assert index["mode"] == "period"
    assert [item["period"] for item in index["periods"]] == ["2023q4", "2024q1"]
    installed = multipart.restore_periods(index, out, tmp_path / "installed", periods=["2024q1"])
    names = sorted(path.name for path in (tmp_path / "installed").iterdir())
    assert names == ["2024q1.zip", "2024q1_notes.zip"]
    assert installed["files_installed"] == 2
    with zipfile.ZipFile(source) as bundle:
        assert (tmp_path / "installed/2024q1.zip").read_bytes() == bundle.read("2024q1.zip")
    # A second run is idempotent.
    again = multipart.restore_periods(index, out, tmp_path / "installed", periods=["2024q1"])
    assert again["files_already_present"] == 2


def test_missing_period_package_is_rejected(tmp_path: Path) -> None:
    source = _financial_statement_archive(tmp_path)
    out = tmp_path / "parts"
    index = multipart.build_period_parts(source, out, dataset_id="sec.financial_statement_data_sets",
                                         snapshot_id="snap")
    (out / index["parts"][0]["name"]).unlink()
    with pytest.raises(multipart.MissingPartError):
        multipart.restore_periods(index, out, tmp_path / "installed")
    with pytest.raises(multipart.MultipartError, match="unknown periods"):
        multipart.restore_periods(index, out, tmp_path / "installed", periods=["1999q1"])


# ------------------------------------------------------------- install lifecycle
def _package(tmp_path: Path, store: SnapshotStore, dataset_id: str) -> tuple[Path, Path]:
    builder = _script("build_open_data_package")
    package = tmp_path / f"{dataset_id}.tar.zst"
    index = tmp_path / f"{dataset_id}.index.json"
    code = builder.main([
        "--dataset", dataset_id, "--out", str(package), "--index", str(index),
        "--open-root", str(store.root), "--open-db", str(tmp_path / "open.db"),
    ])
    assert code == 0
    return package, index


def test_a_package_embeds_its_licence_terms(tmp_path: Path) -> None:
    import tarfile

    import zstandard

    store, _ = _snapshot(tmp_path)
    package, _ = _package(tmp_path, store, "sec.company_tickers")
    import io

    with package.open("rb") as raw:
        payload = zstandard.ZstdDecompressor().stream_reader(raw).read()
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        names = archive.getnames()
        licences = {"LICENSES.json": archive.extractfile("LICENSES.json").read().decode("utf-8")}
    assert "LICENSES.md" in names and "LICENSES.json" in names
    assert "ATTRIBUTION.md" in names and "PACKAGE_MANIFEST.json" in names
    payload = json.loads(licences["LICENSES.json"])
    assert payload["datasets"][0]["license_name"].startswith("U.S. federal government work")


def test_install_downloads_verifies_and_restores_then_is_idempotent(tmp_path: Path) -> None:
    registry = Registry.load()
    store, snapshot = _snapshot(tmp_path)
    package, _ = _package(tmp_path, store, "sec.company_tickers")
    index = {
        "schema": "atlas.open_data.release.v1",
        "release_tag": "open-data-2026-11",
        "assets": [{
            "dataset_id": "sec.company_tickers",
            "snapshot_id": snapshot.snapshot_id,
            "asset": package.name,
            "asset_bytes": package.stat().st_size,
            "asset_sha256": _sha(package),
            "url": package.as_uri(),
        }],
    }
    fresh = SnapshotStore(tmp_path / "fresh")
    result = install(registry, fresh, index, ["sec.company_tickers"],
                     cache_dir=tmp_path / "cache",
                     downloads_path=tmp_path / "downloads.json")
    assert result["failures"] == []
    assert result["restored"] == 1
    restored = fresh.snapshot_path("sec.company_tickers", snapshot.snapshot_id)
    assert restored.exists()
    check = fresh.verify(fresh.list_snapshots("sec.company_tickers")[0], deep=True)
    assert check["ok"]
    manifest = json.loads((restored / "manifest.json").read_text())
    assert manifest["restored_from"] == package.name
    downloads = json.loads((tmp_path / "downloads.json").read_text())
    assert downloads["downloads"][0]["sha256"] == _sha(package)
    # Nothing is replaced; a second install reports the snapshot as present.
    again = install(registry, fresh, index, ["sec.company_tickers"],
                    cache_dir=tmp_path / "cache",
                    downloads_path=tmp_path / "downloads.json")
    assert again["already_present"] == 1
    assert again["restored"] == 0


def test_install_refuses_a_dataset_that_may_no_longer_be_published(tmp_path: Path) -> None:
    registry = _registry(tmp_path, rights="local_use_only")
    index = {"assets": [{"dataset_id": "test.dataset", "asset": "test.dataset.tar.zst",
                         "url": "file:///nowhere"}]}
    with pytest.raises(InstallError, match="may no longer be distributed"):
        install(registry, SnapshotStore(tmp_path / "fresh"), index, ["test.dataset"],
                cache_dir=tmp_path / "cache", downloads_path=tmp_path / "downloads.json")


def test_download_rejects_a_hash_mismatch_and_removes_the_partial(tmp_path: Path) -> None:
    source = tmp_path / "asset.bin"
    source.write_bytes(b"z" * 5000)
    with pytest.raises(InstallError, match="sha256"):
        download(source.as_uri(), tmp_path / "cache/asset.bin",
                 expected_sha256="0" * 64)
    assert not (tmp_path / "cache/asset.bin").exists()
    assert not (tmp_path / "cache/asset.bin.part").exists()


def test_install_does_not_replace_different_bytes(tmp_path: Path) -> None:
    source = tmp_path / "asset.bin"
    source.write_bytes(b"a" * 100)
    target = tmp_path / "cache/asset.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"b" * 100)
    with pytest.raises(InstallError, match="refusing to replace"):
        download(source.as_uri(), target)


# --------------------------------------------------------------- release catalogue
def test_catalogue_separates_packaged_from_uploaded_and_verified(tmp_path: Path) -> None:
    registry = Registry.load()
    store, snapshot = _snapshot(tmp_path)
    package, _ = _package(tmp_path, store, "sec.company_tickers")
    sha = _sha(package)
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({
        "release_tag": "open-data-2026-11",
        "rights_source": "registry",
        "assets": [{"dataset_id": "sec.company_tickers", "snapshot_id": snapshot.snapshot_id,
                    "asset": package.name, "asset_bytes": package.stat().st_size,
                    "asset_sha256": sha, "rights_class": "public_domain"}],
    }))
    downloads_path = tmp_path / "downloads.json"
    downloads_path.write_text(json.dumps({"downloads": []}))
    catalog = release_catalog(registry, store, index_path=index_path,
                              downloads_path=downloads_path)
    row = next(item for item in catalog["datasets"]
               if item["dataset_id"] == "sec.company_tickers")
    assert row["state"] == "packaged"
    assert row["packages_built"][0]["sha256"] == sha
    assert row["packages_uploaded"] == []
    downloads_path.write_text(json.dumps({"downloads": [{
        "asset": package.name, "sha256": sha, "url": "https://example.org/" + package.name,
        "bytes": package.stat().st_size}]}))
    catalog = release_catalog(registry, store, index_path=index_path,
                              downloads_path=downloads_path)
    row = next(item for item in catalog["datasets"]
               if item["dataset_id"] == "sec.company_tickers")
    assert row["state"] == "download_verified"
    # A dataset with no committed manifest and no store is not called durable.
    other = next(item for item in catalog["datasets"]
                 if item["dataset_id"] == "sec.companyfacts")
    assert other["state"] != "download_verified"


def test_resolve_assets_reads_multipart_parts_from_the_index() -> None:
    index = {
        "assets": [{"dataset_id": "sec.financial_statement_data_sets", "asset": None,
                    "asset_bytes": 1234}],
        "multipart": {
            "sec.financial_statement_data_sets": {
                "mode": "period",
                "snapshot_id": "snap",
                "source": {"sha256": "a" * 64, "bytes": 2048},
                "parts": [
                    {"name": "sec.financial_statement_data_sets-period-2024q1.tar.zst",
                     "bytes": 1000, "sha256": "b" * 64, "period": "2024q1"},
                    {"name": "sec.financial_statement_data_sets-period-2023q4.tar.zst",
                     "bytes": 234, "sha256": "c" * 64, "period": "2023q4"},
                ],
                "periods": [{"period": "2023q4"}, {"period": "2024q1"}],
            },
        },
        "asset_base_url": "https://example.org/releases/download/open-data-2026-11",
    }
    resolved = resolve_assets(index, ["sec.financial_statement_data_sets"], periods=["2024q1"])
    assert len(resolved) == 1
    assert resolved[0]["asset"].endswith("2024q1.tar.zst")
    assert resolved[0]["url"].startswith("https://example.org/releases/download/")


# ------------------------------------------------- independent byte verification
from atlas.open_data.verification import expected_assets, verify_release  # noqa: E402


def _release_asset(name: str, path: Path, **overrides) -> dict:
    payload = {
        "name": name,
        "size": path.stat().st_size,
        "digest": f"sha256:{_sha(path)}",
        "browser_download_url": path.as_uri(),
        "url": None,
    }
    payload.update(overrides)
    return payload


def _release_index(tmp_path: Path, package: Path, snapshot_id: str) -> Path:
    index_path = tmp_path / "release-index.json"
    index_path.write_text(json.dumps({
        "schema": "atlas.open_data.release.v1",
        "release_tag": "open-data-2026-11",
        "assets": [{
            "dataset_id": "sec.company_tickers",
            "snapshot_id": snapshot_id,
            "asset": package.name,
            "asset_bytes": package.stat().st_size,
            "asset_sha256": _sha(package),
        }],
    }), encoding="utf-8")
    return index_path


def test_release_verification_downloads_hashes_and_restores(tmp_path: Path) -> None:
    store, snapshot = _snapshot(tmp_path)
    package, _ = _package(tmp_path, store, "sec.company_tickers")
    index_path = _release_index(tmp_path, package, snapshot.snapshot_id)
    release = {
        "html_url": "https://example.org/releases/tag/open-data-2026-11",
        "draft": False,
        "assets": [_release_asset(package.name, package),
                   _release_asset(index_path.name, index_path)],
    }
    report = verify_release(
        repo="Satwik-P28/Atlas", tag="open-data-2026-11", index_path=index_path,
        download_dir=tmp_path / "download", fresh_store=tmp_path / "fresh",
        release=release,
    )
    assert report["problems"] == []
    assert report["ok"] is True
    assert report["byte_verified_count"] == report["expected_assets"] == 2
    assert report["metadata_only_count"] == 0
    restored = report["restoration"]["packages"]["packages"][0]
    assert restored["snapshot_verified"] is True
    assert restored["idempotent"] is True
    assert restored["snapshots"][0]["snapshot_id"] == snapshot.snapshot_id


def test_release_verification_detects_missing_assets(tmp_path: Path) -> None:
    store, snapshot = _snapshot(tmp_path)
    package, _ = _package(tmp_path, store, "sec.company_tickers")
    index_path = _release_index(tmp_path, package, snapshot.snapshot_id)
    release = {"draft": False,
               "assets": [_release_asset(index_path.name, index_path)]}
    report = verify_release(
        repo="Satwik-P28/Atlas", tag="open-data-2026-11", index_path=index_path,
        download_dir=tmp_path / "download", fresh_store=tmp_path / "fresh",
        release=release,
    )
    assert report["ok"] is False
    assert package.name in report["missing"]
    assert any("not in the release" in problem for problem in report["problems"])


def test_release_verification_detects_corrupt_bytes(tmp_path: Path) -> None:
    store, snapshot = _snapshot(tmp_path)
    package, _ = _package(tmp_path, store, "sec.company_tickers")
    index_path = _release_index(tmp_path, package, snapshot.snapshot_id)
    tampered = tmp_path / "tampered" / package.name
    tampered.parent.mkdir()
    payload = bytearray(package.read_bytes())
    payload[-1] ^= 0xFF
    tampered.write_bytes(payload)
    assert tampered.stat().st_size == package.stat().st_size
    release = {"draft": False,
               "assets": [_release_asset(package.name, tampered),
                          _release_asset(index_path.name, index_path)]}
    report = verify_release(
        repo="Satwik-P28/Atlas", tag="open-data-2026-11", index_path=index_path,
        download_dir=tmp_path / "download", fresh_store=tmp_path / "fresh",
        release=release,
    )
    assert report["ok"] is False
    assert package.name in report["failed"]
    assert any("downloaded sha256" in problem for problem in report["problems"])


def test_a_split_period_package_survives_the_index_and_installs(tmp_path: Path) -> None:
    """Regression: the index dropped `split`, so a split period could not install."""
    index_module = _script("index_open_data_release")
    source = _financial_statement_archive(tmp_path)
    out = tmp_path / "parts"
    index = multipart.build_period_parts(
        source, out, dataset_id="sec.financial_statement_data_sets",
        snapshot_id="snap", part_limit=120)
    split = [part for part in index["parts"] if part.get("split")]
    assert split, "the fixture must produce at least one split period package"
    preserved = [index_module._index_part(part) for part in index["parts"]]
    payload = {
        "schema": "atlas.open_data.multipart.v1",
        "mode": "period",
        "dataset_id": "sec.financial_statement_data_sets",
        "snapshot_id": "snap",
        "source": index["source"],
        "parts": preserved,
    }
    sub_names = [entry["name"] for part in split for entry in part["split"]["parts"]]
    preserved_names = {member["name"] for part in preserved
                       for member in ((part.get("split") or {}).get("parts") or [part])}
    assert all(name in preserved_names for name in sub_names)
    assert any(name not in {part["name"] for part in preserved} for name in sub_names)
    catalogue = {"assets": [{"dataset_id": "sec.financial_statement_data_sets", "asset": None}],
                 "multipart": {"sec.financial_statement_data_sets": payload}}
    assert sub_names[0] in {entry["asset"] for entry in expected_assets(catalogue)}
    resolved = resolve_assets(catalogue, ["sec.financial_statement_data_sets"])
    assert [item["asset"] for item in resolved] == [
        member["name"] for part in preserved
        for member in ((part.get("split") or {}).get("parts") or [part])]
    restored = multipart.restore_periods(payload, out, tmp_path / "installed")
    assert restored["periods"] == 2
    with zipfile.ZipFile(source) as bundle:
        for name in ("2024q1.zip", "2024q1_notes.zip", "2023q4.zip"):
            assert (tmp_path / "installed" / name).read_bytes() == bundle.read(name)
    again = multipart.restore_periods(payload, out, tmp_path / "installed")
    assert again["files_already_present"] == restored["files_installed"]
